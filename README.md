# LinkerHand L10 灵巧手教育版工作空间

ROS 2 Jazzy 工作空间，用于控制 LinkerHand L10 10 自由度灵巧手（右手）。支持 MuJoCo 物理仿真、CAN 总线真机控制、RViz2 可视化、摄像头手部追踪、LLM 自然语言手势控制，以及自定义手势管理和手势序列自动播放。

## 系统架构

```
用户交互层
┌──────────────────────┐  ┌──────────────────────┐  ┌──────────────────────┐
│ 控制面板 (GUI)        │  │ LLM 对话控制          │  │ 手部追踪 (摄像头)     │
│ PySide2 双色滑块      │  │ 自然语言 → 手势        │  │ MediaPipe → DOF       │
│ 自定义手势 CRUD       │  │                      │  │                      │
│ 手势序列 CRUD + 播放  │  │                      │  │                      │
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
  numpy==1.26.4 \
  python-can

# 可选：LLM 自然语言控制
pip3 install --break-system-packages \
  openai

# 可选：摄像头手部追踪
pip3 install --break-system-packages \
  mediapipe \
  opencv-python

# 可选：石头剪刀布游戏
pip3 install --break-system-packages \
  pygame edge-tts
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

# 石头剪刀布游戏（含仿真启动）
ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_sim.launch.py

# 石头剪刀布游戏（真机）
ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_real.launch.py
```

> **摄像头自动扫描：** 手部追踪和石头剪刀布默认自动扫描可用摄像头（0-9），无需手动指定 `camera_id`。如有多个摄像头，可通过 `camera_id` 参数指定设备号，如 `camera_id:=2`。

## 目录结构

```
linkerhand_edu_ws/
├── l10_right_hand_essential/     # 核心包（8 个，运行必需）
│   ├── linker_hand_description/  #   URDF/STL/MuJoCo XML 模型资产
│   ├── hand_forward_kinematics/  #   纯 Python 正运动学/逆运动学库
│   ├── l10_right_hand_mujoco_sim/#   MuJoCo 仿真后端
│   ├── l10_right_hand_driver/    #   CAN 总线真机驱动
│   ├── l10_hand_gateway/         #   命令反向代理 + FK/IK 网关
│   ├── l10_hand_control_panel/   #   PySide2 GUI 控制面板（手势管理 + 序列播放）
│   ├── l10_right_hand_viz/       #   RViz2 可视化
│   └── l10_right_hand_bootstrap/ #   分时启动 launch 文件
├── l10_right_hand_examples/      # 应用示例（3 个，可选）
│   ├── l10_right_hand_llm/       #   LLM 自然语言手势控制
│   ├── l10_right_hand_tracking/  #   摄像头手部追踪
│   └── l10_right_hand_rock_paper_scissors/  #   石头剪刀布互动游戏
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

## ROS2 通信接口

系统采用 **发布/订阅** 模式，所有通信通过 topic 完成，无 service/action。

### Topic 总览

#### 后端 → Gateway（状态上报）

| Topic | 类型 | 说明 |
|------|------|------|
| `/cb_right_hand_state` | `sensor_msgs/JointState` | 10 DOF 当前位置（0-255），来自 CAN 驱动或 MuJoCo 仿真 |
| `/cb_right_hand_info` | `std_msgs/String` | 手部信息 JSON（版本、速度、故障、温度、扭矩） |
| `/cb_right_hand_force` | `std_msgs/Float32MultiArray` | 单点触觉压力（4 组 x 5 指），仅 `is_touch=true` 时发布 |
| `/cb_right_hand_matrix_touch` | `std_msgs/String` | 矩阵触觉 JSON（每指 12x6 网格 + 时间戳），仅 `touch_type > 1` 时发布 |
| `/cb_right_hand_matrix_touch_pc` | `sensor_msgs/PointCloud2` | 矩阵触觉 PointCloud2 格式 |
| `/cb_right_hand_matrix_touch_mass` | `std_msgs/String` | 每指触觉质量求和 JSON |

#### Gateway 广播（状态镜像）

| Topic | 类型 | 说明 |
|------|------|------|
| `/l10_gateway/current/dof` | `sensor_msgs/JointState` | 10 DOF 当前值（0-255），来自后端原始状态 |
| `/l10_gateway/target/dof` | `sensor_msgs/JointState` | 10 DOF 目标值（0-255），经过速度限制/碰撞防护/触觉防护后的值 |
| `/l10_gateway/current/skeleton` | `geometry_msgs/PoseArray` | 当前 FK 骨架（21 个 body 位姿） |
| `/l10_gateway/target/skeleton` | `geometry_msgs/PoseArray` | 目标 FK 骨架 |
| `/l10_gateway/current/control_points` | `geometry_msgs/PoseArray` | 当前 5 指尖控制点 |
| `/l10_gateway/target/control_points` | `geometry_msgs/PoseArray` | 目标 5 指尖控制点 |
| `/l10_gateway/camera` | `std_msgs/Float32MultiArray` | 相机状态 `[distance, nx, ny, nz]` |
| `/l10_gateway/speed_limit` | `std_msgs/Float32` | 速度限制百分比（0-100，100=无限制） |
| `/l10_gateway/sensor/force` | `std_msgs/Float32MultiArray` | 触觉压力（透传） |
| `/l10_gateway/sensor/matrix_touch` | `std_msgs/String` | 矩阵触觉 JSON（透传） |
| `/l10_gateway/sensor/matrix_touch_mass` | `std_msgs/String` | 触觉质量 JSON（透传） |

#### 上层 → Gateway（命令输入）

| Topic | 类型 | 说明 |
|------|------|------|
| `/l10_gateway/cmd/dof` | `sensor_msgs/JointState` | **直接 DOF 命令**：10 个关节值（0-255），由控制面板/LLM/RPS 发布 |
| `/l10_gateway/cmd/skeleton` | `geometry_msgs/PoseArray` | 骨架命令：21 个位姿 → 逆 FK → DOF |
| `/l10_gateway/cmd/control_points` | `geometry_msgs/PoseArray` | 控制点命令：5 个指尖 3D 位置 → IK → DOF（手部追踪使用） |
| `/l10_gateway/cmd/control_points_diff` | `geometry_msgs/PoseArray` | 差分控制点：当前 CP + 偏移 → IK → DOF |
| `/l10_gateway/cmd/camera` | `std_msgs/Float32MultiArray` | 相机命令：`[distance, nx, ny, nz]` |
| `/l10_gateway/cmd/camera_diff` | `std_msgs/Float32MultiArray` | 差分相机：`[delta_distance, qx, qy, qz]` |
| `/l10_gateway/cmd/speed_limit` | `std_msgs/Float32` | 速度限制：0-100 百分比 |

#### Gateway → 后端（控制转发）

| Topic | 类型 | 说明 |
|------|------|------|
| `/cb_right_hand_control_cmd` | `sensor_msgs/JointState` | 10 DOF 控制命令，转发给 CAN 驱动或 MuJoCo 仿真 |
| `/cb_hand_setting_cmd` | `std_msgs/String` | 设置命令 JSON（`set_speed`、`set_max_torque_limits`、`clear_faults`、`set_electric_current`） |

### 消息格式

#### `sensor_msgs/JointState`（DOF 命令/状态）

```text
header:   标准 ROS2 消息头（frame_id, stamp）
name:     关节名称列表（DOF 命令可省略，按顺序映射）
position: float64[] — 10 个 DOF 值（0.0-255.0）
velocity: float64[] — 关节速度（通常省略）
effort:   float64[] — 关节力矩（通常省略）
```

**10 DOF 顺序**（与 `DOF_ORDER` 一致）：

| 索引 | 名称 | 说明 |
|------|------|------|
| 0 | thumb_bend | 拇指弯曲 |
| 1 | thumb_lateral | 拇指侧摆 |
| 2 | index_bend | 食指弯曲 |
| 3 | middle_bend | 中指弯曲 |
| 4 | ring_bend | 无名指弯曲 |
| 5 | little_bend | 小指弯曲 |
| 6 | index_lateral | 食指侧摆 |
| 7 | ring_lateral | 无名指侧摆 |
| 8 | little_lateral | 小指侧摆 |
| 9 | thumb_rotation | 拇指旋转 |

#### `geometry_msgs/PoseArray`（骨架/控制点）

```text
header:   标准 ROS2 消息头
poses:    Pose[] — 每个 Pose 包含：
  position:    Point(x, y, z) — 米制单位，MuJoCo 坐标系
  orientation: Quaternion(x, y, z, w)
```

- **骨架**：21 个 Pose（手腕 + 20 个关节）
- **控制点**：5 个 Pose（拇指/食指/中指/无名指/小指指尖）

#### `std_msgs/Float32MultiArray`（相机/触觉）

```text
data: float32[]
```

- **相机状态**：`[distance, nx, ny, nz]` — 距离 + 掌心法向量
- **触觉压力**：4 组 x 5 指 = 20 个 float32 值

#### `std_msgs/String`（设置/触觉 JSON）

```json
// 设置命令示例：
{"cmd": "set_speed", "value": 100}
{"cmd": "set_max_torque_limits", "values": [100, 100, ...]}
{"cmd": "clear_faults"}
{"cmd": "set_electric_current", "value": 500}

// 矩阵触觉示例：
{"finger": 0, "timestamp": 1234567890, "data": [[0,1,...], ...]}
```

### 命令行操作示例

```bash
# ---- 查看 topic 列表 ----
ros2 topic list

# ---- 查看当前 DOF 状态（实时流） ----
ros2 topic echo /l10_gateway/current/dof

# ---- 查看目标 DOF ----
ros2 topic echo /l10_gateway/target/dof

# ---- 查看 5 指尖控制点 ----
ros2 topic echo /l10_gateway/current/control_points

# ---- 查看速度限制 ----
ros2 topic echo /l10_gateway/speed_limit

# ---- 查看触觉数据 ----
ros2 topic echo /l10_gateway/sensor/force
ros2 topic echo /l10_gateway/sensor/matrix_touch

# ---- 查看 topic 频率 ----
ros2 topic hz /l10_gateway/current/dof

# ---- 查看 topic 信息（类型、发布者、订阅者） ----
ros2 topic info /l10_gateway/cmd/dof

# ---- 查看所有 gateway 相关 topic ----
ros2 topic list | grep l10_gateway

# ---- 发送 DOF 命令（握拳：全部 0） ----
ros2 topic pub /l10_gateway/cmd/dof sensor_msgs/msg/JointState \
  "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: ''}, \
    name: ['thumb_bend','thumb_lateral','index_bend','middle_bend','ring_bend','little_bend','index_lateral','ring_lateral','little_lateral','thumb_rotation'], \
    position: [0,0,0,0,0,0,0,0,0,0], velocity: [], effort: []}"

# ---- 发送 DOF 命令（张开手掌：全部 255） ----
ros2 topic pub /l10_gateway/cmd/dof sensor_msgs/msg/JointState \
  "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: ''}, \
    name: ['thumb_bend','thumb_lateral','index_bend','middle_bend','ring_bend','little_bend','index_lateral','ring_lateral','little_lateral','thumb_rotation'], \
    position: [255,255,255,255,255,255,255,255,255,255], velocity: [], effort: []}"

# ---- 发送 DOF 命令（竖大拇指） ----
ros2 topic pub /l10_gateway/cmd/dof sensor_msgs/msg/JointState \
  "{header: {stamp: {sec: 0, nanosec: 0}, frame_id: ''}, \
    name: ['thumb_bend','thumb_lateral','index_bend','middle_bend','ring_bend','little_bend','index_lateral','ring_lateral','little_lateral','thumb_rotation'], \
    position: [200,220,0,0,0,0,0,0,0,50], velocity: [], effort: []}"

# ---- 设置速度限制（50%） ----
ros2 topic pub /l10_gateway/cmd/speed_limit std_msgs/msg/Float32 "{data: 50.0}"

# ---- 发送设置命令（清故障） ----
ros2 topic pub /cb_hand_setting_cmd std_msgs/msg/String \
  '{data: "{\"cmd\": \"clear_faults\"}"}'

# ---- 查看节点图 ----
ros2 node list
ros2 node info /l10_hand_gateway

# ---- 查看所有节点之间的连接 ----
ros2 node info /l10_hand_gateway  # 显示该节点的 pub/sub
```

> **提示：** `ros2 topic pub` 默认只发一次。持续发送添加 `-r 10` 参数（10Hz）。
> 也可以先用 `--once` 发送一条测试命令观察效果。

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
- [应用示例文档](l10_right_hand_examples/README.md) — LLM 控制、手部追踪和石头剪刀布游戏的使用方法
- [控制面板文档](l10_right_hand_essential/l10_hand_control_panel/README.md) — 自定义手势与序列管理使用指南
- 各软件包内部的 `README.md` — 技术细节、算法原理、踩坑记录
