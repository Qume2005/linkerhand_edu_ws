# LinkerHand L10 灵巧手教育版工作空间

ROS 2 Jazzy 工作空间，用于控制 LinkerHand L10 10 自由度灵巧手（右手）。支持 MuJoCo 物理仿真、CAN 总线真机控制、RViz2 可视化、摄像头手部追踪、以及 LLM 自然语言手势控制。

## 系统架构

```
用户交互层
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ 控制面板 (GUI)        │  │ LLM 对话控制          │  │ 手部追踪 (摄像头)     │
│ PySide2 双色滑块      │  │ 自然语言 → 手势        │  │ MediaPipe → DOF       │
└──────────┬───────────┘  └──────────┬───────────┘  └──────────┬───────────┘
           │                         │                          │
           └─────────────────────────┼──────────────────────────┘
                                     │ /l10_gateway/cmd/*
                           ┌─────────▼──────────┐
                           │  l10_hand_gateway   │
                           │  命令代理 + FK/IK    │
                           │  多格式命令 → DOF     │
                           │                     │
                           │  处理管道:           │
                           │  速度映射 → 样条轨迹  │
                           │  → 碰撞防护 → 触觉   │
                           └─────────┬──────────┘
                                     │ /cb_right_hand_control_cmd
                  ┌──────────────────┴──────────────────┐
                  │                                      │
        ┌─────────▼─────────┐                ┌───────────▼──────────┐
        │ MuJoCo 仿真后端    │                │ CAN 真机驱动          │
        │ (开发/测试)        │                │ (实际硬件)            │
        └───────────────────┘                └──────────────────────┘
```

**核心设计:** 仿真后端和真机驱动发布完全相同的 topic，上层代码无需修改即可切换。

## 依赖安装

以下命令基于 **Ubuntu 24.04 LTS**。

### 1. ROS 2 Jazzy

```bash
# 设置 locale
sudo apt update && sudo apt install -y locales
sudo locale-gen en_US en_US.UTF-8
sudo update-locale LC_ALL=en_US.UTF-8 LANG=en_US.UTF-8
export LANG=en_US.UTF-8

# 添加 ROS 2 apt 源
sudo apt install -y software-properties-common
sudo add-apt-repository -y universe
sudo apt update && sudo apt install -y curl
sudo curl -sSL https://raw.githubusercontent.com/ros/rosdistro/master/ros.key \
  -o /usr/share/keyrings/ros-archive-keyring.gpg
echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/ros-archive-keyring.gpg] \
  http://packages.ros.org/ros2/ubuntu $(. /etc/os-release && echo $UBUNTU_CODENAME) main" \
  | sudo tee /etc/apt/sources.list.d/ros2.list > /dev/null

# 安装 ROS 2 Jazzy
sudo apt update
sudo apt install -y ros-jazzy-ros-base

# 验证
source /opt/ros/jazzy/setup.bash
ros2 --version
```

### 2. 系统依赖

```bash
# ROS 2 额外包（RViz2 可视化、robot_state_publisher、消息类型）
sudo apt install -y \
  ros-jazzy-rviz2 \
  ros-jazzy-robot-state-publisher \
  ros-jazzy-geometry-msgs

# GUI 框架（PySide2）
sudo apt install -y \
  python3-pyside2.qtcore \
  python3-pyside2.qtgui \
  python3-pyside2.qtwidgets

# 构建工具
sudo apt install -y python3-pip python3-colcon-common-extensions
```

### 3. Python 依赖

```bash
# 核心依赖（仿真/控制必需）
pip3 install --break-system-packages \
  mujoco==3.4.0 \
  numpy \
  python-can

# 可选：LLM 自然语言控制
pip3 install --break-system-packages \
  openai

# 可选：摄像头手部追踪
pip3 install --break-system-packages \
  mediapipe \
  opencv-python
```

### 4. CAN 总线（仅真机模式需要）

```bash
# 安装 SocketCAN 工具
sudo apt install -y can-utils
```

## 快速开始

### 1. 克隆工作空间

```bash
git clone <repo-url> linkerhand_edu_ws
cd linkerhand_edu_ws
```

### 2. 构建

```bash
# 全量构建
colcon build

# 或仅构建核心包
colcon build --packages-select \
  linker_hand_description hand_forward_kinematics \
  l10_right_hand_mujoco_sim l10_hand_gateway \
  l10_hand_control_panel l10_right_hand_viz \
  l10_right_hand_driver l10_right_hand_bootstrap
```

> **构建顺序:** `linker_hand_description` → `hand_forward_kinematics` → 其余包

### 3. 加载环境

```bash
source install/setup.bash
```

### 4. 启动

```bash
# 仿真模式（MuJoCo + GUI + RViz2）
ros2 launch l10_right_hand_bootstrap sim.launch.py

# 真机模式（CAN 驱动 + GUI + RViz2）
sudo ip link set can0 up type can bitrate 1000000 && ip link show can0  # 配置 CAN 接口（1Mbps 波特率）
ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can0 is_touch:=true topic_hz:=60

# LLM 自然语言控制（含仿真启动）
ros2 launch l10_right_hand_llm llm_control.launch.py

# 手部追踪（含仿真启动）
ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py
```

## 目录结构

```
linkerhand_edu_ws/
├── l10_right_hand_essential/     # 核心包（8 个，运行必需）
│   ├── linker_hand_description/  #   URDF/STL/MuJoCo XML 模型资产
│   ├── hand_forward_kinematics/  #   纯 Python 正运动学/逆运动学库
│   ├── l10_right_hand_mujoco_sim/#   MuJoCo 仿真后端
│   ├── l10_right_hand_driver/    #   CAN 总线真机驱动
│   ├── l10_hand_gateway/         #   命令反向代理 + FK/IK 网关
│   ├── l10_hand_control_panel/   #   PySide2 GUI 控制面板
│   ├── l10_right_hand_viz/       #   RViz2 可视化
│   └── l10_right_hand_bootstrap/ #   分时启动 launch 文件
├── l10_right_hand_examples/      # 应用示例（2 个，可选）
│   ├── l10_right_hand_llm/       #   LLM 自然语言手势控制
│   └── l10_right_hand_tracking/  #   摄像头手部追踪
├── Dockerfile                    # 完整容器化环境
├── CLAUDE.md                     # Claude Code 开发参考
└── README.md                     # 本文件
```

## Docker 快速开始

```bash
# 构建镜像
docker build -t linkerhand-edu .

# 仿真模式（默认启动 LLM 控制）
xhost +local:
docker run -it --rm \
  --net=host \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  linkerhand-edu

# 真机模式（需要 CAN 设备访问权限）
docker run -it --rm \
  --net=host --privileged \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  --device=/dev/can0 \
  linkerhand-edu \
  ros2 launch l10_right_hand_llm llm_control_real.launch.py
```

容器内置 fcitx5 中文拼音输入法，启动时自动运行。

> Docker 下 MuJoCo 渲染可能需要 NVIDIA GPU 直通（`--gpus all`，需安装 nvidia-container-toolkit）或软件渲染（`-e LIBGL_ALWAYS_SOFTWARE=1`）。

## DOF 参考表

L10 右手有 10 个自由度，值范围 0-255：

| 索引 | 名称 | 0 = | 255 = |
|------|------|-----|-------|
| 0 | thumb_bend (拇指弯曲) | 弯曲 | 伸直 |
| 1 | thumb_lateral (拇指侧摆) | 贴掌心 | 外展 |
| 2 | index_bend (食指弯曲) | 弯曲 | 伸直 |
| 3 | middle_bend (中指弯曲) | 弯曲 | 伸直 |
| 4 | ring_bend (无名指弯曲) | 弯曲 | 伸直 |
| 5 | little_bend (小指弯曲) | 弯曲 | 伸直 |
| 6 | index_lateral (食指侧摆) | 并拢 | 张开 |
| 7 | ring_lateral (无名指侧摆) | 并拢 | 张开 |
| 8 | little_lateral (小指侧摆) | 并拢 | 张开 |
| 9 | thumb_rotation (拇指旋转) | 向掌心 | 向外 |

CAN ID（右手）: `0x27`。默认 CAN 端口: `can0`。

## 详细文档

- [核心包文档](l10_right_hand_essential/README.md) — 8 个核心包的功能介绍、依赖关系、使用场景
- [应用示例文档](l10_right_hand_examples/README.md) — LLM 控制和手部追踪的使用方法
- 各软件包内部的 `README.md` — 技术细节、算法原理、踩坑记录
