FROM docker.m.daocloud.io/ros:jazzy-ros-base

# 避免交互式提示
ENV DEBIAN_FRONTEND=noninteractive

# ---- 系统依赖 ----
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3-pip \
    libgl1 \
    libglib2.0-0 \
    libfontconfig1 \
    libxcb-xinerama0 \
    libxcb-cursor0 \
    python3-pyside2.qtcore \
    python3-pyside2.qtgui \
    python3-pyside2.qtwidgets \
    ros-jazzy-robot-state-publisher \
    ros-jazzy-rviz2 \
    ros-jazzy-geometry-msgs \
    fonts-noto-cjk \
    fcitx5 \
    fcitx5-chinese-addons \
    fcitx5-frontend-qt5 \
    dbus \
    dbus-x11 \
    && rm -rf /var/lib/apt/lists/*

# 中文输入法
ENV QT_IM_MODULE=fcitx \
    GTK_IM_MODULE=fcitx \
    XMODIFIERS=@im=fcitx

# ---- Python 依赖 ----
RUN pip3 install --no-cache-dir --break-system-packages \
    mujoco==3.4.0 \
    openai>=1.12.0

# ---- 工作空间 ----
WORKDIR /ws

# 先拷贝依赖包并构建 (利用 Docker 缓存层)
COPY l10_right_hand_essential/ /ws/l10_right_hand_essential/
RUN . /opt/ros/jazzy/setup.sh \
    && colcon build \
        --packages-select \
            linker_hand_description \
            hand_forward_kinematics \
            l10_right_hand_mujoco_sim \
            l10_hand_gateway \
            l10_hand_control_panel \
            l10_right_hand_viz \
            l10_right_hand_driver \
            l10_right_hand_bootstrap \
    && find /ws/install -xtype l -delete

# 再拷贝 LLM 控制包并构建
COPY l10_right_hand_examples/l10_right_hand_llm/ /ws/l10_right_hand_examples/l10_right_hand_llm/
RUN . /opt/ros/jazzy/setup.sh \
    && . /ws/install/setup.sh \
    && colcon build --packages-select l10_right_hand_llm

# 拷贝剩余源码 (如有其他 examples 包)
COPY l10_right_hand_examples/ /ws/l10_right_hand_examples/

# ---- 启动入口 ----
# 仿真模式 (默认)
COPY <<'EOF' /entrypoint.sh
#!/bin/bash
set -e
source /opt/ros/jazzy/setup.bash
source /ws/install/setup.bash
mkdir -p /run/dbus && dbus-daemon --system --nosyslog 2>/dev/null || true
fcitx5 -d 2>/dev/null || true
exec "$@"
EOF
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
CMD ["ros2", "launch", "l10_right_hand_llm", "llm_control.launch.py"]