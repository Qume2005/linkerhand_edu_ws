#!/usr/bin/env bash
#
# test-ros-source-strict-mode.sh — 回归测试：chroot-customize.sh 在 `set -Eeuo pipefail`
# 下 source /opt/ros/jazzy/setup.bash + 跑 colcon 时，必须用「strict-mode-off 守卫」包住，
# 否则 ROS/colcon 这些非 set -u-safe 的第三方脚本会在引用未绑定变量时令整个构建中止。
#
# 背景（root cause）：
#   chroot-customize.sh L10: set -Eeuo pipefail（含 -u/nounset）。
#   C1 步骤 L233-235：
#       source /opt/ros/jazzy/setup.bash
#       cd "$SKEL"
#       colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
#   /opt/ros/jazzy/setup.bash 第 8 行引用 AMENT_TRACE_SETUP_FILES（未定义）。在 set -u 下
#   这是致命错误 → 非零退出 → set -e 令整脚本中止，报：
#       /opt/ros/jazzy/setup.bash: 行 8: AMENT_TRACE_SETUP_FILES: 未绑定的变量
#       ERROR: chroot-customize 执行失败
#   ROS/colcon 脚本本就不是为 set -u 编写的；在 strict mode 下 source/调用它们就是 bug。
#
# 修复（singular + targeted，标准惯用法 — 不全局关闭 strict mode）：
#   每一个 source .../setup.bash 与 ROS/colcon 调用点都用「保存选项 → 放松 → 运行 → 还原」
#   守卫包起来，例：
#       _saveset="$(set +o)"
#       set +u +e
#       source /opt/ros/jazzy/setup.bash
#       colcon build ...
#       eval "$_saveset"
#
# 本测试：在隔离临时目录里复刻该失败模式（沙箱内无法 source 真实 ROS setup.bash，故用一个
# 引用未绑定变量的 stub 脚本模拟 ROS setup.bash）。验证：
#   - 场景 A（RED，复现 bug）：set -u 下裸 source stub → 引用未绑定变量 → 非零退出 →
#     set -e 令脚本中止（退出码非零）。
#   - 场景 B（GREEN，守卫生效）：set -u 下用「set +u; source stub; set -u」守卫包住 →
#     退出码 0，且 stub 的副作用（ROS setup 侧效果）可见。
# 两者都在 set -e 下运行以复现「set -e 中止构建」的语义。
#
# 场景 C：chroot-customize.sh 内容守卫 — 确认 C1 的 source/colcon 已被 strict-mode-off
# 守卫包住（grep 形态恒定检查），且脚本顶部的 set -Eeuo pipefail 仍在（没有全局放松）。
#
# 约定（对齐 test-resolv-conf-dangling-symlink.sh 的 SELFTEST 风格）：
#   失败计数为 0 时打印 "SELFTEST PASS (0 failures)" 并 exit 0；否则非零退出。
#
# 运行：bash packaging/iso/tests/test-ros-source-strict-mode.sh
#   不需 root、不需 ROS、不需跑完整构建。

set -Eeuo pipefail

CHROOT_SH="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/chroot-customize.sh"
[[ -f "$CHROOT_SH" ]] || { echo "ERROR: 找不到 chroot-customize.sh: $CHROOT_SH" >&2; exit 2; }

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

# 给定一个「source 方式」（"unguarded" 或 "guarded"），在 set -u 下尝试 source stub，
# 返回退出码与「stub 副作用是否可见」。
# 用法： run_source_case <mode> <stub> ; 往 stdout 打 "<exit>\t<effect>"
run_source_case() {
    local mode="$1" stub="$2"
    local rc effect

    # 在子 shell 里以 set -e + set -u 运行，复刻 chroot-customize.sh 的 strict mode 语义。
    set +e
    (
        set -e
        set -u
        if [[ "$mode" == "guarded" ]]; then
            # 守卫：保存选项 → 放松 nounset/errexit → source → 还原
            _saveset="$(set +o)"
            set +u +e
            # shellcheck disable=SC1090
            source "$stub"
            eval "$_saveset"
        else
            # 裸 source（无守卫）— 复刻 bug
            # shellcheck disable=SC1090
            source "$stub"
        fi
        echo "after-source-ok"
    ) >/dev/null 2>&1
    rc=$?
    set -e

    # stub 的副作用：往 STUB_SIDE_EFFECT 指向的文件写一行。
    if [[ -f "${STUB_SIDE_EFFECT:-}" ]]; then
        effect="1"
    else
        effect="0"
    fi
    printf '%s\t%s' "$rc" "$effect"
}

echo "================================================================"
echo " 场景 A：复刻 bug（set -u 下裸 source 引用未绑定变量的 stub）→ 应失败"
echo "================================================================"

# 临时沙箱（不碰真实 ROS / 系统）。
SANDBOX="$(mktemp -d)"
trap 'rm -rf -- "$SANDBOX" 2>/dev/null || true' EXIT
export STUB_SIDE_EFFECT="$SANDBOX/side-effect"

# stub 脚本模拟 /opt/ros/jazzy/setup.bash：先做一个「ROS setup 侧效果」（写文件），
# 然后引用一个未定义的变量（模拟 AMENT_TRACE_SETUP_FILES）。
STUB="$SANDBOX/setup.bash"
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
# 模拟 ROS setup.bash 的侧效果
echo "sourced" > "${STUB_SIDE_EFFECT:?}"
# 模拟 ROS setup.bash 第 8 行引用未定义变量（AMENT_TRACE_SETUP_FILES）
if [ -n "${AMENT_TRACE_SETUP_FILES:-}" ]; then
    : # guarded branch — never reached in stub
fi
EOF

# 注意：上面的 stub 用了 ${VAR:-} 是「守卫过的」写法。为复刻真实 ROS（未守卫），
# 这里再写一个「未守卫引用未绑定变量」的 stub。
cat > "$STUB" <<'EOF'
#!/usr/bin/env bash
# 模拟 /opt/ros/jazzy/setup.bash — 第 8 行裸引用未绑定变量
echo "sourced" > "${STUB_SIDE_EFFECT:?}"
# 模拟 ROS 未守卫引用：直接展开未定义变量（set -u 下致命）
: "${AMENT_TRACE_SETUP_FILES}"
EOF

# 裸 source（RED：期望失败）
unguarded_out="$(run_source_case "unguarded" "$STUB")"
unguarded_rc="${unguarded_out%%$'\t'*}"
unguarded_effect="${unguarded_out##*$'\t'}"
echo "  裸 source（无守卫）        : exit=$unguarded_rc, stub_effect=$unguarded_effect"
# RED：裸 source 在 set -u 下应非零退出
check "裸source引用未绑定变量在set-u下失败: 退出码非0" "nonzero" "$([[ "$unguarded_rc" -ne 0 ]] && echo nonzero || echo zero)"

echo
echo "================================================================"
echo " 场景 B：守卫生效（set +u; source; set -u）→ 应成功"
echo "================================================================"

# 清掉上一次的副作用文件，避免污染判断
rm -f -- "$STUB_SIDE_EFFECT"

# 守卫 source（GREEN：期望成功）
guarded_out="$(run_source_case "guarded" "$STUB")"
guarded_rc="${guarded_out%%$'\t'*}"
guarded_effect="${guarded_out##*$'\t'}"
echo "  守卫 source（set +u/+e）    : exit=$guarded_rc, stub_effect=$guarded_effect"
# GREEN：守卫 source 应退出码 0
check "守卫source(set+u)绕过未绑定变量: 退出码0" "0" "$guarded_rc"
# GREEN：stub 的侧效果应可见（说明 source 真正执行了，不是被跳过）
check "守卫source真正执行(stub侧效果可见)" "1" "$guarded_effect"

echo
echo "================================================================"
echo " 场景 C：chroot-customize.sh 内容守卫（grep 形态检查）"
echo "================================================================"

# 守卫 1：脚本顶部仍保持 set -Eeuo pipefail（没有全局放松）。
if grep -qE '^set +-Eeuo +pipefail' "$CHROOT_SH"; then
    printf "  ok   | chroot-customize.sh 顶部保留 set -Eeuo pipefail\n"
else
    printf "  FAIL | chroot-customize.sh 顶部 set -Eeuo pipefail 被改动（不应全局放松）\n" >&2
    fails=$((fails+1))
fi

# 守卫 2：C1 的 `source /opt/ros/jazzy/setup.bash` 必须被 strict-mode-off 守卫包住。
# 形态：存在一个 source 行，且在其之前（同 C1 块内）有 set +u（放空 nounset）。
# 我们检查「source /opt/ros/jazzy/setup.bash」与「colcon build」附近出现 set +u / eval 守卫。
C1_BLOCK="$(awk '/C1: precompile workspace/,/C1: install\/setup.bash 校验通过/' "$CHROOT_SH")"
if printf '%s\n' "$C1_BLOCK" | grep -qE 'set \+u'; then
    printf "  ok   | C1 块内含 set +u（relax nounset）守卫\n"
else
    printf "  FAIL | C1 块内缺少 set +u 守卫（source/colcon 未被保护）\n" >&2
    fails=$((fails+1))
fi

if printf '%s\n' "$C1_BLOCK" | grep -qE 'source /opt/ros/jazzy/setup\.bash'; then
    printf "  ok   | C1 块内 source /opt/ros/jazzy/setup.bash 存在\n"
else
    printf "  FAIL | C1 块内未见 source /opt/ros/jazzy/setup.bash\n" >&2
    fails=$((fails+1))
fi

if printf '%s\n' "$C1_BLOCK" | grep -qE 'colcon build'; then
    printf "  ok   | C1 块内 colcon build 存在\n"
else
    printf "  FAIL | C1 块内未见 colcon build\n" >&2
    fails=$((fails+1))
fi

# 守卫 3：C1 块内存在「还原」机制（eval "$_saveset" 或等价），证明 strict mode 被恢复。
if printf '%s\n' "$C1_BLOCK" | grep -qE 'eval "\$_saveset"'; then
    printf "  ok   | C1 块内含 eval \"\$_saveset\"（还原 shell 选项）\n"
else
    printf "  FAIL | C1 块内缺少 eval \"\$_saveset\"（strict mode 未恢复）\n" >&2
    fails=$((fails+1))
fi

# 守卫 4：脚本里没有遗留的、未被守卫的裸 `source /opt/ros/jazzy/setup.bash`
# （即每一处该 source 都应该位于 set +u ... eval "$_saveset" 之间）。
# 我们做粗粒度检查：source /opt/ros/jazzy/setup.bash 出现的次数应 ≤ set +u 出现次数。
src_count="$(grep -cE '^[[:space:]]*source /opt/ros/jazzy/setup\.bash' "$CHROOT_SH" || true)"
relax_count="$(grep -cE '^[[:space:]]*set \+u' "$CHROOT_SH" || true)"
echo "  统计: source /opt/ros/jazzy/setup.bash 行=$src_count, set +u 行=$relax_count"
if [[ "$relax_count" -ge "$src_count" && "$src_count" -ge 1 ]]; then
    printf "  ok   | 每处 source /opt/ros/jazzy/setup.bash 都有 set +u 守卫覆盖（relax>=%d >= src=%d）\n" "$relax_count" "$src_count"
else
    printf "  FAIL | 存在未被守卫的裸 source /opt/ros/jazzy/setup.bash（src=%d, relax=%d）\n" "$src_count" "$relax_count" >&2
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
