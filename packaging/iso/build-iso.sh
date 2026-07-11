#!/usr/bin/env bash
#
# build-iso.sh — LinkerHand Edu 持久化 Live USB ISO 打包流水线（替代 Cubic）
#
# 把官方 ubuntu-24.04.4-desktop-amd64.iso → 定制持久化 linkerhand-edu-<ver>-amd64.iso
# 一条命令可重建、可复现。详见 packaging/iso/docs/build-iso-design.md。
#
# 用法：sudo ./build-iso.sh
#   环境变量覆盖：
#     ORIG_ISO   源 ISO 路径（默认 ~/下载/ubuntu-24.04.4-desktop-amd64.iso）
#     BUILD_DIR  中间件目录（默认 /tmp，需 >=25G 可写）
#     VERSION    版本号（默认 当天日期 YYYY.MM.DD）
#
# 退出码：0 成功；1 校验/断言失败；2 工具缺失。

set -Eeuo pipefail

# ---------------------------------------------------------------------------
# 全局变量（在 cleanup() 中使用，必须先声明）
# ---------------------------------------------------------------------------
ROOTFS=""
ISODIR=""
CUSTOMIZE_RAN=0

# ---------------------------------------------------------------------------
# cleanup() — trap EXIT 时卸载 rootfs 下的伪文件系统并删临时目录
# ---------------------------------------------------------------------------
cleanup() {
    local rc=$?
    # 反向 umount：先 dev/pts 再 dev/proc/sys/run，避免 busy
    if [[ -n "${ROOTFS:-}" && -d "${ROOTFS:-}" ]]; then
        local sub
        for sub in dev/pts dev proc sys run; do
            local mnt="${ROOTFS}/${sub}"
            if mountpoint -q "$mnt" 2>/dev/null; then
                umount -f "$mnt" 2>/dev/null || umount -l "$mnt" 2>/dev/null || true
            fi
        done
    fi
    # 删临时目录（ISODIR + ROOTFS + repro.sh 都在 WORK 下）
    if [[ -n "${WORK:-}" && -d "${WORK:-}" ]]; then
        rm -rf -- "$WORK" 2>/dev/null || true
    fi
    exit "$rc"
}
trap cleanup EXIT

# ---------------------------------------------------------------------------
# die() — 打印错误到 stderr 并以非零码退出
# ---------------------------------------------------------------------------
die() {
    echo "ERROR: $*" >&2
    exit 1
}

# ---------------------------------------------------------------------------
# require_cmd() — 校验命令存在，缺失则列出并退出码 2
# ---------------------------------------------------------------------------
require_cmd() {
    local missing=()
    while [[ $# -gt 0 ]]; do
        command -v "$1" >/dev/null 2>&1 || missing+=("$1")
        shift
    done
    if [[ ${#missing[@]} -gt 0 ]]; then
        echo "ERROR: 缺少必需工具: ${missing[*]}" >&2
        echo "请安装: sudo apt install -y xorriso squashfs-tools gdisk rsync mtools" >&2
        exit 2
    fi
}

# ===========================================================================
# 步骤 1：校验环境
# ===========================================================================
validate_env() {
    [[ "$EUID" -eq 0 ]] || die "必须以 root 运行（需要 mount/chroot）。请用 sudo。"

    [[ -f "$ORIG_ISO" ]] || die "源 ISO 不存在: $ORIG_ISO"

    require_cmd xorriso unsquashfs mksquashfs rsync sgdisk file find awk

    # BUILD_DIR 可用空间 >= 25G
    mkdir -p "$BUILD_DIR"
    local avail_kb
    avail_kb="$(df -P "$BUILD_DIR" | awk 'NR==2{print $4}')"
    local avail_gb=$(( avail_kb / 1024 / 1024 ))
    if [[ "$avail_gb" -lt 25 ]]; then
        die "BUILD_DIR ($BUILD_DIR) 可用空间仅 ${avail_gb}G，需要 >=25G。可用 BUILD_DIR=/path 覆盖。"
    fi
    echo "[1/11] 环境校验通过：BUILD_DIR=$BUILD_DIR (${avail_gb}G 可用)，ORIG_ISO=$ORIG_ISO"
}

# ===========================================================================
# 步骤 2：解包原 ISO
# ===========================================================================
extract_iso() {
    echo "[2/11] 解包原 ISO → $ISODIR"
    xorriso -osirrox on -indev "$ORIG_ISO" \
        -extract / "$ISODIR" >/dev/null 2>&1 \
        || die "xorriso 解包失败"

    # 校验关键文件
    local need=(
        casper/minimal.squashfs
        casper/vmlinuz
        casper/initrd
        boot/grub/grub.cfg
    )
    local f
    for f in "${need[@]}"; do
        [[ -e "$ISODIR/$f" ]] || die "ISO 缺少必需文件: $f"
    done
    [[ -d "$ISODIR/EFI/boot" ]] || die "ISO 缺少 EFI/boot/ 目录"
}

# ===========================================================================
# 步骤 3：unsquashfs 主 rootfs
# ===========================================================================
unsquash_rootfs() {
    echo "[3/11] unsquashfs → $ROOTFS"
    rm -rf -- "$ROOTFS"
    unsquashfs -d "$ROOTFS" "$ISODIR/casper/minimal.squashfs" >/dev/null 2>&1 \
        || die "unsquashfs 失败"
    [[ -d "$ROOTFS" ]] || die "unsquashfs 后 rootfs 不存在"
}

# ===========================================================================
# 步骤 4：注入项目（rsync 排除冗余 + 真实 key 永不进）
# ===========================================================================
inject_payload() {
    echo "[4/11] 注入项目 → $ROOTFS/_payload/ws/"

    # ---- MediaPipe hand_landmarker 模型捆绑 ----
    # 两个运行时节点都需要此模型，但路径不同：
    #   RPS 节点 (gesture_detector.py)       : ~/.local/share/mediapipe/tasks/hand_landmarker.task
    #   Tracking 节点 (hand_tracking_node.py) : {mp.__path__[0]}/tasks/hand_landmarker.task
    # 宿主机无网络时需离线捆绑；有网络时 curl 下载。
    local MODEL_SRC="${HOME}/.local/share/mediapipe/tasks/hand_landmarker.task"
    if [[ ! -f "$MODEL_SRC" ]]; then
        echo "      本地未找到 MediaPipe 模型，下载中..."
        mkdir -p "$(dirname "$MODEL_SRC")"
        curl -L -o "$MODEL_SRC" \
            "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task" \
            || die "MediaPipe 模型下载失败"
    else
        echo "      本地找到 MediaPipe 模型: $MODEL_SRC"
    fi

    # 目标 1：RPS 节点（用户级 ~/.local/share）
    local dst1="$ROOTFS/root/.local/share/mediapipe/tasks/hand_landmarker.task"
    mkdir -p "$(dirname "$dst1")"
    cp "$MODEL_SRC" "$dst1" || die "复制模型到 $dst1 失败"

    # 目标 2：Tracking 节点（mediapipe pip 包目录；chroot-customize.sh 会 pip install mediapipe）
    local dst2="$ROOTFS/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task"
    mkdir -p "$(dirname "$dst2")"
    cp "$MODEL_SRC" "$dst2" || die "复制模型到 $dst2 失败"

    echo "      MediaPipe 模型: hand_landmarker.task → bundled into ISO"
    # ---- /MediaPipe 模型捆绑 ----

    mkdir -p "$ROOTFS/_payload/ws"

    # rsync 工作空间：排除构建产物/缓存/git/明文 key
    rsync -a \
        --exclude='build/' \
        --exclude='log/' \
        --exclude='.pytest_cache/' \
        --exclude='install/' \
        --exclude='__pycache__/' \
        --exclude='.git/' \
        --exclude='*.pyc' \
        --exclude='*.pyo' \
        --exclude='llm_settings.json' \
        --exclude='.claude/' \
        "$WS/" "$ROOTFS/_payload/ws/" \
        || die "rsync 工作空间失败"

    # 拷 chroot-customize.sh + llm_settings.template.json 进 rootfs（若存在）
    if [[ -f "$THIS_DIR/chroot-customize.sh" ]]; then
        cp "$THIS_DIR/chroot-customize.sh" "$ROOTFS/usr/sbin/chroot-customize"
        chmod 755 "$ROOTFS/usr/sbin/chroot-customize"
        CUSTOMIZE_AVAILABLE=1
    else
        echo "WARN: packaging/iso/chroot-customize.sh 缺席，跳过 chroot 定制步骤（仅流水线骨架）。" >&2
        CUSTOMIZE_AVAILABLE=0
    fi
    if [[ -f "$THIS_DIR/llm_settings.template.json" ]]; then
        cp "$THIS_DIR/llm_settings.template.json" "$ROOTFS/_payload/llm_settings.template.json"
    fi

    # ---- 离线安装包搬运（VSCode .deb + Firefox tarball + Zed tarball + Sidex .deb）----
    local CACHE_DIR="$THIS_DIR/cache/customise"

    local -a DEBS=()
    local -a TARS=()

    # 通配符收集 .deb 和 tarball
    while IFS= read -r f; do [[ -n "$f" ]] && DEBS+=("$f"); done < <(ls "$CACHE_DIR"/*.deb 2>/dev/null || true)
    while IFS= read -r f; do [[ -n "$f" ]] && TARS+=("$f"); done < <(ls "$CACHE_DIR"/*.tar.xz "$CACHE_DIR"/*.tar.gz 2>/dev/null || true)

    mkdir -p "$ROOTFS/_payload"

    for deb in "${DEBS[@]}"; do
        local name
        name="$(basename "$deb")"
        local dest="_payload/$(echo "$name" | sed 's/[^A-Za-z0-9._-]/_/g')"
        cp "$deb" "$ROOTFS/$dest"
        echo "      .deb: $name → $dest"
    done

    for tar in "${TARS[@]}"; do
        local name
        name="$(basename "$tar")"
        local dest="_payload/$(echo "$name" | sed 's/[^A-Za-z0-9._-]/_/g')"
        cp "$tar" "$ROOTFS/$dest"
        echo "      tarball: $name → $dest"
    done

    if [[ ${#DEBS[@]} -eq 0 && ${#TARS[@]} -eq 0 ]]; then
        echo "      WARN: $CACHE_DIR 下未找到任何 .deb 或 tarball，跳过离线安装包搬运。" >&2
    fi
}

# ===========================================================================
# 步骤 5：chroot 定制（仅当 chroot-customize.sh 存在）
# ===========================================================================
chroot_mount() {
    # bind-mount 伪文件系统
    mkdir -p "$ROOTFS/dev/pts" "$ROOTFS/proc" "$ROOTFS/sys" "$ROOTFS/run"
    mount --bind /dev     "$ROOTFS/dev"     || die "mount /dev 失败"
    mount --bind /dev/pts "$ROOTFS/dev/pts" || die "mount /dev/pts 失败"
    mount -t proc  proc  "$ROOTFS/proc"     || die "mount /proc 失败"
    mount -t sysfs sysfs "$ROOTFS/sys"      || die "mount /sys 失败"
    mount -t tmpfs tmpfs "$ROOTFS/run"      || die "mount /run 失败"
    # DNS：chroot 共享宿主机网络命名空间，resolv.conf 解决解析
    # 注意：Ubuntu 24.04 rootfs 的 /etc/resolv.conf 是指向
    # ../run/systemd/resolve/stub-resolv.conf 的符号链接；上面挂的是全新 tmpfs（目标
    # 不存在），该 symlink 悬空。裸 cp 拒绝穿过悬空 symlink 写文件 → 非零退出 →
    # set -e 在 [5/11] 静默中止。--remove-destination 先 unlink 该 symlink 再写真实
    # 常规文件；目标不存在或已是常规文件时为 no-op-safe。
    if [[ -f /etc/resolv.conf ]]; then
        cp --remove-destination /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
    fi
}

chroot_umount() {
    # 反向 umount（dev/pts 先，dev 后）
    umount -f "$ROOTFS/dev/pts"  2>/dev/null || true
    umount -f "$ROOTFS/dev"      2>/dev/null || true
    umount -f "$ROOTFS/proc"     2>/dev/null || true
    umount -f "$ROOTFS/sys"      2>/dev/null || true
    umount -f "$ROOTFS/run"      2>/dev/null || true
}

run_chroot_customize() {
    if [[ "$CUSTOMIZE_AVAILABLE" -ne 1 ]]; then
        echo "[5/11] 跳过 chroot 定制（chroot-customize.sh 缺席）。"
        return
    fi
    echo "[5/11] chroot 定制 → /usr/sbin/chroot-customize"
    chroot_mount
    CUSTOMIZE_RAN=1

    # 运行定制脚本
    chroot "$ROOTFS" /usr/sbin/chroot-customize \
        || die "chroot-customize 执行失败"

    # 清理 apt 缓存（减小 squashfs 体积）
    chroot "$ROOTFS" apt-get clean 2>/dev/null || true
    rm -rf "$ROOTFS/var/lib/apt/lists/"*

    # 卸载（在 cleanup 兜底前显式卸一次，便于错误诊断）
    chroot_umount
    CUSTOMIZE_RAN=0
}

# ===========================================================================
# 步骤 6：重打包 squashfs（xz，保留 xattrs，排除缓存）
# ===========================================================================
repack_squashfs() {
    echo "[6/11] mksquashfs → minimal.squashfs"
    rm -f "$ISODIR/casper/minimal.squashfs"
    mksquashfs "$ROOTFS" "$ISODIR/casper/minimal.squashfs" \
        -comp xz -b 1048576 -Xdict-size 100% \
        -noappend \
        -wildcards \
        -e 'var/cache/apt/archives/*.deb' 'tmp/*' 'root/.cache/*' \
        >/dev/null 2>&1 \
        || die "mksquashfs 失败"
    # 注意：不加 -no-xattrs（casper 依赖 xattrs）
}

# ===========================================================================
# 步骤 7：更新元数据（filesystem.size / manifest / .disk/info）
# ===========================================================================
update_metadata() {
    echo "[7/11] 更新元数据"
    local sqfs_bytes
    sqfs_bytes="$(stat -c '%s' "$ISODIR/casper/minimal.squashfs")"

    # filesystem.size / minimal.size = 新 squashfs 字节数
    echo "$sqfs_bytes" > "$ISODIR/casper/filesystem.size"
    echo "$sqfs_bytes" > "$ISODIR/casper/minimal.size"

    # manifest：dpkg -l 列出已装包。chroot 跑过则用 rootfs（已卸载，重挂只读态）；
    # 否则从 rootfs 直接跑 dpkg（rootfs 里有 dpkg 数据库）。
    local manifest_tmp
    manifest_tmp="$(mktemp)"
    if chroot "$ROOTFS" dpkg -l 2>/dev/null | awk '/^ii/{print $2"\tinstall"}' > "$manifest_tmp" \
        && [[ -s "$manifest_tmp" ]]; then
        cp "$manifest_tmp" "$ISODIR/casper/filesystem.manifest"
        cp "$manifest_tmp" "$ISODIR/casper/minimal.manifest"
    else
        echo "WARN: dpkg manifest 生成失败（rootfs 可能已卸载伪 fs），跳过 manifest。" >&2
        rm -f "$ISODIR/casper/filesystem.manifest" "$ISODIR/casper/minimal.manifest" 2>/dev/null || true
    fi
    rm -f "$manifest_tmp"

    # .disk/info
    mkdir -p "$ISODIR/.disk"
    echo "LinkerHand Edu ${VERSION} - $(date -R)" > "$ISODIR/.disk/info"
}

# ===========================================================================
# ★ 步骤 8：双模式 GRUB 菜单（核心 — 重写整个菜单块，不用 sed）
# ===========================================================================
# generate_grub_menu() — 生成统一的双模式菜单块（4 条 menuentry）。参数为 1 时，
# 给每条 linux 行追加 iso-scan/filename=${iso_path}（loopback.cfg 用）。
# 输出到 stdout，调用方重定向到目标文件。
#
# 菜单结构（严格按 build-iso-design.md 规范）：
#   1. Persistent (default)         : persistent          --- quiet splash
#   2. Live (clean, no save)        :                     --- quiet splash
#   3. Persistent (safe graphics)   : persistent nomodeset --- quiet splash
#   4. Live (safe graphics)         :      nomodeset       --- quiet splash
generate_grub_menu() {
    local with_iso_scan="${1:-0}"   # 1 = loopback.cfg 模式
    local iso_scan=""
    if [[ "$with_iso_scan" == "1" ]]; then
        # loopback.cfg 里 GRUB 变量 ${iso_path} 由外层 grub.cfg 设定
        iso_scan=" iso-scan/filename=\${iso_path}"
    fi

    cat <<EOF
set default=0
set timeout=10

menuentry "LinkerHand Edu - Persistent (default)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz root=live:/cdrom${iso_scan} persistent --- quiet splash
    initrd /casper/initrd
}
menuentry "LinkerHand Edu - Live (clean, no save)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz root=live:/cdrom${iso_scan} --- quiet splash
    initrd /casper/initrd
}
menuentry "LinkerHand Edu - Persistent (safe graphics)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz root=live:/cdrom${iso_scan} persistent nomodeset --- quiet splash
    initrd /casper/initrd
}
menuentry "LinkerHand Edu - Live (safe graphics)" {
    set gfxpayload=keep
    linux  /casper/vmlinuz root=live:/cdrom${iso_scan} nomodeset --- quiet splash
    initrd /casper/initrd
}
EOF
}

# assert_grub_file — 对单个 grub 配置文件做结构断言。
#   - 恰好 4 条 menuentry
#   - 恰好 2 处 linux 行含 persistent（两条 Persistent 项）
#   - 恰好 2 处 linux 行含 nomodeset（两条 safe graphics 项）
#   - Live (clean) 行存在：vmlinuz 后直接 --- （persistent 与 nomodeset 都不命中）
assert_grub_file() {
    local f="$1" label="$2" expect_iso_scan="${3:-0}"

    [[ -f "$f" ]] || die "$label 断言失败：文件不存在 $f"

    local n_menu n_persist n_nomodeset n_iso_scan n_root
    n_menu=$(grep -c '^menuentry ' "$f" || true)
    n_persist=$(grep -cE '^ *linux.*\bpersistent\b' "$f" || true)
    n_nomodeset=$(grep -cE '^ *linux.*\bnomodeset\b' "$f" || true)
    n_iso_scan=$(grep -c 'iso-scan/filename' "$f" || true)
    n_root=$(grep -cE '\broot=live:/cdrom\b' "$f" || true)

    [[ "$n_menu" -eq 4 ]] \
        || die "$label 断言失败：menuentry 数期望 4，实际 $n_menu"
    [[ "$n_persist" -eq 2 ]] \
        || die "$label 断言失败：persistent linux 行期望 2，实际 $n_persist（应有两条 Persistent 项）"
    [[ "$n_nomodeset" -eq 2 ]] \
        || die "$label 断言失败：nomodeset linux 行期望 2，实际 $n_nomodeset"

    # Live (clean) 项：linux 行 vmlinuz 后直接跟 --- quiet splash（不含 persistent/nomodeset）
    grep -qE '^ *linux.*/casper/vmlinuz( +[^ ]*)* +--- quiet splash *$' "$f" \
        || die "$label 断言失败：缺 Live (clean) 项（应含 'vmlinuz ... --- quiet splash' 无 persistent/nomodeset）"

    if [[ "$expect_iso_scan" == "1" ]]; then
        [[ "$n_iso_scan" -eq 4 ]] \
            || die "$label 断言失败：iso-scan/filename 期望 4（每条 linux 行一次），实际 $n_iso_scan"
    else
        [[ "$n_iso_scan" -eq 0 ]] \
            || die "$label 断言失败：grub.cfg 不应含 iso-scan/filename（实际 $n_iso_scan）"
    fi
    [[ "$n_root" -eq 4 ]] \
        || die "$label 断言失败：root=live:/cdrom 期望 4（每条 linux 行一次），实际 $n_root"
}

rewrite_grub() {
    echo "[8/11] 重写双模式 GRUB 菜单"

    # grub.cfg：整体重写为统一菜单（原文件的 loadfont/menu_color_* 等非菜单 set 项
    # 非必需，GRUB 自带默认；为保证双模式菜单可靠落地，采用整体重写）。
    generate_grub_menu 0 > "$ISODIR/boot/grub/grub.cfg"

    # loopback.cfg：菜单结构一致，每条 linux 加 iso-scan/filename=${iso_path}
    generate_grub_menu 1 > "$ISODIR/boot/grub/loopback.cfg"

    # ★ 断言（grub.cfg 不含 iso-scan；loopback.cfg 每条 linux 行一次）
    assert_grub_file "$ISODIR/boot/grub/grub.cfg"     "grub.cfg"     0
    assert_grub_file "$ISODIR/boot/grub/loopback.cfg" "loopback.cfg" 1
}

# ===========================================================================
# 步骤 9：重算 md5sum.txt
# ===========================================================================
recompute_md5() {
    echo "[9/11] 重算 md5sum.txt"
    (
        cd "$ISODIR"
        find . -type f ! -path './md5sum.txt' -printf '%P\0' \
            | sort -z \
            | xargs -0 md5sum > md5sum.txt
    ) || die "md5sum 重算失败"
}

# ===========================================================================
# ★ 步骤 10：xorriso 生成 isohybrid ISO（从原 ISO 取确切 mkisofs 参数）
# ===========================================================================
# extract_esp — 从原 ISO 提取 UEFI ESP 分区（append-partition 原始字节）
# 作为独立文件保存，供 patch_repro_sh 在 -e 参数中直接引用。
#
# 背景：report_el_torito as_mkisofs 输出的 --interval:local_fs:OFFSETd-SIZEd::FILE
# 语法中的 BYTE OFFSET 是针对原 ISO 的绝对偏移。若 FILE 替换为新构建的 ISO，
# 同一偏移量在新 ISO 的不同布局下指向 ISO9660 文件系统数据而非 ESP，
# 导致 UEFI 启动镜像损坏（GRUB 菜单可见但无法加载内核）。
#
# 修复：将 ESP 原始字节提取为独立文件，在 -e 参数中直接引用该文件路径。
extract_esp() {
    local src_iso="$1" dst_file="$2"

    # 通过 report_el_torito plain 探测 UEFI 启动镜像的偏移和大小
    local eltorito_output
    eltorito_output="$(xorriso -indev "$src_iso" -report_el_torito plain 2>/dev/null)" || {
        echo "WARN: report_el_torito 失败，无法提取 ESP。" >&2
        return 1
    }

    # 解析 UEFI 启动镜像行：提取偏移（字节）和大小（扇区）
    # 格式: El Torito boot img : N UEFI ... SECTORS OFFSET
    local uefi_line
    uefi_line="$(echo "$eltorito_output" | grep 'UEFI' | head -1)" || true
    if [[ -z "$uefi_line" ]]; then
        echo "WARN: 原 ISO 中未找到 UEFI El Torito 启动镜像。" >&2
        return 1
    fi

    # 从行中提取扇区数和 LBA 偏移（最后两列）
    local sectors lba
    sectors="$(echo "$uefi_line" | awk '{print $(NF-1)}')"
    lba="$(echo "$uefi_line" | awk '{print $NF}')"

    if [[ -z "$sectors" || -z "$lba" || "$sectors" -eq 0 ]]; then
        echo "WARN: 无法解析 UEFI 启动镜像参数: $uefi_line" >&2
        return 1
    fi

    local offset_bytes=$(( lba * 512 ))
    local size_bytes=$(( sectors * 512 ))

    echo "[10a] 从原 ISO 提取 UEFI ESP: LBA=$lba, 偏移=${offset_bytes}, 大小=${size_bytes} 字节"
    dd if="$src_iso" of="$dst_file" bs=1 skip="$offset_bytes" count="$size_bytes" 2>/dev/null \
        || { echo "WARN: dd 提取 ESP 失败。" >&2; return 1; }

    local extracted_size
    extracted_size="$(stat -c '%s' "$dst_file" 2>/dev/null || echo 0)"
    if [[ "$extracted_size" -ne "$size_bytes" ]]; then
        echo "WARN: ESP 提取大小不匹配 (期望 ${size_bytes}, 实际 ${extracted_size})。" >&2
        return 1
    fi

    echo "[10a] ESP 提取完成: $dst_file (${extracted_size} 字节)"
    return 0
}

build_iso_image() {
    echo "[10/11] xorriso 生成 isohybrid ISO"

    mkdir -p "$(dirname "$OUT")"

    # 10a. 从原 ISO 提取 UEFI ESP 为独立文件（修复 --interval local_fs 指向错误 ISO 的 bug）
    local efi_img="$BUILD_DIR/uefi-esp.img"
    if ! extract_esp "$ORIG_ISO" "$efi_img"; then
        echo "WARN: ESP 提取失败，回退到手动 xorriso -as mkisofs。" >&2
        build_iso_image_fallback ""
        return
    fi

    # 10b. 从原 ISO 探测 El Torito 启动结构 → repro.sh
    local repro="$BUILD_DIR/repro.sh"
    if ! xorriso -indev "$ORIG_ISO" -report_el_torito as_mkisofs > "$repro" 2>/dev/null; then
        echo "WARN: report_el_torito 失败，回退到手动 xorriso -as mkisofs。" >&2
        build_iso_image_fallback "$efi_img"
        return
    fi

    # 10c. 在 repro.sh 基础上改：源目录 → ISODIR，-o → OUT，-V → 新卷标，
    #      -e 的 --interval:local_fs: 引用替换为提取的 ESP 文件路径。
    local patched="$BUILD_DIR/repro.patched.sh"
    patch_repro_sh "$repro" "$patched" "$efi_img"

    # 10d. 执行 patched repro.sh；若失败退回兜底方案。
    if ! bash "$patched"; then
        echo "WARN: patched repro.sh 执行失败，回退到手动 xorriso -as mkisofs。" >&2
        build_iso_image_fallback "$efi_img"
    fi
}

# patch_repro_sh — 把 report_el_torito as_mkisofs 输出改造成可执行的、
# 指向 $ISODIR → $OUT 的复现脚本。
#
# xorriso -report_el_torito as_mkisofs 的输出是一行（或几行）以
# `xorriso -as mkisofs` 开头的完整命令，包含从原 ISO 探测出的全部启动结构参数
# （isohybrid-mbr / isohybrid-gpt-basdat / eltorito-boot / -e efi.img 等），
# 末尾带 `-V '<原卷标>'` 与（可能带）`-o <原输出>` 与原源目录。
#
# 我们逐 token 改造：
#   - `-V 'xxx'` / `-V "xxx"` / `-V xxx`  → `-V "LinkerHand Edu <VERSION>"`
#   - `-o <path>`                          → `-o "<OUT>"`
#   - `-e '--interval:local_fs:...::FILE'` → `-e "$efi_img"` （UEFI 修复：避免
#     --interval 的 BYTE OFFSET 指向新 ISO 的错误位置）
#   - 末尾的原源目录路径（不以 - 开头的最后参数）→ "<ISODIR>"
# 启动结构参数原样保留（这是从原 ISO 探测出的真实值，不凭记忆）。
patch_repro_sh() {
    local src="$1" dst="$2" efi_img="$3"

    # 把整个 repro.sh 内容拼成单行（xorriso 输出本身是单行，但稳健处理多行/续行）
    local raw
    raw="$(tr '\n' ' ' < "$src" | tr -s ' ')"

    # 1) 去掉可能的前导 `xorriso -as mkisofs`（后面统一由我们补）
    raw="${raw#xorriso -as mkisofs }"
    raw="${raw#xorriso }"

    # 2) 替换 -V '<label>' / -V "<label>" / -V <label>
    #    （顺序：先引号形式，再裸 token 形式，避免误伤）
    raw="$(printf '%s' "$raw" | sed -E \
        -e "s/-V '[^']*'/-V \"LinkerHand Edu ${VERSION}\"/g" \
        -e 's/-V "([^"]*)"/-V "LinkerHand Edu '"${VERSION}"'"/g' \
        -e "s/-V [^'\" ]+/ -V \"LinkerHand Edu ${VERSION}\" /g")"

    # 3) ★ 修复 UEFI：将 -e '--interval:local_fs:OFFSETd-SIZEd::FILE' 替换为 -e "$efi_img"
    #    --interval:local_fs: 中的 BYTE OFFSET 是针对原 ISO 的绝对字节偏移。
    #    若 FILE 被替换为新构建的 ISO 路径，同一偏移在新 ISO 的不同布局下
    #    指向 ISO9660 文件系统数据而非 ESP → UEFI 启动镜像损坏。
    #    修复：直接用提取的 ESP 文件路径 ($3) 作为 -e 的参数。
    if [[ -n "$efi_img" ]]; then
        raw="$(printf '%s' "$raw" | sed -E \
            -e "s|-e '--interval:local_fs:[0-9]+d-[0-9]+d::[^: ]+'|-e '${efi_img}'|g" \
            -e 's|-e "--interval:local_fs:[0-9]+d-[0-9]+d::[^: ]+"|-e "'"${efi_img}"'"|g')"
    fi

    # 4) 替换 -o <path>（裸 token 形式；as_mkisofs 输出通常带 -o）
    if printf '%s' "$raw" | grep -qE -- '-o +[^ ]+ '; then
        raw="$(printf '%s' "$raw" | sed -E "s#-o +[^ ]+#-o \"${OUT}\"#g")"
    fi

    # 5) 末尾原源目录：去掉（若存在）再统一追加 "$ISODIR"。
    #    as_mkisofs 输出的最后一个位置参数（若存在）是原源目录的绝对路径（含 /）。
    #    仅剥离「含 / 的路径形态位置参数」，绝不剥离以 - 开头的 flag，也绝不剥离
    #    flag 的裸值（如 -boot-load-size 10160 的 10160、十六进制 UUID 等不含 / 的值）。
    #    旧版用 `s# +[^ -][^ ]*$##` 会误删任意不以 - 开头的末尾 token（如裸数字 10160），
    #    仅靠末尾恰好有个空格才侥幸不触发——一旦末尾无空格即破坏 -boot-load-size 值，
    #    生成「能构建但无法启动」的 ISO。改为只在末尾 token 含 /（路径形态）时剥离。
    raw="$(printf '%s' "$raw" | sed -E 's# +[^ ][^ ]*/[^ ]*$##')"
    # 收尾规整：去除可能残留的末尾空格
    raw="${raw% }"

    # 6) 若 4) 没命中 -o（as_mkisofs 不输出 -o 的情况），这里补上
    if ! printf '%s' "$raw" | grep -qE -- '-o +'; then
        raw="${raw} -o \"${OUT}\""
    fi

    # 7) 组装最终脚本：补回 xorriso -as mkisofs 前缀 + 源目录
    local final_cmd="xorriso -as mkisofs ${raw} \"${ISODIR}\""
    {
        echo '#!/usr/bin/env bash'
        echo 'set -e'
        echo "# 由 build-iso.sh 从原 ISO 的 report_el_torito as_mkisofs 自动生成。"
        echo "# 启动结构参数（isohybrid/eltorito/efi）原样保留自原 ISO 探测。"
        echo "exec ${final_cmd}"
    } > "$dst"

    # 诊断：打印最终 mkisofs 命令，便于人工核对启动 token 是否完好。
    echo "---- 生成的 xorriso mkisofs 命令 ----"
    echo "${final_cmd}"
    echo "-------------------------------------"
    chmod +x "$dst"
}

build_iso_image_fallback() {
    # 兜底：用 xorriso -as mkisofs 手动补关键启动参数。
    # 24.04 desktop ISO 典型结构：isohybrid-gpt-basdat + MBR + EFI/boot/bootx64.efi。
    # 注意：这是兜底方案，优先用 report_el_torito 探测的真实参数。
    # $1 = 已提取的 UEFI ESP 文件路径（若存在）
    local efi_img="${1:-}"
    echo "WARN: 使用兜底 xorriso 参数（可能不如 report_el_torito 精确）。" >&2

    [[ -n "$efi_img" ]] || {
        [[ -f "$ISODIR/boot/grub/efi.img" ]] && efi_img="$ISODIR/boot/grub/efi.img"
        [[ -f "$ISODIR/EFI/boot/efi.img" ]] && efi_img="$ISODIR/EFI/boot/efi.img"
    }

    local efi_args=()
    if [[ -n "$efi_img" ]]; then
        efi_args+=(-eltorito-alt-boot -e "$efi_img" -no-emul-boot \
                   -isohybrid-gpt-basdat)
    fi

    xorriso -as mkisofs \
        -r -V "LinkerHand Edu ${VERSION}" \
        -o "$OUT" \
        -J -joliet-long \
        -b boot/grub/i386-pc/eltorito.img \
        -no-emul-boot -boot-load-size 4 -boot-info-table \
        "${efi_args[@]}" \
        "$ISODIR" \
        || die "兜底 xorriso 生成 ISO 失败"
}

# ===========================================================================
# 步骤 11：产物校验
# ===========================================================================
verify_product() {
    echo "[11/11] 产物校验"
    [[ -f "$OUT" ]] || die "产物 ISO 不存在: $OUT"

    local ftype
    ftype="$(file "$OUT")"
    # 必须是 ISO 9660（防止拿任意镜像冒充）。
    echo "$ftype" | grep -q 'ISO 9660' \
        || die "产物不是 ISO 9660 镜像: $ftype"

    # 可启动性判据：优先用 xorriso 探测「有效的 El Torito 启动记录」——这才是
    # 真正的可启动标记。注意：libmagic 5.45（Ubuntu 24.04）对 isohybrid-GPT ISO
    # 只报告 `(DOS/MBR boot sector)`，从不输出 `GPT`，所以不能再用 grep 'GPT'
    # 判定（会把合法 ISO 误 die，参见 tests/test-verify-product-gate.sh）。
    # xorriso 缺失时回退到 `file` 含 `DOS/MBR`，保证闸门不会变成空操作。
    local boot_ok=no
    if command -v xorriso >/dev/null 2>&1; then
        if xorriso -indev "$OUT" -report_el_torito plain 2>/dev/null \
                | grep -q '^El Torito boot img'; then
            boot_ok=yes
        fi
    else
        echo "$ftype" | grep -q 'DOS/MBR' && boot_ok=yes
    fi
    [[ "$boot_ok" == yes ]] \
        || die "产物无可启动的 El Torito 记录（也非 DOS/MBR boot sector）: $ftype"

    local size_human
    size_human="$(du -h "$OUT" | awk '{print $1}')"
    echo "----------------------------------------------------------------"
    echo "✓ ISO 构建成功"
    echo "  路径: $OUT"
    echo "  大小: $size_human"
    echo "  类型: $ftype"
    echo "----------------------------------------------------------------"
}

# ===========================================================================
# main()
# ===========================================================================
main() {
    # ---- 配置（环境变量覆盖）----
    # ORIG_ISO 默认值：在 sudo 下用「真正调用者」(SUDO_USER) 的家目录，而非
    # root 的 $HOME（=/root）。否则默认值会落到 /root/下载/... 而源 ISO 其实
    # 在调用者家目录（如 /home/<user>/下载/...），validate_env 会立即报「源 ISO
    # 不存在」。无 SUDO_USER / getent 失败时回退到 $HOME。
    if [[ -z "${ORIG_ISO:-}" ]]; then
        local _real_user="${SUDO_USER:-${USER:-$(whoami)}}"
        local _real_home
        _real_home="$(getent passwd "$_real_user" 2>/dev/null | cut -d: -f6 || true)"
        local _base_home="${_real_home:-$HOME}"
        ORIG_ISO="${_base_home}/下载/ubuntu-24.04.4-desktop-amd64.iso"
    fi
    ORIG_ISO="$(realpath "$ORIG_ISO" 2>/dev/null || echo "$ORIG_ISO")"
    BUILD_DIR="${BUILD_DIR:-/tmp}"
    VERSION="${VERSION:-$(date +%Y.%m.%d)}"

    # 脚本所在目录 & 项目根
    THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    WS="$(realpath "$THIS_DIR/../..")"
    [[ -d "$WS" ]] || die "无法定位项目根 (WS)：$WS"

    # 产物路径
    OUT="$WS/packaging/iso/out/linkerhand-edu-${VERSION}-amd64.iso"
    mkdir -p "$(dirname "$OUT")"

    # 工作目录（ISODIR / ROOTFS / repro.sh 都在这下面，cleanup 一次删干净）
    WORK="$(mktemp -d -p "$BUILD_DIR" "linkerhand-build-XXXXXX")"
    ISODIR="$WORK/iso"
    ROOTFS="$WORK/rootfs"
    mkdir -p "$ISODIR"

    echo "================================================================"
    echo " LinkerHand Edu ISO 构建"
    echo "   版本:  $VERSION"
    echo "   源ISO: $ORIG_ISO"
    echo "   项目:  $WS"
    echo "   工作:  $WORK"
    echo "   产物:  $OUT"
    echo "================================================================"

    validate_env       # 步骤 1
    extract_iso        # 步骤 2
    unsquash_rootfs    # 步骤 3
    inject_payload     # 步骤 4
    run_chroot_customize  # 步骤 5（条件）
    repack_squashfs    # 步骤 6
    update_metadata    # 步骤 7
    rewrite_grub       # 步骤 8 ★
    recompute_md5      # 步骤 9
    build_iso_image    # 步骤 10 ★
    verify_product     # 步骤 11

    echo "构建完成。"
}

main "$@"
