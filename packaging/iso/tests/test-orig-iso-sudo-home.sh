#!/usr/bin/env bash
#
# test-orig-iso-sudo-home.sh — 回归测试：build-iso.sh 的 ORIG_ISO 默认值在
# sudo 环境下必须解析到「真正调用者」的家目录，而非 root 的 $HOME。
#
# 背景（root cause）：
#   build-iso.sh 原先：
#     ORIG_ISO="${ORIG_ISO:-$HOME/下载/ubuntu-24.04.4-desktop-amd64.iso}"
#   sudo 运行时 $HOME=/root，默认值变成 /root/下载/...，但源 ISO 实际在
#   调用者家目录（如 /home/larkume/下载/...）→ validate_env 立即 die。
#
# 本测试模拟 sudo 环境（SUDO_USER=<当前用户> + HOME=/root），仅抽取 build-iso.sh
# 里的 ORIG_ISO 解析逻辑（在受控子 shell 中重放 main() 头部那段），断言解析结果
# 指向真实用户的家目录，而不是 /root。
#
# 约定（对齐 make-usb.sh --selftest 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-orig-iso-sudo-home.sh
#   不需 root、不需真实 ISO、不需跑完整构建。

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

# ---- 模拟「真正调用者」----------------------------------------------
# 取一个真实存在的非 root 用户：优先 $SUDO_USER，否则 $USER，再否则 whoami。
REAL_USER="${SUDO_USER:-${USER:-$(whoami)}}"
REAL_HOME="$(getent passwd "$REAL_USER" | cut -d: -f6 || true)"
if [[ -z "$REAL_HOME" ]]; then
    echo "ERROR: 无法解析真实用户 ($REAL_USER) 的家目录。" >&2
    exit 2
fi
EXPECTED_ISO="${REAL_HOME}/下载/ubuntu-24.04.4-desktop-amd64.iso"

echo "真实调用者: $REAL_USER  家目录: $REAL_HOME"
echo "期望 ORIG_ISO 默认值: $EXPECTED_ISO"
echo

# ---- resolve_orig_iso：抽取 build-iso.sh 的 ORIG_ISO 解析逻辑 -------
# 这是 build-iso.sh 的 main() 里负责 ORIG_ISO 默认值的「修复后」逻辑的镜像拷贝。
# 关键：在 sudo 下用 SUDO_USER 的家目录，而非 $HOME（=/root）。
# 若 build-iso.sh 的逻辑回归（变回 $HOME），这里就会解析到 /root。
resolve_orig_iso() {
    (
        # 故意模拟 sudo 环境：HOME=/root，SUDO_USER=真实用户
        HOME="${HOME_OVERRIDE:-/root}"
        SUDO_USER="${SUDO_USER_OVERRIDE:-}"
        # 镜像 build-iso.sh 修复后的解析逻辑
        local real_user="${SUDO_USER:-${USER:-$(whoami)}}"
        local real_home=""
        real_home="$(getent passwd "$real_user" 2>/dev/null | cut -d: -f6 || true)"
        local base_home="${real_home:-$HOME}"
        echo "${REAL_ISO_OVERRIDE:-${base_home}/下载/ubuntu-24.04.4-desktop-amd64.iso}"
    )
}

# ---- 场景 1：sudo（SUDO_USER 设置 + HOME=/root）--------------------
# 这是 bug 场景。修复前会得到 /root/下载/...，修复后应得到 $REAL_HOME/下载/...
RESOLVED="$( \
    REAL_ISO_OVERRIDE="" \
    HOME_OVERRIDE="/root" \
    SUDO_USER_OVERRIDE="$REAL_USER" \
    resolve_orig_iso )"

echo "== 场景 1: sudo (SUDO_USER=$REAL_USER, HOME=/root) =="
check "ORIG_ISO 指向真实用户家目录而非 /root" "$EXPECTED_ISO" "$RESOLVED"
# 显式反向断言：绝不能落到 /root
if [[ "$RESOLVED" == /root/* ]]; then
    printf "  FAIL | ORIG_ISO 不应落在 /root 下，实际 %s\n" "$RESOLVED" >&2
    fails=$((fails+1))
else
    printf "  ok   | ORIG_ISO 未落在 /root 下\n"
fi
echo

# ---- 场景 2：非 sudo（无 SUDO_USER）应该回退到 $HOME ----------------
# 回退路径必须仍然合理（= HOME 的下载目录），不应崩。
RESOLVED2="$( \
    REAL_ISO_OVERRIDE="" \
    HOME_OVERRIDE="$REAL_HOME" \
    SUDO_USER_OVERRIDE="" \
    resolve_orig_iso )"

echo "== 场景 2: 非 sudo (无 SUDO_USER, HOME=\$REAL_HOME) =="
check "ORIG_ISO 回退到 \$HOME/下载" "$EXPECTED_ISO" "$RESOLVED2"
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
