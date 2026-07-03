#!/usr/bin/env bash
#
# make-usb.sh — 生产端：把定制 ISO 烧成「持久化」可启动 U 盘（Linux）
#
# 用法:
#   sudo ./packaging/iso/make-usb.sh <ISO> <设备如/dev/sdX> [持久化大小GB]
#
#   ISO          定制 ISO 路径（必填）
#   DEV          目标整盘设备，如 /dev/sdb（必填，必须是整盘不是分区）
#   PERSIST_GB   writable 分区大小（GB），默认 0 = 用尽剩余空间
#
#   ./packaging/iso/make-usb.sh --selftest
#                不烧盘、不需 root、不需物理设备。仅对防呆分类逻辑跑一遍
#                断言（用 fake DEV），用于回归验证。
#
# 产出:
#   - dd 写入 ISO（isohybrid GPT+MBR，BIOS+UEFI 都能启动）
#   - 追加分区 2，ext4 标签恰好 "writable"（casper 识别此标签作为 COW 覆盖层）
#   - 终端用户拿到此 U 盘即插即用，默认进 Persistent 模式
#
# 设计参考: .claude/plans/u-iso-u-u-u-starry-giraffe.md 第 4 节
#
# 坑（重要）:
#   - isohybrid ISO 是 GPT+MBR 混合分区表。必须用 sgdisk 追加分区；
#     fdisk 交互式可能误判 GPT 布局而破坏启动区，不要用。
#   - partprobe 必须在 sgdisk 之前（dd 后重读完整分区表）和之后（看到新分区 2）
#     各一次，否则 mkfs.ext4 可能找不到刚建好的分区设备节点。
#   - U 盘容量需 > ISO + >=1G 才有持久化意义，推荐 16G+；脚本会前置 warn。
#   - 本脚本为「生产端」工具，会彻底擦除目标盘，不要拿系统盘当 DEV。

set -Eeuo pipefail

# ===========================================================================
# 纯分类函数（不依赖 root / 不依赖实际设备，可被 --selftest 单测）
# ===========================================================================

# 输入分区或整盘路径，输出整盘路径（尽力而为；无法解析时原样返回）
# /dev/nvme0n1p2 -> /dev/nvme0n1 ; /dev/mmcblk0p2 -> /dev/mmcblk0 ;
# /dev/sda2      -> /dev/sda     ; /dev/sdb        -> /dev/sdb
resolve_whole_disk() {
    local p="$1"
    local base="${p#/dev/}"
    if [[ "$base" =~ ^(nvme[0-9]+n[0-9]+)p[0-9]+$ ]]; then
        echo "/dev/${BASH_REMATCH[1]}"
        return
    fi
    if [[ "$base" =~ ^(mmcblk[0-9]+)p[0-9]+$ ]]; then
        echo "/dev/${BASH_REMATCH[1]}"
        return
    fi
    if [[ "$base" =~ ^([a-z]+)[0-9]+$ ]]; then
        echo "/dev/${BASH_REMATCH[1]}"
        return
    fi
    echo "$p"
}

# 整盘路径是否为「分区」（而非整盘）。返回 0=是分区，1=是整盘。
#   /dev/sdb1 / /dev/nvme0n1p2 / /dev/mmcblk0p1  -> 分区（return 0）
#   /dev/sdb  / /dev/nvme0n1  / /dev/mmcblk0     -> 整盘（return 1）
is_partition() {
    local d="$1"
    local base="${d#/dev/}"
    # nvme/mmcblk 分区: 末尾 p<数字>
    if [[ "$base" =~ ^(nvme[0-9]+n[0-9]+|mmcblk[0-9]+)p[0-9]+$ ]]; then
        return 0
    fi
    # sd/vd/xvd 等带数字后缀 -> 分区
    if [[ "$base" =~ ^[a-z]+[0-9]+$ ]]; then
        return 0
    fi
    return 1
}

# 整盘路径是否在系统盘黑名单中（按设备名规则 + 可选根盘比较）。
#   $1 = 候选整盘 ; $2 = 当前根所在整盘（可空）
#   返回 0=应拒绝（系统盘），1=可接受；理由打到 stdout。
should_reject_system_disk() {
    local d="$1"
    local root_disk="${2:-}"
    # if [[ "$d" == "/dev/sda" ]]; then
    #     echo "/dev/sda（通常是系统主盘）"
    #     return 0
    # fi
    if [[ "$d" =~ ^/dev/nvme[0-9]+n[0-9]+$ ]]; then
        echo "$d（NVMe 盘，通常是系统盘）"
        return 0
    fi
    if [[ "$d" =~ ^/dev/mmcblk[0-9]+$ ]]; then
        echo "$d（eMMC 盘，通常是系统盘）"
        return 0
    fi
    if [[ -n "$root_disk" && "$d" == "$root_disk" ]]; then
        echo "$d（当前根文件系统所在盘）"
        return 0
    fi
    return 1
}

# 由整盘路径推导分区 2 设备名。
#   mmcblk/nvme 整盘分区带 p: ${DEV}p2 ; sd 系列为 ${DEV}2
part2_device() {
    local d="$1"
    if [[ "$d" =~ ^/dev/(nvme[0-9]+n[0-9]+|mmcblk[0-9]+)$ ]]; then
        echo "${d}p2"
    else
        echo "${d}2"
    fi
}

# 向上取整到 GiB（字节 -> GiB），至少返回 1。
ceil_gib() {
    awk -v b="$1" 'BEGIN {
        if (b == "" || b+0 == 0) { print 1; exit }
        g = b / 1073741824.0
        printf("%d\n", (g == int(g)) ? g : int(g)+1)
    }'
}

# ===========================================================================
# --selftest：对纯分类函数跑断言，不烧盘、不需 root、不需设备
# ===========================================================================
run_selftest() {
    local fails=0
    check() {
        # check <desc> <expected> <actual>
        local desc="$1" expected="$2" actual="$3"
        if [[ "$expected" == "$actual" ]]; then
            printf "  ok   | %s -> %s\n" "$desc" "$actual"
        else
            printf "  FAIL | %s : expected '%s' got '%s'\n" "$desc" "$expected" "$actual" >&2
            fails=$((fails+1))
        fi
    }

    echo "== resolve_whole_disk =="
    check "nvme0n1p2" "/dev/nvme0n1" "$(resolve_whole_disk /dev/nvme0n1p2)"
    check "mmcblk0p2"  "/dev/mmcblk0"  "$(resolve_whole_disk /dev/mmcblk0p2)"
    check "sda2"       "/dev/sda"      "$(resolve_whole_disk /dev/sda2)"
    check "sdb(整盘)"  "/dev/sdb"      "$(resolve_whole_disk /dev/sdb)"

    # 注意：set -e 下，返回非零的函数必须放进 || / if 链，否则脚本会退出。
    # 用 if/else 把 0/1 语义码安全取出来交给 check 比较。
    rc_ispart() {
        if is_partition "$1"; then echo 0; else echo 1; fi
    }
    rc_reject() {
        if should_reject_system_disk "$@" >/dev/null; then echo 0; else echo 1; fi
    }

    echo "== is_partition (0=分区,1=整盘) =="
    check "/dev/sdb1"        "0(par)"  "$(rc_ispart /dev/sdb1)"
    check "/dev/nvme0n1p2"   "0(par)"  "$(rc_ispart /dev/nvme0n1p2)"
    check "/dev/mmcblk0p1"   "0(par)"  "$(rc_ispart /dev/mmcblk0p1)"
    check "/dev/sdb"         "1(disk)" "$(rc_ispart /dev/sdb)"
    check "/dev/nvme0n1"     "1(disk)" "$(rc_ispart /dev/nvme0n1)"
    check "/dev/mmcblk0"     "1(disk)" "$(rc_ispart /dev/mmcblk0)"

    echo "== should_reject_system_disk (0=拒绝,1=接受) =="
    check "/dev/sda"                "0(rej)" "$(rc_reject /dev/sda)"
    check "/dev/nvme0n1"            "0(rej)" "$(rc_reject /dev/nvme0n1)"
    check "/dev/mmcblk0"            "0(rej)" "$(rc_reject /dev/mmcblk0)"
    check "/dev/sdb"                "1(ok)"  "$(rc_reject /dev/sdb)"
    check "/dev/sdc"                "1(ok)"  "$(rc_reject /dev/sdc)"
    # 根盘 = /dev/sdb 时，候选 /dev/sdb 应被拒（避免把当前系统盘当目标）
    check "root=/dev/sdb -> /dev/sdb" "0(rej)" "$(rc_reject /dev/sdb /dev/sdb)"
    check "root=/dev/sdb -> /dev/sdc" "1(ok)"  "$(rc_reject /dev/sdc /dev/sdb)"

    echo "== part2_device =="
    check "sdb->p2"    "/dev/sdb2"     "$(part2_device /dev/sdb)"
    check "nvme->p2"   "/dev/nvme0n1p2" "$(part2_device /dev/nvme0n1)"
    check "mmcblk->p2" "/dev/mmcblk0p2" "$(part2_device /dev/mmcblk0)"

    echo "== ceil_gib =="
    check "0B"      "1" "$(ceil_gib 0)"
    check "1GiB"    "1" "$(ceil_gib 1073741824)"
    check "1.5GiB"  "2" "$(ceil_gib 1610612736)"
    check "16GiB"   "16" "$(ceil_gib 17179869184)"

    if [[ "$fails" -eq 0 ]]; then
        echo "SELFTEST PASS (0 failures)"
        return 0
    fi
    echo "SELFTEST FAIL ($fails failures)" >&2
    return 1
}

# --selftest 短路：在任何 root/参数检查之前
if [[ "${1:-}" == "--selftest" ]]; then
    run_selftest
    exit $?
fi

# ===========================================================================
# 主流程
# ===========================================================================

# ---------------------------------------------------------------------------
# 前置：root 权限
# ---------------------------------------------------------------------------
if [[ "${EUID}" -ne 0 ]]; then
    echo "ERROR: 必须以 root 运行（用 sudo）。" >&2
    echo "  sudo $0 $*" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 参数解析
# ---------------------------------------------------------------------------
if [[ $# -lt 2 ]]; then
    cat >&2 <<'EOF'
用法: sudo ./packaging/iso/make-usb.sh <ISO> <设备如/dev/sdX> [持久化大小GB]
  ISO          定制 ISO 路径（必填）
  DEV          目标整盘设备，如 /dev/sdb（必填）
  PERSIST_GB   writable 分区大小 GB，默认 0 = 用尽剩余空间

自测: ./packaging/iso/make-usb.sh --selftest   （不烧盘、不需 root）
EOF
    exit 2
fi

ISO="$1"
DEV="$2"
PERSIST_GB="${3:-0}"

# ---------------------------------------------------------------------------
# 工具依赖自检
# ---------------------------------------------------------------------------
need_cmd() {
    command -v "$1" >/dev/null 2>&1 || {
        echo "ERROR: 缺少命令 '$1'，请先安装。" >&2
        echo "  sudo apt install -y gdisk util-linux e2fsprogs mount" >&2
        exit 1
    }
}
need_cmd dd
need_cmd sgdisk
need_cmd partprobe
need_cmd udevadm
need_cmd mkfs.ext4
need_cmd blkid
need_cmd lsblk
need_cmd findmnt

# ---------------------------------------------------------------------------
# 安全防呆
# ---------------------------------------------------------------------------

# (1) ISO 存在且是文件
if [[ ! -f "$ISO" ]]; then
    echo "ERROR: ISO 文件不存在: $ISO" >&2
    exit 1
fi

# (2) DEV 是块设备
if [[ ! -b "$DEV" ]]; then
    echo "ERROR: '$DEV' 不是块设备（[ -b ] 失败）。" >&2
    echo "  请指定整盘设备，如 /dev/sdb 。" >&2
    exit 1
fi

# 规范化为 /dev/... 形式
DEV="$(readlink -f "$DEV")"

# (3) 拒绝分区：要求整盘
if is_partition "$DEV"; then
    echo "ERROR: '$DEV' 看起来是分区，不是整盘。" >&2
    echo "  请指定整盘设备。例如用 /dev/sdb 而不是 /dev/sdb1。" >&2
    exit 1
fi

# (4) 拒绝系统盘：/dev/sda、/dev/nvme*、/dev/mmcblk0、以及当前根盘
ROOT_PART=""
ROOT_DISK=""
if ROOT_PART="$(findmnt -no SOURCE / 2>/dev/null)"; then
    ROOT_DISK="$(resolve_whole_disk "$ROOT_PART")"
fi
if reason="$(should_reject_system_disk "$DEV" "$ROOT_DISK")"; then
    echo "ERROR: 拒绝操作系统盘: $reason" >&2
    if [[ -n "$ROOT_PART" ]]; then
        echo "  （当前根: $ROOT_PART -> 整盘 $ROOT_DISK）" >&2
    fi
    echo "  烧录会彻底擦除目标盘数据，请改用 U 盘（如 /dev/sdb / /dev/sdc）。" >&2
    exit 1
fi

# (5) 容量 warn（过小提示）
DEV_SIZE_HUMAN="$(lsblk -ndo SIZE "$DEV" 2>/dev/null || echo '?')"
ISO_SIZE_BYTES="$(stat -c %s "$ISO")"
iso_gib="$(ceil_gib "$ISO_SIZE_BYTES")"
echo "INFO: 目标盘容量 ${DEV_SIZE_HUMAN}；ISO 约 ${iso_gib}G。"
if [[ "$DEV_SIZE_HUMAN" != "?" ]]; then
    dev_size_bytes="$(lsblk -bndo SIZE "$DEV" 2>/dev/null || echo 0)"
    dev_gib="$(ceil_gib "$dev_size_bytes")"
    # ISO 占用 + 至少 1G 持久化才合理；低于 16G 给 warn
    if [[ "$dev_gib" -lt 16 ]]; then
        echo "WARN: 目标盘 $DEV 容量约 ${DEV_SIZE_HUMAN}，小于推荐 16G。" >&2
        echo "      至少需要 ISO($iso_gib G) + >=1G 才有持久化意义。" >&2
    fi
fi

# (6) 展示目标盘信息 + 大写 YES 确认
echo "=============================================================="
echo " 即将擦除以下设备并烧录 ISO + 追加 writable 持久化分区:"
echo "--------------------------------------------------------------"
lsblk -ndo NAME,SIZE,MODEL,VENDOR,TRAN "$DEV" 2>/dev/null || \
    lsblk -ndo NAME,SIZE "$DEV"
echo "--------------------------------------------------------------"
echo " ISO : $ISO"
echo " DEV : $DEV  (整盘将被完全擦除)"
if [[ "$PERSIST_GB" == "0" ]]; then
    echo " 持久: 用尽剩余空间"
else
    echo " 持久: ${PERSIST_GB} GB"
fi
echo "=============================================================="
printf " 输入大写 YES 确认继续: "
read -r CONFIRM
if [[ "$CONFIRM" != "YES" ]]; then
    echo "未确认（需输入大写 YES），退出。未做任何修改。" >&2
    exit 1
fi

# ---------------------------------------------------------------------------
# 1. dd 写入 ISO
# ---------------------------------------------------------------------------
echo "==> [1/5] dd 写入 ISO -> $DEV ..."
dd if="$ISO" of="$DEV" bs=8M conv=fsync status=progress
sync

# ---------------------------------------------------------------------------
# 2. 重读分区表（sgdisk 之前必须让内核看到 ISO 自带的 GPT+MBR）
#    坑：partprobe 必须在 sgdisk 之前，让内核重读完整分区表。
# ---------------------------------------------------------------------------
echo "==> [2/5] 重读分区表 ..."
partprobe "$DEV" || partx -u "$DEV" || true
udevadm settle
sleep 2

# ---------------------------------------------------------------------------
# 3. 追加 writable 分区（分区 2）
#    isohybrid 是 GPT+MBR，用 sgdisk 追加安全；不要用 fdisk（会误判 GPT）。
# ---------------------------------------------------------------------------
echo "==> [3/5] sgdisk 追加 writable 分区 ..."
if [[ "$PERSIST_GB" == "0" ]]; then
    # 0:0 = 起点默认、终点用尽剩余空间
    sgdisk --new=2:0:0 --typecode=2:8300 --change-name=2:"writable" "$DEV"
else
    sgdisk --new="2:0:+${PERSIST_GB}G" --typecode=2:8300 --change-name=2:"writable" "$DEV"
fi
# 坑：sgdisk 之后必须再 partprobe，让内核看到分区 2 设备节点
partprobe "$DEV" || partx -u "$DEV" || true
udevadm settle
sleep 2

# ---------------------------------------------------------------------------
# 4. 计算分区 2 设备名 + mkfs.ext4（标签正好 writable，保留块 0%）
# ---------------------------------------------------------------------------
PART2="$(part2_device "$DEV")"

if [[ ! -b "$PART2" ]]; then
    echo "ERROR: 分区设备 '$PART2' 不存在（partprobe 后仍未见）。" >&2
    echo "  可手动检查: lsblk $DEV ; partprobe $DEV ; ls /dev/" >&2
    exit 1
fi

echo "==> [4/5] mkfs.ext4 -L writable $PART2 ..."
mkfs.ext4 -F -L writable -m 0 "$PART2"
sync

# ---------------------------------------------------------------------------
# 5. 验证与提示
# ---------------------------------------------------------------------------
echo "==> [5/5] 验证 ..."
echo "--- lsblk ---"
lsblk -o NAME,SIZE,FSTYPE,LABEL "$DEV"
echo "--- blkid $PART2 ---"
blkid "$PART2"

# 校验标签确实为 writable
LABEL_CHECK="$(blkid -s LABEL -o value "$PART2" 2>/dev/null || true)"
if [[ "$LABEL_CHECK" != "writable" ]]; then
    echo "ERROR: 分区 2 标签应为 'writable'，实际为 '${LABEL_CHECK}'。" >&2
    echo "  casper 依标签 'writable' 挂载持久化覆盖层，标签错误将导致不持久化。" >&2
    exit 1
fi

echo "=============================================================="
echo " 完成。此 U 盘即插即用，默认进 Persistent 模式。"
echo "  - BIOS + UEFI 均可启动（isohybrid GPT+MBR）"
echo "  - 全部改动写入 writable 分区，关机不丢"
echo "  - 把 U 盘交给终端用户，插上、开机、即用（零命令）"
echo "=============================================================="
