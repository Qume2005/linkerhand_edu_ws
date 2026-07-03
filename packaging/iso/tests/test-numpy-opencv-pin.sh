#!/usr/bin/env bash
#
# test-numpy-opencv-pin.sh — 回归测试：chroot-customize.sh A11 段 pip 安装的 pin 集
# 必须与 SYSTEM numpy 1.26.4（Ubuntu 24.04 / ROS Jazzy，apt 装的，无 pip RECORD）兼容。
#
# 背景（root cause）：
#   旧 A11 装的是
#       mujoco==3.4.0 mediapipe==0.10.32 opencv-python-headless==4.13.0.92
#   opencv-python-headless 4.13.0.92 的 METADATA 对 py3.12 硬要 numpy>=2；而系统 numpy
#   是 apt 的 1.26.4，pip 无法卸载它（无 RECORD）→ chroot 内 pip 死于
#   "Cannot uninstall numpy"。同时 mediapipe 0.10.32 依赖 opencv-contrib-python（非 headless），
#   与单独装的 headless 争抢 cv2 命名空间，亦是冲突源。
#
# 修复（Approach A）：
#   显式锁 numpy==1.26.4，opencv 改用 opencv-contrib-python==4.11.0.86
#   （4.11 对 py3.12 仅要 numpy>=1.26.0 无上界；contrib 是 headless 超集，单行覆盖 mediapipe）。
#
# 验证证据（一次性、记入交付文档，不在每次测试时重下 wheel）：
#   在 py3.12.3 throwaway venv 内
#     pip install numpy==1.26.4 mujoco==3.4.0 mediapipe==0.10.32 opencv-contrib-python==4.11.0.86
#   pip 干净解析（无 ResolutionImpossible，仅装 1 个 opencv），随后
#     import numpy, mujoco, mediapipe, cv2  →  numpy 1.26.4 / cv2 4.11.0 / IMPORTS_OK  (exit 0)
#
# 本测试：纯内容守卫（grep A11 段），不跑 pip、不下载 wheel。验证：
#   - numpy==1.26.4 被 A11 显式锁定
#   - opencv 用 opencv-contrib-python==4.11.0.86（4.11 级、numpy 1.x 兼容）
#   - 不再出现 numpy>=2 触发型 opencv 版本（opencv-python-headless==4.13 / 任何 4.12+/4.13 headless）
#   - 保留 mujoco==3.4.0 与 mediapipe==0.10.32（项目锁定的版本）
#
# 约定（对齐 test-resolv-conf-dangling-symlink.sh 的 SELFTEST 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-numpy-opencv-pin.sh
#   不需 root、不需 pip、不需联网。

set -Eeuo pipefail

CHROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/chroot-customize.sh"
[[ -f "$CHROOT" ]] || { echo "ERROR: 找不到 chroot-customize.sh: $CHROOT" >&2; exit 2; }

# A11 段：从 "A11" 标记行到下一个 "#---" / "#====" 分隔标记之间。这里直接对整个脚本
# 做针对性 grep（pin 字符串在脚本内应唯一），避免脆弱的行段切片。

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
    if grep -nE -- "$pattern" "$CHROOT" >/dev/null 2>&1; then
        printf "  ok   | %s\n" "$desc"
    else
        printf "  FAIL | %s : 未在 chroot-customize.sh 命中 /%s/\n" "$desc" "$pattern" >&2
        fails=$((fails+1))
    fi
}
check_absent() {
    # check_absent <desc> <pattern>  ——  pattern 在脚本内必须不命中（0 行）
    local desc="$1" pattern="$2"
    if grep -nE -- "$pattern" "$CHROOT" >/dev/null 2>&1; then
        printf "  FAIL | %s : 在 chroot-customize.sh 中不应存在（命中 /%s/）\n" "$desc" "$pattern" >&2
        fails=$((fails+1))
    else
        printf "  ok   | %s\n" "$desc"
    fi
}

echo "================================================================"
echo " A11 pin 集内容守卫（numpy 1.26.4 兼容性）"
echo "================================================================"

echo "  目标: $CHROOT"
echo

echo "  --- 必备 pin（应存在）---"
check_present "A11 显式锁 numpy==1.26.4"           'numpy==1\.26\.4'
check_present "A11 保留 mujoco==3.4.0"              'mujoco==3\.4\.0'
check_present "A11 保留 mediapipe==0.10.32"         'mediapipe==0\.10\.32'
check_present "A11 用 opencv-contrib-python==4.11.0.86" 'opencv-contrib-python==4\.11\.0\.86'
echo

echo "  --- 冲突 / numpy>=2 触发型 opencv（应不存在）---"
check_absent  "不再装 numpy>=2-forcing opencv-python-headless 4.13" 'opencv-python-headless==4\.13'
check_absent  "不再装任何 headless 4.12+/4.13"                      'opencv-python-headless==4\.1[2-9]'
check_absent  "不再装 contrib 4.12+/4.13（会要 numpy>=2）"          'opencv-contrib-python==4\.1[2-9]'
# 同时安装 headless 与 contrib 会争抢 cv2 命名空间 → 只要还存在 headless 行即冲突
check_absent  "不再混装 opencv-python-headless（与 contrib 争 cv2）" 'opencv-python-headless'
echo

echo "  --- 关键单条数（防重复 / 防意外多行）---"
# 只数「实际安装行」：缩进、非注释的 pin 行。注释行里的 pin 引用（说明文字）
# 不算，避免把注释里对版本的描述误判为重复安装。
np_count=$(grep -nE -- 'numpy==1\.26\.4' "$CHROOT" | grep -vcE '^[0-9]+:[[:space:]]*#' || true)
check "numpy==1.26.4 作为安装行恰好出现 1 次" "1" "$np_count"
cv_count=$(grep -nE -- 'opencv-contrib-python==4\.11\.0\.86' "$CHROOT" | grep -vcE '^[0-9]+:[[:space:]]*#' || true)
check "opencv-contrib-python==4.11.0.86 作为安装行恰好出现 1 次" "1" "$cv_count"
echo

# --------------------------------------------------------------------
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
