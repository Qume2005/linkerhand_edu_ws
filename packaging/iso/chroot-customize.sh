#!/usr/bin/env bash
# chroot-customize.sh — LinkerHand Edu ISO rootfs 定制脚本
#
# 在 chroot 内以 root 运行，cwd=/。由 build-iso.sh 注入：
#   /_payload/ws/                          # 工作空间快照（已 exclude build/install/.git/llm_settings.json）
#   /_payload/llm_settings.template.json   # 清理版模板（空 key）
#
# 演进自 packaging/iso/legacy/fastinstall.bash.reference（Cubic 时代 chroot 脚本），
# 新增三项打磨：C1 预编译工作空间、C2 真实 key 零进镜像、C3 CAN 免密 sudo。
set -Eeuo pipefail

# 工作空间快照由 build-iso.sh rsync 注入；真实 llm_settings.json 已被 exclude。
PAYLOAD="/_payload"
WS_DIR="$PAYLOAD/ws"
SKEL="/etc/skel/Desktop"

log() { printf '\n\033[1;34m[chroot-customize]\033[0m %s\n' "$*"; }

#==============================================================================
# A. 迁移自 fastinstall.bash.reference（按原顺序）
#==============================================================================

#--- A1. firstboot-fix-grub.service（去 nomodeset，首启一次性）----------------
log "A1: firstboot-fix-grub.service"
cat > /usr/local/sbin/firstboot-fix-grub.sh << 'EOF'
#!/bin/sh
set -e

GRUB_CONF="/etc/default/grub"
MARK="/var/lib/firstboot/grub-fixed"

[ -f "$MARK" ] && exit 0
[ -f "$GRUB_CONF" ] || exit 0

cp "$GRUB_CONF" "${GRUB_CONF}.bak"

sed -i 's/\bnomodeset\b//g' "$GRUB_CONF"
sed -i 's/vga=[0-9a-fA-FxX]\+//g' "$GRUB_CONF"

update-grub || cp "${GRUB_CONF}.bak" "$GRUB_CONF"

mkdir -p "$(dirname "$MARK")"
: > "$MARK"
EOF
chmod 755 /usr/local/sbin/firstboot-fix-grub.sh
cat > /etc/systemd/system/firstboot-fix-grub.service << 'EOF'
[Unit]
Description=First boot: remove nomodeset and update grub
After=local-fs.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/firstboot-fix-grub.sh

[Install]
WantedBy=multi-user.target
EOF
ln -sf /etc/systemd/system/firstboot-fix-grub.service \
       /etc/systemd/system/multi-user.target.wants/

#--- A2. apt 源换阿里云-------------------------------------------------------
log "A2: switch apt mirror to aliyun"
sed -i 's|http://archive.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources
sed -i 's|http://security.ubuntu.com|https://mirrors.aliyun.com|g' /etc/apt/sources.list.d/ubuntu.sources

#--- A3. 删冗余软件 + autoremove----------------------------------------------
log "A3: remove unnecessary packages"
apt-get update
apt-get remove -y libreoffice-common snapd rhythmbox shotwell remmina
apt-get autoremove -y

#--- A4. 时区 / locale / user-dirs--------------------------------------------
log "A4: timezone + locale + user-dirs"
ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
apt-get install -y locales curl
locale-gen zh_CN zh_CN.UTF-8
update-locale LC_ALL=zh_CN.UTF-8 LANG=zh_CN.UTF-8
export LANG=zh_CN.UTF-8
cat > /etc/xdg/user-dirs.conf << 'EOF'
enabled=False
filename_encoding=UTF-8
EOF

#--- A5. add-apt-repository universe------------------------------------------
log "A5: enable universe"
apt-get install -y software-properties-common
add-apt-repository universe -y

#--- A6. ROS2 apt 源（ros2-apt-source deb）-----------------------------------
log "A6: ROS2 apt source"
export ROS_APT_SOURCE_VERSION="$(curl -s https://api.github.com/repos/ros-infrastructure/ros-apt-source/releases/latest | grep -F "tag_name" | awk -F'"' '{print $4}')"
curl -L -o /tmp/ros2-apt-source.deb "https://github.com/ros-infrastructure/ros-apt-source/releases/download/${ROS_APT_SOURCE_VERSION}/ros2-apt-source_${ROS_APT_SOURCE_VERSION}.$(. /etc/os-release && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME}}")_all.deb"
dpkg -i /tmp/ros2-apt-source.deb

#--- A7. ros-dev-tools + Suites 补 noble-updates/-backports + full-upgrade----
log "A7: ros-dev-tools + full-upgrade"
sed -i 's/^Suites:.*/Suites: noble noble-updates noble-backports/' /etc/apt/sources.list.d/ubuntu.sources
apt-get clean
apt-get update
apt-get full-upgrade -y
apt-get install -y ros-dev-tools

#--- A8. ros-jazzy-ros-base + .bashrc-----------------------------------------
log "A8: ros-jazzy-ros-base + bashrc"
apt-get install -y ros-jazzy-ros-base
echo '. /opt/ros/jazzy/setup.sh && . ~/Desktop/install/setup.sh' >> /etc/skel/.bashrc

#--- A9. 系统依赖-------------------------------------------------------------
log "A9: system & project dependencies"
apt-get install -y --no-install-recommends \
    python3-pip \
    libgl1 \
    libglib2.0-0 \
    libfontconfig1 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    python3-pyside2.qtcore \
    python3-pyside2.qtgui \
    python3-pyside2.qtwidgets \
    python3-pygame \
    python3-openai \
    ros-jazzy-robot-state-publisher \
    ros-jazzy-rviz2 \
    ros-jazzy-geometry-msgs \
    fonts-noto-cjk \
    fcitx5 \
    fcitx5-chinese-addons \
    fcitx5-frontend-qt5 \
    dbus \
    dbus-x11 \
    can-utils

#--- A10. fcitx5 配置（pinyin，Ctrl+space）-----------------------------------
log "A10: fcitx5 pinyin config"
mkdir -p /root/.config/fcitx5
printf '[Hotkey]\nTrigger=Ctrl+space\n' > /root/.config/fcitx5/config
printf '[Groups/0]\nName=Default\nDefault Layout=us\nDefaultIM=pinyin\n\
[Groups/0/Items/0]\nName=keyboard-us\nLayout=\n\
[Groups/0/Items/1]\nName=pinyin\nLayout=\n' > /root/.config/fcitx5/profile

#--- A11. pip 装运行时依赖----------------------------------------------------
# numpy 锁 1.26.4：Ubuntu 24.04 / ROS Jazzy 的系统 numpy（apt）即 1.26.4，无 pip RECORD，
# pip 无法卸载它 → 任何要求 numpy>=2 的包都会让构建在 chroot 内死于
# "Cannot uninstall numpy, RECORD file not found"。故必须用 numpy 1.x 兼容的包。
# opencv 选 opencv-contrib-python==4.11.0.86（而非 4.13.0.92 的 headless）：
#   - mediapipe==0.10.32 依赖 opencv-contrib-python（非 headless），且不锁版本；
#   - opencv 4.12+ 的 METADATA 硬要 numpy>=2；4.11.0.86 对 py3.12 仅 numpy>=1.26.0（无上界），
#     与系统 numpy 1.26.4 兼容。contrib 是 headless 的超集，单行覆盖 mediapipe 与 cv2，
#     避免「headless + contrib 同时安装 → 争抢 cv2 命名空间」的冲突。
log "A11: pip install mujoco / mediapipe / opencv-contrib-python (numpy 1.26.4-compatible)"
pip3 install --no-cache-dir --break-system-packages \
    -i https://pypi.tuna.tsinghua.edu.cn/simple \
    numpy==1.26.4 \
    mujoco==3.4.0 \
    mediapipe==0.10.32 \
    opencv-contrib-python==4.11.0.86

#==============================================================================
# B. 摆工作空间到 skel（演进 fastinstall 的 mv 段）
#==============================================================================

log "B: stage workspace into /etc/skel/Desktop"
mkdir -p "$SKEL"

# B1. 工作空间三个包（cp -a，显式路径，不用 mv）
cp -a "$WS_DIR/l10_right_hand_essential" "$SKEL/"
cp -a "$WS_DIR/l10_right_hand_examples" "$SKEL/"
cp -a "$WS_DIR/README.md" "$SKEL/"

# B2. 清理版 LLM 配置模板（真实 key 从未进 payload）
#     build-iso.sh 把模板注入 /_payload/llm_settings.template.json；
#     兜底：若 build-iso.sh 没注入但 rootfs 自带，用 /usr/local/share/ 的。
if [ -f "$PAYLOAD/llm_settings.template.json" ]; then
    cp "$PAYLOAD/llm_settings.template.json" "$SKEL/llm_settings.json"
elif [ -f /usr/local/share/llm_settings.template.json ]; then
    cp /usr/local/share/llm_settings.template.json "$SKEL/llm_settings.json"
else
    echo "[chroot-customize] WARN: llm_settings.template.json 不在 /_payload 也不在 /usr/local/share；跳过（首启时需手动补）" >&2
fi

# B3. 安全自检：skel 里的 llm_settings.json 不得含长 key
if [ -f "$SKEL/llm_settings.json" ]; then
    LEAK="$(grep -cE '[A-Za-z0-9]{20,}' "$SKEL/llm_settings.json" || true)"
    if [ "$LEAK" -ne 0 ]; then
        echo "[chroot-customize] FATAL: $SKEL/llm_settings.json 含 ≥20 字符的可疑 token（命中 $LEAK 处），疑似真实 key 泄露，中止。" >&2
        exit 1
    fi
fi

# B4. 桌面启动器（与 fastinstall 一致的 7 个，去掉 `colcon build && ` 前缀）
log "B4: desktop launchers (precompiled, no colcon build prefix)"
echo "source install/setup.bash && ros2 launch l10_right_hand_bootstrap sim.launch.py" \
    > "$SKEL/上位机（仿真）.sh"
chmod 755 "$SKEL/上位机（仿真）.sh"

echo "source install/setup.bash \
      && sudo ip link set can0 up type can bitrate 1000000 \
      && ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can0 is_touch:=true topic_hz:=60" \
    > "$SKEL/上位机（真机）.sh"
chmod 755 "$SKEL/上位机（真机）.sh"

echo "source install/setup.bash && ros2 launch l10_right_hand_llm llm_control.launch.py" \
    > "$SKEL/LLM控制（仿真）.sh"
chmod 755 "$SKEL/LLM控制（仿真）.sh"

echo "source install/setup.bash \
      && sudo ip link set can0 up type can bitrate 1000000 \
      && ros2 launch l10_right_hand_llm llm_control_real.launch.py" \
    > "$SKEL/LLM控制（真机）.sh"
chmod 755 "$SKEL/LLM控制（真机）.sh"

echo "source install/setup.bash && ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py" \
    > "$SKEL/人手跟随（仿真）.sh"
chmod 755 "$SKEL/人手跟随（仿真）.sh"

echo "source install/setup.bash && ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_sim.launch.py" \
    > "$SKEL/石头剪刀布（仿真）.sh"
chmod 755 "$SKEL/石头剪刀布（仿真）.sh"

echo "source install/setup.bash \
      && sudo ip link set can0 up type can bitrate 1000000 \
      && ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_real.launch.py" \
    > "$SKEL/石头剪刀布（真机）.sh"
chmod 755 "$SKEL/石头剪刀布（真机）.sh"

#==============================================================================
# C. 三项打磨（演进，fastinstall 没有）
#==============================================================================

#--- C1. 预编译工作空间（默认 copy 安装模式，不用 symlink-install，绝对 symlink 在 live 系统里会断）---
log "C1: precompile workspace (copy mode, Release)"
# ROS setup.bash / colcon 不是 set -u-safe 的第三方脚本（如 setup.bash 第 8 行裸引用
# 未定义的 AMENT_TRACE_SETUP_FILES）。本脚本顶部 set -Eeuo pipefail（含 -u/nounset）下
# 裸 source/调用它们会触发「未绑定的变量」致命错误 → set -e 中止整脚本。
# 标准 idiom：保存 shell 选项 → 放松 nounset/errexit → source + colcon → 还原。
# 严禁全局关闭 strict mode；仅在这一处第三方脚本边界临时放松。
_saveset="$(set +o)"
set +u +e
# shellcheck disable=SC1091
source /opt/ros/jazzy/setup.bash
cd "$SKEL"
colcon build --cmake-args -DCMAKE_BUILD_TYPE=Release
colcon_rc=$?
eval "$_saveset"
# colcon 即使在放松 -e 期间失败也要被发现：非零即中止（strict mode 已恢复）。
if [ "$colcon_rc" -ne 0 ]; then
    echo "[chroot-customize] FATAL: colcon build 失败 (exit=$colcon_rc)。" >&2
    exit 1
fi

# 校验预编译产物存在
if [ ! -f "$SKEL/install/setup.bash" ]; then
    echo "[chroot-customize] FATAL: colcon build 完成但 $SKEL/install/setup.bash 不存在，预编译失败。" >&2
    exit 1
fi
log "C1: install/setup.bash 校验通过"

# C2. key 已在 B2 处理（只放空 key 模板，真实 key 从未进 payload）。

#--- C3. CAN 免密 sudo（live 用户运行时由 casper 创建，用 %sudo 组命中）------
log "C3: CAN sudoers (passwordless for %sudo)"
cat > /etc/sudoers.d/linkerhand-can << 'EOF'
%sudo ALL=(root) NOPASSWD: /sbin/ip link set can0 up type can bitrate 1000000
%sudo ALL=(root) NOPASSWD: /sbin/ip link set can0 down
EOF
chmod 440 /etc/sudoers.d/linkerhand-can

# visudo 语法校验，失败即中止（chroot 内必须有 visudo，由 sudo 包提供）
if ! visudo -cf /etc/sudoers.d/linkerhand-can; then
    echo "[chroot-customize] FATAL: sudoers 片段语法校验失败，中止。" >&2
    exit 1
fi
log "C3: sudoers 校验通过"

#==============================================================================
# D. 收尾
#==============================================================================
log "D: cleanup"
apt-get clean
rm -rf /var/lib/apt/lists/* \
       /var/cache/apt/archives/*.deb \
       /_payload

log "done."
