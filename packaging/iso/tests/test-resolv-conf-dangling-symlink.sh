#!/usr/bin/env bash
#
# test-resolv-conf-dangling-symlink.sh — 回归测试：build-iso.sh 复制 /etc/resolv.conf 进
# rootfs 时，必须不被 rootfs 内的悬空符号链接（dangling symlink）卡死。
#
# 背景（root cause）：
#   build-iso.sh [5/11] chroot_mount() 中（约 L175-176）：
#       if [[ -f /etc/resolv.conf ]]; then
#           cp /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
#       fi
#   Ubuntu 24.04 的解包 rootfs 里，/etc/resolv.conf 是指向
#   ../run/systemd/resolve/stub-resolv.conf 的符号链接。而 build-iso.sh 在 ~L173 把
#   一个全新 tmpfs 挂到 $ROOTFS/run（未 bind-mount 宿主机 /run），于是该 symlink 的
#   目标不存在 → 悬空符号链接。GNU cp 默认拒绝「穿过」悬空 symlink 写文件：
#       cp: 不写入悬空符号链接 '.../rootfs/etc/resolv.conf' 的目标
#   该 cp 以非零码退出；build-iso.sh 顶部 `set -Eeuo pipefail`（L16）令整个构建在
#   [5/11] 静默中止。后续 chroot-customize.sh 的 apt-get update（L68）+ curl
#   github（L91-92）都依赖 DNS，所以这一次 cp 是致命的。
#
# 修复（singular + targeted）：
#       cp --remove-destination /etc/resolv.conf "$ROOTFS/etc/resolv.conf"
#   --remove-destination 先 unlink 目标 symlink，再写入一个真实常规文件 → 对悬空
#   symlink 鲁棒；目标不存在或已是常规文件时为 no-op-safe。不改 `if [[ -f ]]` 守卫。
#
# 本测试：在隔离的临时目录里复刻该场景（不跑完整构建），分别验证
#   - 旧命令（裸 cp）         → 在悬空 symlink 上失败（非零退出），写不出常规文件
#   - 修复命令（cp --remove-destination）→ 成功（退出码 0），且写入真实常规文件
# 两者都在 `set -e` 下运行，以复现「set -e 中止构建」的语义。
#
# 约定（对齐 test-casper-initrd-name.sh / test-orig-iso-sudo-home.sh 的 SELFTEST 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-resolv-conf-dangling-symlink.sh
#   不需 root、不需跑完整构建。

set -Eeuo pipefail

BUILD_ISO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build-iso.sh"
[[ -f "$BUILD_ISO" ]] || { echo "ERROR: 找不到 build-iso.sh: $BUILD_ISO" >&2; exit 2; }

fails=0
check() {
    # check <desc> <expected> <actual>
    local desc="$1" expected="$2" actual="$3"
    if [[ "$expected" == "$actual" ]]; then
        printf "  ok   | %s\n" "$desc"
    else
        printf "  FAIL | %s : expected '%s' got '%s'\n" "$desc" "$expected" "$actual" >&2
        fails=$((fails+1))
    fi
}

# 给定一个 cp 命令前缀（"cp" 或 "cp --remove-destination"），在悬空 symlink 场景下
# 运行它，返回退出码与目标是否为真实常规文件。
# 用法： run_cp_case <cp_prefix> <src> <dst_dir> ; 往 stdout 打 "<exit>\t<is_regular>"
run_cp_case() {
    local cp_prefix="$1" src="$2" dst_dir="$3"
    local dst="$dst_dir/etc/resolv.conf"
    local rc is_reg

    # set -e 下运行 cp；非零退出会被捕获（用 || 兜住，不打断本测试脚本）。
    set +e
    ( set -e; $cp_prefix "$src" "$dst"; ) >/dev/null 2>&1
    rc=$?
    set -e

    if [[ -L "$dst" ]]; then
        is_reg="0"   # 仍是符号链接（悬空或指向别处）→ 不是常规文件
    elif [[ -f "$dst" ]]; then
        is_reg="1"
    else
        is_reg="0"
    fi
    printf '%s\t%s' "$rc" "$is_reg"
}

echo "================================================================"
echo " 场景 A：复刻悬空符号链接场景（set -e 下 cp 行为）"
echo "================================================================"

# 临时目录做隔离沙箱（不碰真实 rootfs / 宿主机 /etc/resolv.conf）。
SANDBOX="$(mktemp -d)"
trap 'rm -rf -- "$SANDBOX" 2>/dev/null || true' EXIT

# 准备：源 resolv.conf（真实常规文件）
SRC="$SANDBOX/src-resolv.conf"
printf 'nameserver 192.0.2.53\n' > "$SRC"

# 准备：目标目录，内含一个指向「不存在目标」的悬空 symlink（复刻 Ubuntu 24.04
# rootfs 里 /etc/resolv.conf → ../run/systemd/resolve/stub-resolv.conf，
# 而 /run 是全新 tmpfs、目标不存在的情形）。
make_dangling_dst() {
    local root="$1"
    rm -rf -- "$root"
    mkdir -p "$root/etc"
    # 目标 ../run/systemd/resolve/stub-resolv.conf 不存在 → 悬空 symlink
    ln -s ../run/systemd/resolve/stub-resolv.conf "$root/etc/resolv.conf"
    # 断言场景就位：它确实是符号链接且解析失败（悬空）
    [[ -L "$root/etc/resolv.conf" ]] || { echo "FIXTURE FAIL: 未建成符号链接" >&2; exit 2; }
}

echo "  fixture: 悬空符号链接 $(readlink "$SANDBOX/old/etc/resolv.conf" 2>/dev/null || true)"

# --- 旧命令（裸 cp，无 --remove-destination）→ 期望失败 -----------------
make_dangling_dst "$SANDBOX/old"
old_out="$(run_cp_case "cp" "$SRC" "$SANDBOX/old")"
old_rc="${old_out%%$'\t'*}"
old_reg="${old_out##*$'\t'}"
echo "  旧命令 cp                      : exit=$old_rc, written_regular_file=$old_reg"
# 旧命令应失败：退出码非零（GNU cp 拒绝穿过悬空 symlink）
check "旧命令(裸cp)对悬空symlink失败: 退出码非0" "nonzero" "$([[ "$old_rc" -ne 0 ]] && echo nonzero || echo zero)"
# 旧命令不应写入真实常规文件（目标仍是悬空 symlink）
check "旧命令(裸cp)未写入常规文件" "0" "$old_reg"

# --- 修复命令（cp --remove-destination）→ 期望成功 ----------------------
make_dangling_dst "$SANDBOX/new"
new_out="$(run_cp_case "cp --remove-destination" "$SRC" "$SANDBOX/new")"
new_rc="${new_out%%$'\t'*}"
new_reg="${new_out##*$'\t'}"
echo "  修复命令 cp --remove-destination: exit=$new_rc, written_regular_file=$new_reg"
# 修复命令应成功：退出码 0
check "修复命令(--remove-destination)对悬空symlink成功: 退出码0" "0" "$new_rc"
# 修复命令应写入真实常规文件（不再是符号链接）
check "修复命令(--remove-destination)写入常规文件" "1" "$new_reg"

# --- 内容校验：写入的常规文件内容应等于源 ------------------------------
if [[ "$new_reg" == "1" ]]; then
    if cmp -s "$SRC" "$SANDBOX/new/etc/resolv.conf"; then
        printf "  ok   | 写入文件内容与源一致\n"
    else
        printf "  FAIL | 写入文件内容与源不一致\n" >&2
        fails=$((fails+1))
    fi
fi
echo

echo "================================================================"
echo " 场景 B：脚本内容守卫（恒定）"
echo "================================================================"

# 守卫：build-iso.sh 的 resolv.conf cp 必须带 --remove-destination。
# 抓 resolv.conf 那一行的 cp 调用（容许任意空白）。
if grep -nE 'cp +--remove-destination +/etc/resolv\.conf +"?\$\{?ROOTFS\}?/etc/resolv\.conf' \
        "$BUILD_ISO" >/dev/null 2>&1; then
    printf "  ok   | build-iso.sh resolv.conf cp 已用 --remove-destination\n"
else
    printf "  FAIL | build-iso.sh resolv.conf cp 未用 --remove-destination（修复未落地）\n" >&2
    fails=$((fails+1))
fi

# 守卫：仍保留 if [[ -f ... ]] 守卫（不应被改掉）。
if grep -qE 'if *\[\[ *-f */etc/resolv\.conf *\]\]' "$BUILD_ISO"; then
    printf "  ok   | build-iso.sh 保留 if [[ -f /etc/resolv.conf ]] 守卫\n"
else
    printf "  FAIL | build-iso.sh 丢失 if [[ -f /etc/resolv.conf ]] 守卫\n" >&2
    fails=$((fails+1))
fi
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
