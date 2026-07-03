#!/usr/bin/env bash
#
# test-test-iso-dep-check.sh — 回归测试：test-iso.sh 的 QEMU 依赖检查必须探测真正的二进制
# qemu-system-x86_64，而非 Debian/Ubuntu 的包名/元包名 qemu-system-x86（后者不是二进制，
# command -v 找不到 → check_dep die → QEMU 启动前即中止）。
#
# 背景（root cause）：
#   test-iso.sh:90 旧写作 `check_dep qemu-system-x86 qemu-system-x86`。
#   check_dep 的第一个参数是被 `command -v "$1"` 探测的【二进制名】（见 test-iso.sh:86），
#   第二个参数只是 die 信息里给用户看的【安装提示包名】。
#   qemu-system-x86 是包/元包名，宿主机上没有同名二进制 → command -v 失败 → die 中止。
#   真正的二进制是 qemu-system-x86_64（脚本自己在 launch_qemu 第 ~187 行就调用它）。
#   证据：command -v qemu-system-x86 → exit 1（无输出）；
#         command -v qemu-system-x86_64 → /usr/bin/qemu-system-x86_64（exit 0）；
#         dpkg -S /usr/bin/qemu-system-x86_64 → qemu-system-x86 包提供该二进制。
#
# 修复（singular + targeted）：
#   line 90 改为 `check_dep qemu-system-x86_64 qemu-system-x86`
#   （第一参数探测真二进制 qemu-system-x86_64；第二参数保留元包 qemu-system-x86 作安装提示）。
#
# 本测试两部分：
#   (a) 内容守卫：line 90 的 check_dep 第一参数必须是真二进制 qemu-system-x86_64，
#       不得把 qemu-system-x86 当作二进制名探测。
#   (b) 功能验证：在本宿主机（qemu-system-x86_64 已安装）上，fixed check_dep 的探测逻辑
#       必须通过（command -v qemu-system-x86_64 成功）。
#
# 约定（对齐 test-resolv-conf-dangling-symlink.sh / test-numpy-opencv-pin.sh 的 SELFTEST 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-test-iso-dep-check.sh
#   不需 root、不启动 QEMU、不联网。

set -Eeuo pipefail

TEST_ISO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/test-iso.sh"
[[ -f "$TEST_ISO" ]] || { echo "ERROR: 找不到 test-iso.sh: $TEST_ISO" >&2; exit 2; }

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
check_present() {
    # check_present <desc> <pattern>  ——  pattern 在脚本内必须命中（≥1 行）
    local desc="$1" pattern="$2"
    if grep -nE -- "$pattern" "$TEST_ISO" >/dev/null 2>&1; then
        printf "  ok   | %s\n" "$desc"
    else
        printf "  FAIL | %s : 未在 test-iso.sh 命中 /%s/\n" "$desc" "$pattern" >&2
        fails=$((fails+1))
    fi
}
check_absent() {
    # check_absent <desc> <pattern>  ——  pattern 在脚本内必须不命中（0 行）
    local desc="$1" pattern="$2"
    if grep -nE -- "$pattern" "$TEST_ISO" >/dev/null 2>&1; then
        printf "  FAIL | %s : 在 test-iso.sh 中不应存在（命中 /%s/）\n" "$desc" "$pattern" >&2
        fails=$((fails+1))
    else
        printf "  ok   | %s\n" "$desc"
    fi
}

echo "================================================================"
echo " test-iso.sh QEMU 依赖检查守卫（探测真二进制 qemu-system-x86_64）"
echo "================================================================"

echo "  目标: $TEST_ISO"
echo

echo "  --- (a) 内容守卫：check_dep 第一参数必须是真二进制 ---"
# 依赖检查行（check_common_deps 内唯一一条 check_dep）必须把真二进制 qemu-system-x86_64
# 作为第一参数。这里精确锚定 check_dep 行（含 qemu 关键字），避免误命中注释/其他行。
check_present "依赖检查探测真二进制 qemu-system-x86_64" 'check_dep[[:space:]]+qemu-system-x86_64[[:space:]]'
# 反面：不得把元包名 qemu-system-x86 当作二进制探测（即不能出现 `check_dep qemu-system-x86 `
# 这种以 qemu-system-x86 作为 command -v 目标的形式——其后跟空格/换行即把包名当二进制）。
check_absent  "不得把元包名 qemu-system-x86 当二进制探测" 'check_dep[[:space:]]+qemu-system-x86[[:space:]]'
echo

echo "  --- (b) 功能验证：fixed 探测在本宿主机通过 ---"
# 本宿主机 qemu-system-x86_64 已安装 → command -v 必须成功（exit 0 且有输出）。
QEMU_BIN=""
if command -v qemu-system-x86_64 >/dev/null 2>&1; then
    QEMU_BIN="$(command -v qemu-system-x86_64)"
    check "command -v qemu-system-x86_64 成功（真二进制存在）" "0" "0"
else
    check "command -v qemu-system-x86_64 成功（真二进制存在）" "0" "1"
fi
# 同时确认元包名 qemu-system-x86 确实【不是】可被 command -v 找到的二进制（这正是 bug 根因）
if command -v qemu-system-x86 >/dev/null 2>&1; then
    check "command -v qemu-system-x86 失败（证明它是包名非二进制）" "1" "0"
else
    check "command -v qemu-system-x86 失败（证明它是包名非二进制）" "1" "1"
fi
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
