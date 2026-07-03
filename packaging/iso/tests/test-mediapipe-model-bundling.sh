#!/usr/bin/env bash
#
# test-mediapipe-model-bundling.sh — 回归测试：build-iso.sh inject_payload() 的
# MediaPipe hand_landmarker.task 模型捆绑逻辑。
#
# 本测试通过 source 真实的 build-iso.sh 并调用 inject_payload() 来验证
# MediaPipe 模型捆绑逻辑，而非使用本地影子函数。
#
# 运行：bash packaging/iso/tests/test-mediapipe-model-bundling.sh
#   不需 root、不需联网、不需真实 MediaPipe 模型。
#

set -Eeuo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUILD_ISO="$(cd "$SCRIPT_DIR/.." && pwd)/build-iso.sh"
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

# ===========================================================================
# Mock 基础设施
# ===========================================================================
setup_mocks() {
    local work_dir="$1"
    local fake_bin="$work_dir/fake_bin"
    mkdir -p "$fake_bin"

    # fake curl：记录调用，可选择成功/失败
    cat > "$fake_bin/curl" << 'CURL_EOF'
#!/usr/bin/env bash
echo "$@" >> "$FAKE_CURL_LOG"
output_file=""
while [[ $# -gt 0 ]]; do
    if [[ "$1" == "-o" && $# -gt 1 ]]; then
        output_file="$2"
        shift 2
    else
        shift
    fi
done
if [[ -n "$output_file" ]]; then
    echo "fake_model_bytes" > "$output_file"
fi
exit "${FAKE_CURL_RC:-0}"
CURL_EOF
    chmod +x "$fake_bin/curl"

    # fake cp：记录调用，实际用 /bin/cp
    cat > "$fake_bin/cp" << 'CP_EOF'
#!/usr/bin/env bash
echo "$@" >> "$FAKE_CP_LOG"
exec /bin/cp "$@"
CP_EOF
    chmod +x "$fake_bin/cp"

    # fake mkdir：记录调用，实际用 /bin/mkdir
    cat > "$fake_bin/mkdir" << 'MKDIR_EOF'
#!/usr/bin/env bash
echo "$@" >> "$FAKE_MKDIR_LOG"
exec /bin/mkdir "$@"
MKDIR_EOF
    chmod +x "$fake_bin/mkdir"

    # fake rsync：no-op，直接成功（inject_payload 末尾依赖 rsync）
    cat > "$fake_bin/rsync" << 'RSYNC_EOF'
#!/usr/bin/env bash
exit 0
RSYNC_EOF
    chmod +x "$fake_bin/rsync"

    export PATH="$fake_bin:$PATH"
}

cleanup_work() {
    rm -rf "$1"
}

# ===========================================================================
# 在隔离的 subshell 中运行 inject_payload（source 真实 build-iso.sh）
# ===========================================================================
run_inject_payload() {
    local work_dir="$1"
    local fake_home="$2"
    local fake_rootfs="$3"

    (
        # 先加载函数定义（去掉末尾的 main "$@" 调用）
        source <(sed '$d' "$BUILD_ISO")

        # 再设置环境变量，避免 build-iso.sh 顶部的 ROOTFS="" / ISODIR=""
        # 等顶层声明覆盖我们的值
        ROOTFS="$fake_rootfs"
        HOME="$fake_home"
        THIS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
        WS="$work_dir/fake_ws"
        mkdir -p "$WS"

        # 调用真实的 inject_payload
        inject_payload
    )
}

# ===========================================================================
# 场景 1：本地已有模型 → 跳过下载，复制到两个目标路径
# ===========================================================================
echo "================================================================"
echo " 场景 1：本地已有模型（不触发下载）"
echo "================================================================"

work1="$(mktemp -d)"
trap 'cleanup_work "$work1"' EXIT

export FAKE_CURL_LOG="$work1/curl.log"
export FAKE_CP_LOG="$work1/cp.log"
export FAKE_MKDIR_LOG="$work1/mkdir.log"
export FAKE_CURL_RC=0

setup_mocks "$work1"

# 在 fake HOME 下创建模型文件
fake_home1="$work1/fake_home"
mkdir -p "$fake_home1/.local/share/mediapipe/tasks"
echo "existing_model_bytes" > "$fake_home1/.local/share/mediapipe/tasks/hand_landmarker.task"

fake_rootfs1="$work1/fake_rootfs"
# inject_payload 还会复制 chroot-customize.sh 到 $ROOTFS/usr/sbin/，
# 预先创建该目录以避免 cp 报错（真实函数未对这两处用 || die，报错不阻断）
mkdir -p "$fake_rootfs1/usr/sbin"

rc1=0
run_inject_payload "$work1" "$fake_home1" "$fake_rootfs1" || rc1=$?

# 验证：curl 未被调用
curl_lines1=0
if [[ -f "$FAKE_CURL_LOG" ]]; then
    curl_lines1=$(wc -l < "$FAKE_CURL_LOG")
fi
check "curl 未被调用（本地已有模型）" "0" "$curl_lines1"

# 验证：cp 日志中包含两个 MediaPipe 目标路径（函数内还有其他 cp，所以不数总数）
if [[ -f "$FAKE_CP_LOG" ]]; then
    cp_log1=$(cat "$FAKE_CP_LOG")
    check "cp 日志含 dst1（RPS 节点路径）" "1" "$([[ "$cp_log1" == *"$fake_rootfs1/root/.local/share/mediapipe/tasks/hand_landmarker.task"* ]] && echo 1 || echo 0)"
    check "cp 日志含 dst2（Tracking 节点路径）" "1" "$([[ "$cp_log1" == *"$fake_rootfs1/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task"* ]] && echo 1 || echo 0)"
fi

# 验证：两个目标文件都被创建
check "dst1 存在" "1" "$([[ -f "$fake_rootfs1/root/.local/share/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"
check "dst2 存在" "1" "$([[ -f "$fake_rootfs1/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"

# 验证：函数返回 0
check "函数返回 0（成功）" "0" "$rc1"

echo
rm -f "$FAKE_CURL_LOG" "$FAKE_CP_LOG" "$FAKE_MKDIR_LOG"

# ===========================================================================
# 场景 2：本地无模型 → 触发 curl 下载，随后复制到两个目标路径
# ===========================================================================
echo "================================================================"
echo " 场景 2：本地无模型（触发下载）"
echo "================================================================"

work2="$(mktemp -d)"
trap 'cleanup_work "$work2"' EXIT

export FAKE_CURL_LOG="$work2/curl.log"
export FAKE_CP_LOG="$work2/cp.log"
export FAKE_MKDIR_LOG="$work2/mkdir.log"
export FAKE_CURL_RC=0

setup_mocks "$work2"

# 不创建 fake_home 下的模型 → 触发下载分支
fake_home2="$work2/fake_home"
fake_rootfs2="$work2/fake_rootfs"
mkdir -p "$fake_rootfs2/usr/sbin"

rc2=0
run_inject_payload "$work2" "$fake_home2" "$fake_rootfs2" || rc2=$?

# 验证：curl 被调用 1 次
curl_lines2=0
if [[ -f "$FAKE_CURL_LOG" ]]; then
    curl_lines2=$(wc -l < "$FAKE_CURL_LOG")
fi
check "curl 被调用 1 次（触发下载）" "1" "$curl_lines2"

# 验证：curl 日志包含正确的 URL
if [[ -f "$FAKE_CURL_LOG" ]]; then
    curl_log=$(cat "$FAKE_CURL_LOG")
    check "curl 日志含 MediaPipe 模型 URL" "1" "$([[ "$curl_log" == *"storage.googleapis.com/mediapipe-models/hand_landmarker"* ]] && echo 1 || echo 0)"
fi

# 验证：下载后模型文件出现在 fake_home
check "下载后模型存在于 HOME" "1" "$([[ -f "$fake_home2/.local/share/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"

# 验证：cp 日志中包含两个 MediaPipe 目标路径
if [[ -f "$FAKE_CP_LOG" ]]; then
    cp_log2=$(cat "$FAKE_CP_LOG")
    check "cp 日志含 dst1（RPS 节点路径）" "1" "$([[ "$cp_log2" == *"$fake_rootfs2/root/.local/share/mediapipe/tasks/hand_landmarker.task"* ]] && echo 1 || echo 0)"
    check "cp 日志含 dst2（Tracking 节点路径）" "1" "$([[ "$cp_log2" == *"$fake_rootfs2/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task"* ]] && echo 1 || echo 0)"
fi

# 验证：两个目标文件都被创建
check "dst1 存在" "1" "$([[ -f "$fake_rootfs2/root/.local/share/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"
check "dst2 存在" "1" "$([[ -f "$fake_rootfs2/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"

# 验证：函数返回 0
check "函数返回 0（下载+复制成功）" "0" "$rc2"

echo
rm -f "$FAKE_CURL_LOG" "$FAKE_CP_LOG" "$FAKE_MKDIR_LOG"

# ===========================================================================
# 场景 3：下载失败 → die 被调用（subshell 非零退出）
# ===========================================================================
echo "================================================================"
echo " 场景 3：下载失败（curl 返回非零）"
echo "================================================================"

work3="$(mktemp -d)"
trap 'cleanup_work "$work3"' EXIT

export FAKE_CURL_LOG="$work3/curl.log"
export FAKE_CP_LOG="$work3/cp.log"
export FAKE_MKDIR_LOG="$work3/mkdir.log"
export FAKE_CURL_RC=1   # curl 模拟失败

setup_mocks "$work3"

fake_home3="$work3/fake_home"
fake_rootfs3="$work3/fake_rootfs"
mkdir -p "$fake_rootfs3/usr/sbin"

rc3=0
run_inject_payload "$work3" "$fake_home3" "$fake_rootfs3" || rc3=$?

# 验证：函数未返回 0（die 被调用，subshell 非零退出）
check "函数未返回 0（die 被调用）" "nonzero" "$([[ "$rc3" -ne 0 ]] && echo nonzero || echo zero)"

# 验证：curl 被调用（尝试了下载）
curl_lines3=0
if [[ -f "$FAKE_CURL_LOG" ]]; then
    curl_lines3=$(wc -l < "$FAKE_CURL_LOG")
fi
check "curl 被调用 1 次（尝试下载）" "1" "$curl_lines3"

# 验证：目标文件不存在（复制不会执行）
check "dst1 不存在（下载失败后不复制）" "0" "$([[ -f "$fake_rootfs3/root/.local/share/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"
check "dst2 不存在（下载失败后不复制）" "0" "$([[ -f "$fake_rootfs3/opt/ros/humble/lib/python3.10/site-packages/mediapipe/tasks/hand_landmarker.task" ]] && echo 1 || echo 0)"

echo

# ===========================================================================
# 结果
# ===========================================================================
if [[ "$fails" -eq 0 ]]; then
    echo "SELFTEST PASS (0 failures)"
    exit 0
fi
echo "SELFTEST FAIL ($fails failures)" >&2
exit 1
