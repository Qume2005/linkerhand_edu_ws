#!/usr/bin/env bash
# test-iso.sh — 生产端 QEMU 一键启动 ISO 测试（BIOS/UEFI × Persistent/Live）
#
# 四种用法：
#   test-iso.sh <iso>                      # BIOS，默认 Persistent 行为（无 writable.img，即 live）
#   test-iso.sh <iso> --uefi               # UEFI
#   test-iso.sh <iso> --persist [--uefi]   # 持久化验证：附加 writable.img，写文件→重启→断言仍在
#   test-iso.sh <iso> --live   [--uefi]    # Live 验证：不附加 writable.img，写文件→重启→断言消失
#
# 持久化原理（免去 GRUB 菜单自动化）：
#   casper 的 persistent 内核参数只有在「找到 writable 分区」时才启用持久化，
#   找不到就回退内存（live 行为）。所以：
#     --persist：附加标签 writable 的 ext4 img 作第二块盘 → casper 命中 → 持久化生效。
#     --live  ：不附加 writable.img → casper 找不到 writable 分区 → 回退内存 → live 行为。
#   两种模式都不需要自动化点击 GRUB 菜单。
#
# 环境变量：
#   BUILD_DIR     构建中间件目录（默认 /tmp）
#   MEM           QEMU 内存 MB（默认 4096）
#   WRITABLE_GB   --persist 的 writable.img 大小 GB（默认 4）
#   HEADLESS=1    无显示（-display none -serial stdio），供 CI
#   INTERACTIVE=1 交互模式（默认）；用户在 VM 内手动操作，脚本据此打印 PASS/FAIL
#   CI=1          全自动模式（实验性；cloud-init/自动登录+脚本）
#
# 详见 packaging/iso/docs/test-iso-design.md 或 packaging/iso/README.md。
set -Eeuo pipefail

#-------------------- 全局变量 --------------------------------------------------
BUILD_DIR="${BUILD_DIR:-/tmp}"
MEM="${MEM:-4096}"
WRITABLE_GB="${WRITABLE_GB:-4}"
ISO=""
MODE="default"          # default | persist | live
UEFI=0
PROG_NAME="$(basename "$0")"

# 标记文件（VM 内写入，跨重启判定）
MARK_FILE="persist-test"
MARK_PATH="\$HOME/$MARK_FILE"   # VM 内执行时用的字面路径（转义 $HOME）

#-------------------- 日志与颜色 ------------------------------------------------
log()  { printf '\n\033[1;34m[test-iso]\033[0m %s\n' "$*"; }
warn() { printf '\n\033[1;33m[test-iso WARN]\033[0m %s\n' "$*" >&2; }
err()  { printf '\n\033[1;31m[test-iso ERROR]\033[0m %s\n' "$*" >&2; }
die()  { err "$*"; exit 1; }

#-------------------- 用法 ------------------------------------------------------
usage() {
    cat << EOF
用法: $PROG_NAME <iso> [模式选项] [显示选项]

模式（默认 = BIOS + 无 writable.img，即 live 行为）:
  (无)                 BIOS 启动，不附加 writable.img（快速可用性验证）
  --uefi               UEFI 启动（可与其他模式组合，位置任意）
  --persist            持久化验证：附加 writable.img，两轮启动断言文件跨重启仍在
  --live               Live 验证：不附加 writable.img，两轮启动断言文件重启后消失

显示:
  (默认)               -display gtk -serial stdio（本地图形窗口 + 串口控制台）
  HEADLESS=1           -display none -serial stdio（无显示，供 CI）

自动化:
  (默认)               INTERACTIVE=1 交互模式：启动 VM、提示用户在 VM 内操作、
                                      用户关机后脚本继续第二轮
  CI=1                 全自动模式（实验性）：尝试 cloud-init/自动登录写入与检测

环境变量:
  BUILD_DIR=${BUILD_DIR}      构建中间件目录
  MEM=${MEM}            QEMU 内存 (MB)
  WRITABLE_GB=${WRITABLE_GB}   writable.img 大小 (GB，仅 --persist)
  HEADLESS                 1=无显示
  INTERACTIVE              1=交互模式（默认）
  CI                       1=全自动模式（实验性）

示例:
  $PROG_NAME out/linkerhand-edu-2026.06.10-amd64.iso
  $PROG_NAME out/linkerhand-edu-2026.06.10-amd64.iso --uefi
  $PROG_NAME out/linkerhand-edu-2026.06.10-amd64.iso --persist
  $PROG_NAME out/linkerhand-edu-2026.06.10-amd64.iso --live --uefi
  HEADLESS=1 $PROG_NAME out/xxx.iso --persist
EOF
}

#-------------------- 依赖检查 --------------------------------------------------
check_dep() {
    command -v "$1" >/dev/null 2>&1 || die "缺少依赖 '$1'。请安装：sudo apt install -y qemu-system-x86 $2"
}

check_common_deps() {
    check_dep qemu-system-x86_64 qemu-system-x86
    # mkfs.ext4 仅在 --persist 需要
}

#-------------------- KVM / 加速器 ----------------------------------------------
# 输出 echo：启用 KVM 时为 "-enable-kvm"，否则为 "-accel tcg"（并 warn）。
pick_accel() {
    if [ -e /dev/kvm ] && [ -r /dev/kvm ] && [ -w /dev/kvm ]; then
        echo "-enable-kvm"
        echo "-cpu host"
    else
        warn "KVM 不可用（/dev/kvm 缺失或无权限），回退 TCG 软件模拟，速度会显著变慢。"
        warn "若宿主机支持虚拟化，请确保 kvm 模块加载且当前用户在 kvm 组：sudo usermod -aG kvm \$USER"
        echo "-accel tcg"
        echo "-cpu qemu64,+avx,+sse4.1"
    fi
}

#-------------------- OVMF 路径探测（UEFI） -------------------------------------
# 返回 OVMF_CODE 路径（stdout）。找不到则 die 并提示 apt install ovmf。
# 候选顺序对应不同发行版/包名的安装位置。
find_ovmf_code() {
    local candidate
    for candidate in \
        "/usr/share/OVMF/OVMF_CODE.fd" \
        "/usr/share/OVMF/OVMF_CODE_4M.fd" \
        "/usr/share/OVMF/OVMF.fd" \
        "/usr/share/ovmf/OVMF_CODE.fd" \
        "/usr/share/ovmf/OVMF_CODE_4M.fd" \
        "/usr/share/ovmf/OVMF.fd" \
        "/usr/share/edk2/ovmf/OVMF_CODE.fd" \
        "/usr/share/edk2/ovmf/OVMF_CODE_4M.fd"; do
        if [ -f "$candidate" ]; then
            echo "$candidate"
            return 0
        fi
    done
    die "未找到 OVMF 固件（OVMF_CODE.fd / OVMF_CODE_4M.fd / OVMF.fd）。探测过：
  /usr/share/OVMF/OVMF_CODE.fd
  /usr/share/OVMF/OVMF_CODE_4M.fd
  /usr/share/OVMF/OVMF.fd
  /usr/share/ovmf/OVMF_CODE.fd
  /usr/share/ovmf/OVMF_CODE_4M.fd
  /usr/share/ovmf/OVMF.fd
  /usr/share/edk2/ovmf/OVMF_CODE.fd
  /usr/share/edk2/ovmf/OVMF_CODE_4M.fd
请安装：sudo apt install -y ovmf"
}

# 给定 OVMF_CODE 路径，定位同目录 OVMF_VARS.fd 并复制成可写副本到 BUILD_DIR。
# stdout = 可写 VARS 副本路径。找不到 VARS 源则 die。
prepare_ovmf_vars() {
    local code_path="$1"
    local code_dir vars_src vars_dst code_basename vars_basename
    code_dir="$(dirname "$code_path")"
    code_basename="$(basename "$code_path")"

    # 根据 CODE 文件名推断 VARS 文件名：OVMF_CODE_4M.fd → OVMF_VARS_4M.fd
    # 回退：不含 _4M 时仍用 OVMF_VARS.fd（兼容旧发行版）
    if [[ "$code_basename" == *_4M.fd ]]; then
        vars_basename="${code_basename/CODE_4M/VARS_4M}"
    else
        vars_basename="OVMF_VARS.fd"
    fi
    vars_src="$code_dir/$vars_basename"

    # 部分发行版（如 Debian）VARS 在 OVMF_CODE_4M.fd 同级；2MB 布局为 OVMF_VARS.fd
    if [ ! -f "$vars_src" ]; then
        # 尝试 4M 变体回退，以及跨目录回退
        for vars_src in \
            "$code_dir/$vars_basename" \
            "$code_dir/OVMF_VARS.fd" \
            "$code_dir/../OVMF_VARS.fd" \
            "$code_dir/OVMF_VARS_4M.fd" \
            "/usr/share/OVMF/OVMF_VARS.fd" \
            "/usr/share/OVMF/OVMF_VARS_4M.fd" \
            "/usr/share/ovmf/OVMF_VARS.fd" \
            "/usr/share/ovmf/OVMF_VARS_4M.fd" \
            "/usr/share/edk2/ovmf/OVMF_VARS.fd"; do
            [ -f "$vars_src" ] && break
        done
    fi
    [ -f "$vars_src" ] || die "未找到 OVMF_VARS.fd 源（与 OVMF_CODE.fd 同目录预期）。code=$code_path"

    # 可写副本（QEMU pflash 第二片必须可写）。文件名带进程号避免并发冲突。
    vars_dst="$BUILD_DIR/OVMF_VARS.test-iso.$$.fd"
    cp "$vars_src" "$vars_dst"
    chmod 644 "$vars_dst"
    echo "$vars_dst"
}

#-------------------- 显示参数 --------------------------------------------------
# stdout = 显示相关 QEMU 参数串
pick_display() {
    if [ "${HEADLESS:-0}" = "1" ]; then
        echo "-display none -serial stdio"
    else
        echo "-display gtk -serial stdio"
    fi
}

#-------------------- 公共启动函数 ----------------------------------------------
# 参数：
#   $1 = iso 路径
#   $2 = uefi 标志（1/0）
#   $3 = writable.img 路径（空 = 不附加持久化盘）
# 启动 QEMU 并阻塞等待其退出。QEMU 退出码透传（即使非零也不被 set -e 杀掉）。
#
# 注意：本函数不直接被 `if launch_qemu ...` 调用以读取 $?——那会拿到被 `!`/`if`
# 取反的值。请用 run_qemu_capture 包装来拿真实退出码。
launch_qemu() {
    local iso="$1"
    local uefi="$2"
    local writable="$3"

    [ -f "$iso" ] || die "ISO 不存在: $iso"

    local accel display qemu_args
    accel="$(pick_accel)"
    display="$(pick_display)"

    qemu_args=(
        qemu-system-x86_64
        -m "$MEM"
        $accel
        -cdrom "$iso"
        -boot d
    )

    # 持久化盘（virtio 磁盘）；标签 writable 由 mkfs.ext4 -L 写入，casper 扫描命中
    if [ -n "$writable" ]; then
        [ -f "$writable" ] || die "writable.img 不存在: $writable"
        qemu_args+=(-drive "file=$writable,format=raw,if=virtio")
    fi

    # UEFI：pflash 第一片只读 CODE，第二片可写 VARS 副本
    if [ "$uefi" = "1" ]; then
        local code_path vars_path
        code_path="$(find_ovmf_code)"
        vars_path="$(prepare_ovmf_vars "$code_path")"
        log "UEFI 固件：CODE=$code_path  VARS(可写副本)=$vars_path"
        qemu_args+=(
            -drive "if=pflash,format=raw,readonly=on,file=$code_path"
            -drive "if=pflash,format=raw,file=$vars_path"
        )
    fi

    qemu_args+=($display)

    log "QEMU 启动参数：${qemu_args[*]}"
    "${qemu_args[@]}"
}

# 包装 launch_qemu：临时关掉 errexit 以便捕获 QEMU 的真实退出码。
# 真实退出码写入全局 QEMU_RC。调用方读 $QEMU_RC。
# 使用 $- 内建判断 errexit 是否开启，避免 `set +o | grep` 在无匹配时返回 1 被 set -e 杀掉。
QEMU_RC=0
run_qemu_capture() {
    if [[ $- == *e* ]]; then
        set +e
        launch_qemu "$@"
        QEMU_RC=$?
        set -e
    else
        launch_qemu "$@"
        QEMU_RC=$?
    fi
    return 0
}

#-------------------- 从 ISO 文件名提取版本（用于 writable img 命名）-------------
# 输入 iso 文件名，stdout 输出 sanitized 版本标签
derive_version_tag() {
    local iso_base tag
    iso_base="$(basename "$ISO")"
    # linkerhand-edu-2026.06.10-amd64.iso → 2026.06.10-amd64
    tag="${iso_base%.iso}"
    tag="${tag#linkerhand-edu-}"
    # 兜底：去除任何非 [A-Za-z0-9._-] 的字符，避免文件名异常
    tag="$(printf '%s' "$tag" | tr -c 'A-Za-z0-9._-' '_')"
    [ -n "$tag" ] || tag="unknown"
    echo "$tag"
}

#-------------------- 准备 writable.img ----------------------------------------
# stdout = writable.img 路径
prepare_writable_img() {
    local tag img
    tag="$(derive_version_tag)"
    img="$BUILD_DIR/writable-$tag.img"

    if [ -f "$img" ]; then
        log "复用已存在的 writable.img：$img（删除以强制重建）"
    else
        log "创建 writable.img：$img（${WRITABLE_GB}G，ext4，标签 writable）"
        truncate -s "${WRITABLE_GB}G" "$img"
        # -F：强制对常规文件建文件系统；-L writable：casper 扫描的关键标签
        if ! mkfs.ext4 -F -L writable "$img" >/dev/null 2>&1; then
            die "mkfs.ext4 失败。请确保已安装：sudo apt install -y e2fsprogs"
        fi
    fi
    echo "$img"
}

#-------------------- 两轮断言（交互 / CI）-------------------------------------
# 参数：
#   $1 = writable.img 路径（空 = 不附加，用于 --live 与默认）
#   $2 = 期望：persist（第二轮文件应在）| live（第二轮文件应消失）
run_two_round_assertion() {
    local writable="$1"
    local expect="$2"

    local interactive="${INTERACTIVE:-1}"
    [ "${CI:-0}" = "1" ] && interactive=0

    log "===== 第一轮：启动并写入标记 ====="
    if [ "$interactive" = "1" ]; then
        cat << EOF

  ┌──────────────────────────────────────────────────────────────────┐
  │ 交互模式：第一轮启动                                             │
  │                                                                  │
  │ 1. VM 启动后，进入桌面/登录界面后打开终端，执行：                │
  │        echo ok > $MARK_PATH                                      │
  │                                                                  │
  │ 2. 确认写入后，在 VM 内正常关机（poweroff）。                    │
  │                                                                  │
  │ 脚本会等待 QEMU 退出后自动进入第二轮。                           │
  └──────────────────────────────────────────────────────────────────┘
EOF
        printf '%s' "按回车启动第一轮 QEMU..."
        read -r _ || true
    else
        warn "CI 全自动模式（实验性）：假定镜像内置 cloud-init 或自动登录脚本会写入 $MARK_PATH。"
        warn "若 VM 内没有对应自动化，第一轮可能未写入，第二轮断言将失败——请退回交互模式。"
    fi

    run_qemu_capture "$ISO" "$UEFI" "$writable"
    if [ "$QEMU_RC" -ne 0 ]; then
        warn "第一轮 QEMU 非零退出（码 $QEMU_RC）。继续第二轮以判定。"
    fi

    log "===== 第二轮：重启并检查标记 ====="
    if [ "$interactive" = "1" ]; then
        cat << EOF

  ┌──────────────────────────────────────────────────────────────────┐
  │ 交互模式：第二轮启动                                             │
  │                                                                  │
  │ 1. VM 启动后，打开终端检查标记文件（路径见下方）：               │
  │        test -f $MARK_PATH && echo FOUND || echo MISSING          │
  │                                                                  │
  │ 2. 根据输出，关机后在下方提示处输入结果：                        │
  │      persist 模式 → FOUND  = PASS（文件仍在 = 持久化生效）       │
  │      persist 模式 → MISSING= FAIL（持久化未生效）                │
  │      live    模式 → MISSING= PASS（文件消失 = live 行为正确）    │
  │      live    模式 → FOUND  = FAIL（意外持久化）                  │
  │                                                                  │
  │ 脚本等待 QEMU 退出后询问判定结果。                               │
  └──────────────────────────────────────────────────────────────────┘
EOF
        printf '%s' "按回车启动第二轮 QEMU..."
        read -r _ || true
    else
        log "CI 模式：第二轮启动（同样假定镜像内有自动检测逻辑，否则请用交互模式）。"
    fi

    run_qemu_capture "$ISO" "$UEFI" "$writable"
    if [ "$QEMU_RC" -ne 0 ]; then
        warn "第二轮 QEMU 非零退出（码 $QEMU_RC）。"
    fi

    # 结果判定
    if [ "$interactive" = "1" ]; then
        local answer
        printf '\n%s' "第二轮 VM 内检查结果？输入 FOUND 或 MISSING（回车=FOUND）："
        read -r answer || true
        answer="${answer:-FOUND}"
        judge_result "$expect" "$answer"
    else
        # CI 模式：无法在 VM 内自动断言文件存在性（需镜像内自动化协助），
        # 此处仅依据两轮 QEMU 均成功启动给出「启动层 PASS」，
        # 并明确告知文件存在性断言需镜像内置脚本回写宿主侧（未来扩展点）。
        log "CI 模式只能自动断言『QEMU 启动成功』。文件存在性断言需要镜像内置 cloud-init 写状态到共享通道（未实现）。"
        log "建议：CI=1 仅用于启动冒烟；持久化语义验证请用默认交互模式。"
        log "两轮 QEMU 均已退出 → 启动层 PASS（文件存在性未断言）。"
    fi
}

# 依据期望与实际观察给出最终 PASS/FAIL
judge_result() {
    local expect="$1"
    local observed="$2"
    local result
    case "$expect" in
        persist)
            if [ "$observed" = "FOUND" ]; then
                result="PASS"
                log "PASS：持久化生效（标记文件跨重启仍在）。"
            else
                result="FAIL"
                err "FAIL：持久化未生效（标记文件重启后消失）。"
                err "排查：① grub.cfg/loopback.cfg 是否含 persistent；② writable.img 标签是否为 writable（blkid）；③ writable.img 是否作为独立盘被附加。"
            fi
            ;;
        live)
            if [ "$observed" = "MISSING" ]; then
                result="PASS"
                log "PASS：Live 行为正确（标记文件重启后消失）。"
            else
                result="FAIL"
                err "FAIL：意外持久化（标记文件重启后仍在）。"
                err "排查：是否误附加了 writable.img？--live 不应附加任何持久化盘。"
            fi
            ;;
        *)
            die "内部错误：未知期望 $expect"
            ;;
    esac
    if [ "$result" = "FAIL" ]; then
        exit 1
    fi
}

#-------------------- 单轮启动（默认 / --uefi 快速验证）------------------------
run_single_boot() {
    log "单轮启动验证（$([ "$UEFI" = "1" ] && echo UEFI || echo BIOS)）"
    if [ "${INTERACTIVE:-1}" != "1" ] && [ "${CI:-0}" = "1" ]; then
        warn "CI 模式：无图形界面下仅能验证 QEMU 进程启动成功，桌面可用性需人工确认。"
    else
        log "VM 启动后请目视确认能进入桌面/登录界面，然后关机。脚本据 QEMU 退出码报告。"
    fi
    run_qemu_capture "$ISO" "$UEFI" ""
    if [ "$QEMU_RC" -eq 0 ]; then
        log "PASS：QEMU 启动并正常退出（退出码 0）。"
    else
        err "FAIL：QEMU 异常退出（码 $QEMU_RC）。"
        exit "$QEMU_RC"
    fi
}

#-------------------- 参数解析 --------------------------------------------------
parse_args() {
    [ $# -eq 0 ] && { usage; die "缺少参数。"; }

    # --help 优先
    case "$1" in
        -h|--help|help) usage; exit 0 ;;
    esac

    ISO="$1"; shift

    while [ $# -gt 0 ]; do
        case "$1" in
            --uefi)    UEFI=1; shift ;;
            --persist) MODE="persist"; shift ;;
            --live)    MODE="live"; shift ;;
            -h|--help) usage; exit 0 ;;
            *) die "未知参数：$1（可用：--uefi --persist --live）" ;;
        esac
    done

    [ -f "$ISO" ] || die "ISO 文件不存在：$ISO"

    # 互斥说明：MODE 是单值变量，parser 每个 --flag 只赋值一次（后者覆盖前者），
    # 故 --persist 与 --live 不可能同时成立——最后出现的那个生效。无需额外断言。
}

#-------------------- 主流程 ----------------------------------------------------
main() {
    parse_args "$@"
    check_common_deps

    mkdir -p "$BUILD_DIR"

    log "ISO     : $ISO"
    log "模式    : $MODE"
    log "UEFI    : $([ "$UEFI" = "1" ] && echo YES || echo NO)"
    log "BUILD_DIR: $BUILD_DIR"
    log "内存    : ${MEM}MB"

    case "$MODE" in
        default)
            # 默认：BIOS/UEFI 单轮启动，无持久化盘（live 行为）
            run_single_boot
            ;;
        persist)
            local img
            img="$(prepare_writable_img)"
            log "持久化盘: $img"
            run_two_round_assertion "$img" "persist"
            ;;
        live)
            # 不附加 writable.img；两轮断言文件应消失
            run_two_round_assertion "" "live"
            ;;
        *)
            die "内部错误：未知 MODE=$MODE"
            ;;
    esac

    log "完成。"
}

main "$@"
