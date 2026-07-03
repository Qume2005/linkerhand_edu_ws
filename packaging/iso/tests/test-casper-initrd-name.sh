#!/usr/bin/env bash
#
# test-casper-initrd-name.sh — 回归测试：build-iso.sh 的 casper initrd 文件名必须
# 与源 ISO 实际包含的文件名一致。
#
# 背景（root cause）：
#   Ubuntu 24.04.4 desktop ISO 把 initrd 发布为 /casper/initrd（无 .gz 扩展名）。
#   build-iso.sh 原先硬编码 casper/initrd.gz（必需文件数组 + 4 条 GRUB initrd 行），
#   于是 extract_iso() 的必需文件校验立即 die：
#       ERROR: ISO 缺少必需文件: casper/initrd.gz
#   建构在 [2/11] 解包原 ISO 阶段就失败。casper/vmlinuz 与 casper/minimal.squashfs
#   都与 ISO 一致，只有 initrd 文件名错了——非结构性问题。
#
# 本测试做两件事：
#   1) 源 ISO 内容校验（若源 ISO 可访问）：复刻 extract_iso() 的必需文件数组，
#      断言数组中每个文件都真实存在于源 ISO（用 xorriso -find 列出）。修复前
#      casper/initrd.gz 不在 ISO 内 → 失败；修复后 casper/initrd 在 ISO 内 → 通过。
#   2) 脚本内容守卫（ISO 不可访问时仍有效）：断言 build-iso.sh 中不再出现
#      initrd.gz 字面量，且 casper/initrd 被引用。修复前 initrd.gz 残留 → 失败。
#
# 约定（对齐 test-orig-iso-sudo-home.sh 的 SELFTEST 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-casper-initrd-name.sh
#   不需 root、不需跑完整构建。源 ISO 不可读时仅做脚本内容守卫。

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

# ---- 抽取 build-iso.sh 中 extract_iso() 的必需文件数组 ----------------
# 复刻该数组的「内容」：解析出 casper/* 条目，用于核对它们是否真实存在于源 ISO。
required_casper_files() {
    # 从 build-iso.sh 里抓 need=( ...) 块中的 casper/* 行（保留相对路径，无 $ISODIR 前缀）
    awk '
        /local need=\(/ {inarr=1}
        inarr && /casper\// {
            sub(/^[[:space:]]+/, "")
            gsub(/[[:space:]]+$/, "")
            print
        }
        inarr && /\)/ {inarr=0}
    ' "$BUILD_ISO"
}

echo "================================================================"
echo " 场景 A：脚本内容守卫（恒定，不依赖源 ISO）"
echo "================================================================"

# 守卫 1：build-iso.sh 不得再出现 initrd.gz 字面量（旧的错误文件名）。
# grep -c 即使无匹配也会打印 0（仅退出码非零），故不要 || echo 0（否则得 "0\n0"）。
n_old="$(grep -c 'initrd\.gz' "$BUILD_ISO" 2>/dev/null || true)"
check "build-iso.sh 无 initrd.gz 字面量残留" "0" "$n_old"

# 守卫 2：build-iso.sh 必须引用 casper/initrd（必需文件数组里）。
if grep -qE '(^|[[:space:]])casper/initrd([[:space:]]|$)' "$BUILD_ISO"; then
    printf "  ok   | build-iso.sh 引用 casper/initrd\n"
else
    printf "  FAIL | build-iso.sh 未引用 casper/initrd（必需文件缺失）\n" >&2
    fails=$((fails+1))
fi
echo

# ---- 场景 B：源 ISO 内容校验（若源 ISO 可读）--------------------------
# 复刻 extract_iso() 的语义：对 need[] 数组中每个 casper/* 文件，断言它真实存在于源 ISO。
echo "================================================================"
echo " 场景 B：源 ISO 内容校验（复刻 extract_iso 的必需文件检查）"
echo "================================================================"

# 复刻 build-iso.sh main() 的 ORIG_ISO 默认解析（与 test-orig-iso-sudo-home 同源），
# 但允许 ORIG_ISO 环境变量覆盖。
resolve_orig_iso() {
    if [[ -n "${ORIG_ISO:-}" ]]; then echo "$ORIG_ISO"; return; fi
    local real_user="${SUDO_USER:-${USER:-$(whoami)}}"
    local real_home
    real_home="$(getent passwd "$real_user" 2>/dev/null | cut -d: -f6 || true)"
    local base_home="${real_home:-$HOME}"
    echo "${base_home}/下载/ubuntu-24.04.4-desktop-amd64.iso"
}

ORIG_ISO_RESOLVED="$(resolve_orig_iso)"
echo "源 ISO: $ORIG_ISO_RESOLVED"

# 把源 ISO 文件清单写到临时文件（绕开「命令替换 + pipefail + set -e」的交互，
# 保证成员判断基于稳定的磁盘内容）。每行一个绝对路径（去掉 xorriso 的单引号包裹）。
iso_list_file=""
if [[ -f "$ORIG_ISO_RESOLVED" ]] && command -v xorriso >/dev/null 2>&1; then
    iso_list_file="$(mktemp)"
    if xorriso -indev "$ORIG_ISO_RESOLVED" -find / -type f 2>/dev/null \
         | sed -E "s/^'(.*)'$/\1/" > "$iso_list_file"; then
        echo "已读取源 ISO 文件清单 → $iso_list_file"
    else
        echo "WARN: 读取源 ISO 文件清单失败，跳过场景 B（仅场景 A 守卫生效）。"
        rm -f "$iso_list_file"; iso_list_file=""
    fi
else
    echo "WARN: 源 ISO 不可读或缺少 xorriso，跳过场景 B（仅场景 A 守卫生效）。"
fi

cleanup_iso_list() { [[ -n "${iso_list_file:-}" ]] && rm -f -- "$iso_list_file" 2>/dev/null || true; }
trap cleanup_iso_list EXIT

if [[ -n "$iso_list_file" && -s "$iso_list_file" ]]; then
    # 对 need[] 里每个 casper/* 条目，断言其存在于源 ISO。
    # 修复前：casper/initrd.gz → 不在清单 → FAIL。
    # 修复后：casper/initrd     → 在清单     → PASS。
    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        # 脚本里是相对路径 casper/...；ISO 清单里是 /casper/... 绝对路径。
        abs="/${rel}"
        if grep -Fxq -- "$abs" "$iso_list_file"; then
            printf "  ok   | 源 ISO 含 %s\n" "$rel"
        else
            printf "  FAIL | 源 ISO 缺 %s（build-iso.sh 必需但 ISO 未提供）\n" "$rel" >&2
            fails=$((fails+1))
        fi
    done < <(required_casper_files)
else
    echo "(跳过)"
fi
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
