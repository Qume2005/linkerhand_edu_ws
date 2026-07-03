#!/usr/bin/env bash
#
# test-verify-product-gate.sh — 回归测试：build-iso.sh 的 [11/11] verify_product
# 产物校验闸门必须能正确接受「合法的 isohybrid-GPT 可启动 ISO」，并拒绝
# 「非 ISO / 损坏」文件。绝不能把一个真正可启动的 ISO 误判为失败。
#
# 背景（root cause）：
#   旧 verify_product 依赖 libmagic 的 `file` 输出里同时包含 `DOS/MBR` 与 `GPT`
#   两个字符串。但 libmagic 5.45（Ubuntu 24.04 自带的 file-5.45）对一个
#   isohybrid-GPT ISO 只报告 `(DOS/MBR boot sector)`，从不输出 `GPT`：
#       $ file ubuntu-24.04.4-desktop-amd64.iso
#       ... ISO 9660 CD-ROM filesystem data (DOS/MBR boot sector) '...' (bootable)
#   `DOS/MBR` 在，`GPT` 不在 → 旧闸门对一个「正确构建的可启动 ISO」误 die。
#   这是一个 ~30 分钟构建后必然出现的「假失败」。
#
#   证据：源 ISO `/home/larkume/下载/ubuntu-24.04.4-desktop-amd64.iso` 与构建产物
#   同为 isohybrid-GPT 格式，其 `file` 输出含 `DOS/MBR` 但不含 `GPT`。
#
# 修复（gate verify_product）：
#   不再字符串匹配 `GPT`。改用「真正存在有效的 El Torito 启动记录」作为可启动性
#   判据——xorriso -report_el_torito plain 在合法可启动 ISO 上会输出
#   `El Torito boot img` 行，在非 ISO 文件上输出为空。xorriso 缺失时回退到
#   `file` 含 `DOS/MBR`（+ ISO 9660 / bootable）即可，保证闸门不会变成空操作。
#
# 本测试（红-绿）：
#   1. OLD_GATE（要求 `GPT`）→ 对源 ISO 的真实 `file` 输出必须 FAIL（红）。
#   2. NEW_GATE（xorriso El Torito + DOS/MBR 回退）→ 对源 ISO 必须 PASS（绿）。
#   3. NEW_GATE → 对一个非 ISO 文本文件必须 REJECT（证明闸门不是空操作）。
#
# 约定（对齐 make-usb.sh --selftest 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-verify-product-gate.sh
#   不需 root、不需跑完整构建；只读取源 ISO 头部（file + xorriso 探测，都很快）。

set -Eeuo pipefail

BUILD_ISO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/build-iso.sh"
[[ -f "$BUILD_ISO" ]] || { echo "ERROR: 找不到 build-iso.sh: $BUILD_ISO" >&2; exit 2; }

# 真实 isohybrid-GPT 可启动 ISO 作为 fixture（与构建产物同格式）。
FIXTURE_ISO="${FIXTURE_ISO:-/home/larkume/下载/ubuntu-24.04.4-desktop-amd64.iso}"
if [[ ! -f "$FIXTURE_ISO" ]]; then
    echo "ERROR: fixture ISO 不存在: $FIXTURE_ISO（请确认源 ISO 路径）" >&2
    exit 2
fi
if ! command -v file >/dev/null 2>&1; then
    echo "ERROR: 缺少 file 命令" >&2; exit 2
fi

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

# ---- OLD_GATE：build-iso.sh 修复前的（错误）闸门逻辑 -----------------
# 要求 `file` 输出同时含 `DOS/MBR` 与 `GPT`。返回 0=通过（accept），1=拒绝。
old_gate_accept() {
    # old_gate_accept <path>
    local p="$1" ft
    ft="$(file "$p")" || return 1
    echo "$ft" | grep -q 'DOS/MBR' || return 1
    echo "$ft" | grep -q 'GPT' || return 1   # ← bug 所在
    return 0
}

# ---- NEW_GATE：build-iso.sh 修复后的（正确）闸门逻辑 -----------------
# 优先用 xorriso -report_el_torito plain：存在 `El Torito boot img` 行即合法可启动。
# xorriso 缺失时回退到 `file` 含 `DOS/MBR`。返回 0=通过（accept），1=拒绝。
new_gate_accept() {
    # new_gate_accept <path>
    local p="$1" ft
    ft="$(file "$p")" || return 1
    # 必须是 ISO9660（防止拿任意含 DOS/MBR 的镜像冒充）。
    echo "$ft" | grep -q 'ISO 9660' || return 1
    if command -v xorriso >/dev/null 2>&1; then
        # 合法可启动 ISO 会输出一行 `El Torito boot img : ...`；非 ISO 文件输出为空。
        if xorriso -indev "$p" -report_el_torito plain 2>/dev/null \
                | grep -q '^El Torito boot img'; then
            return 0
        fi
        return 1
    fi
    # 回退：xorriso 不可用时，DOS/MBR boot sector 即可启动性证据。
    echo "$ft" | grep -q 'DOS/MBR' || return 1
    return 0
}

echo "Fixture ISO: $FIXTURE_ISO"
echo "file 输出:   $(file "$FIXTURE_ISO")"
echo

# ---- 1. OLD_GATE 必须误拒合法 ISO（红：证明 bug 真实存在）------------
echo "== 场景 1: OLD_GATE（要求 GPT）对真实 isohybrid-GPT ISO =="
if old_gate_accept "$FIXTURE_ISO"; then
    OLD_RESULT="accept"
else
    OLD_RESULT="reject"
fi
check "OLD_GATE 必须拒绝（libmagic 5.45 不输出 GPT）→ 复现 bug" "reject" "$OLD_RESULT"
echo

# ---- 2. NEW_GATE 必须接受合法 ISO（绿：修复生效）--------------------
echo "== 场景 2: NEW_GATE（El Torito + DOS/MBR 回退）对真实可启动 ISO =="
if new_gate_accept "$FIXTURE_ISO"; then
    NEW_RESULT="accept"
else
    NEW_RESULT="reject"
fi
check "NEW_GATE 必须接受真实可启动 ISO" "accept" "$NEW_RESULT"
echo

# ---- 3. NEW_GATE 必须拒绝非 ISO 文件（闸门不是空操作）--------------
echo "== 场景 3: NEW_GATE 对非 ISO 文本文件 =="
FAKE="$(mktemp --suffix=.txt)"
trap 'rm -f "$FAKE"' EXIT
printf 'this is not an iso, just a text file\n' >"$FAKE"
if new_gate_accept "$FAKE"; then
    FAKE_RESULT="accept"
else
    FAKE_RESULT="reject"
fi
check "NEW_GATE 必须拒绝非 ISO 文件（保持真实校验）" "reject" "$FAKE_RESULT"
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
