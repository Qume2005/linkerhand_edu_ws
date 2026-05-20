# l10_right_hand_driver

L10 右手 CAN 总线硬件驱动 -- 通过 CAN 总线直接驱动真实 LinkerHand L10 灵巧手，发布与 MuJoCo 仿真完全相同的 ROS2 话题接口。

## 功能概述

本包是 L10 右手的**真实硬件驱动后端**，直接通过 CAN 总线与灵巧手硬件通信，提供与仿真后端 `l10_right_hand_mujoco_sim` 完全相同的话题接口。系统中的其他节点（gateway、控制面板、LLM 等）无需关心后端是仿真还是实体。

核心能力：

- **关节位置控制**：通过 CAN 总线发送 10 DOF 位置命令（分两帧：前 6 + 后 4）
- **关节状态读取**：持续接收 CAN 响应，维护 10 DOF 实时位置缓存
- **触觉数据读取**：支持矩阵型 (12x6) 和单点型两种触觉传感器
- **手部信息查询**：速度、力矩、温度、故障码、固件版本、序列号

## CAN 协议基础

### 通信参数

| 参数 | 值 | 说明 |
|------|-----|------|
| CAN 仲裁 ID | `0x27` | 右手固定 ID |
| 波特率 | 1 Mbps | CAN 总线速率 |
| 协议栈 | python-can | Linux 使用 SocketCAN |
| 帧间隔 | 2ms | 最小帧间隔，防止总线拥塞 |

### 帧格式

```
数据帧: [帧类型标识(1字节)] + [数据(0~7字节)]
仲裁 ID: 0x27 (右手)
```

帧的第一个字节标识帧用途（帧类型标识），后续字节为有效载荷。

### FrameProperty 帧类型枚举

| 枚举值 | 十六进制 | 说明 |
|--------|---------|------|
| `JOINT_POSITION_RCO` | 0x01 | 关节位置（前 6 指） |
| `MAX_PRESS_RCO` | 0x02 | 力矩限制（前 5 指） |
| `MAX_PRESS_RCO2` | 0x03 | 力矩限制（后 5 指） |
| `JOINT_POSITION2_RCO` | 0x04 | 关节位置（后 4 指） |
| `JOINT_SPEED` | 0x05 | 关节速度（前 5 指） |
| `JOINT_SPEED2` | 0x06 | 关节速度（后 5 指） |
| `REQUEST_DATA_RETURN` | 0x09 | 请求状态回报 |
| `HAND_NORMAL_FORCE` | 0x20 | 法向力数据 |
| `HAND_TANGENTIAL_FORCE` | 0x21 | 切向力数据 |
| `HAND_TANGENTIAL_FORCE_DIR` | 0x22 | 切向力方向 |
| `HAND_APPROACH_INC` | 0x23 | 趋近增量 |
| `MOTOR_TEMPERATURE_1` | 0x33 | 电机温度（前 5 指） |
| `MOTOR_TEMPERATURE_2` | 0x34 | 电机温度（后 5 指） |
| 矩阵触觉 | 0xb0-0xb5 | 拇指~小指矩阵数据 |
| 版本查询 | 0x64 / 0xC2 | 固件版本 |
| 序列号查询 | 0xC0 | 硬件序列号 |

### 关节位置发送协议

L10 的 10 DOF 位置命令分为两帧发送：

```
帧 1 (0x04): [0x04] + DOF[6:10]  (后 4 指: 小指弯曲, 无名指侧摆, 小指侧摆, 拇指侧旋)
帧 2 (0x01): [0x01] + DOF[0:6]   (前 6 指: 拇指弯曲~食指侧摆)
```

注意：先发后 4 指再发前 6 指，这是硬件协议的时序要求。

## 线程架构

```
ROS2 主线程 (spin)            CAN 接收线程 (daemon)         CAN 发送 (同步)
┌───────────────────┐        ┌────────────────────┐
│ _hand_control_cb  │        │ receive_response() │
│   缓存命令到       │        │   持续 recv()      │
│   _pending_pose   │        │   -> process_resp() │
│                   │        │   按帧类型更新缓存  │
│ _run() (定时器)   │        │   x01, x04, xb0~5  │
│  1. 发送命令       │──────> │                    │
│     set_joint_pos │  CAN   └────────────────────┘
│  2. 读状态缓存     │  总线
│     x01 + x04     │<──────
│  3. 发布信息       │
│  4. 读触觉数据     │
└───────────────────┘
```

- **ROS2 主线程**：定时器回调 `_run()` 以 `topic_hz` 频率执行 4 步循环
- **CAN 接收线程**：守护线程持续接收 CAN 响应，按帧类型更新内部状态缓存
- **线程安全**：`_pending_pose` 通过 `threading.Lock` 保护；CAN 接收线程的状态缓存通过 `is_cmd` 标志避免发送和查询冲突

## 触觉传感器类型检测

驱动启动时自动检测触觉传感器类型：

```python
# 发送探测帧，检查响应数据长度
touch_type = hand.get_touch_type()

# touch_type == 2: 矩阵传感器（每指 12x6 网格）
# touch_type == 1: 单点传感器（每指 1 个压力值）
# touch_type == -1: 无传感器
```

根据检测到的类型，初始化不同的发布者：

- **矩阵型 (touch_type > 1)**：发布 `/cb_right_hand_matrix_touch`、`_pc`、`_mass` 三个话题
- **单点型 (touch_type == 1)**：仅发布 `/cb_right_hand_force`
- **无传感器 (touch_type == -1)**：不发布任何触觉话题

## 默认初始位姿

节点启动时将手部移动到以下默认位姿（张开、自然展开状态）：

```
[255, 200, 255, 255, 255, 255, 180, 180, 180, 41]
  |    |    |    |    |    |    |    |    |    |
  |    |    |    |    |    |    |    |    |    +-- 拇指侧旋: 略外翻
  |    |    |    |    |    |    |    |    +-- 小指侧摆: 展开
  |    |    |    |    |    |    |    +-- 无名指侧摆: 展开
  |    |    |    |    |    |    +-- 食指侧摆: 展开
  |    |    |    |    |    +-- 小指弯曲: 伸直
  |    |    |    |    +-- 无名指弯曲: 伸直
  |    |    |    +-- 中指弯曲: 伸直
  |    |    +-- 食指弯曲: 伸直
  |    +-- 拇指侧摆: 接近展开
  +-- 拇指弯曲: 伸直
```

初始化顺序：速度 -> 力矩 -> 位置，每个命令后等待 100ms 确保硬件响应。

## ROS 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `can_port` | string | `"can0"` | CAN 接口名称 |
| `is_touch` | bool | True | 是否启用触觉传感器 |
| `topic_hz` | int | 30 | 主循环频率 (Hz) |

## 话题接口

### 发布话题

| 话题 | 消息类型 | 说明 |
|------|---------|------|
| `/cb_right_hand_state` | `sensor_msgs/JointState` | 10 DOF 关节位置 (0-255) |
| `/cb_right_hand_info` | `std_msgs/String` | 手部信息 JSON |
| `/cb_right_hand_force` | `Float32MultiArray` | 单点压力 (仅单点传感器) |
| `/cb_right_hand_matrix_touch` | `std_msgs/String` | 矩阵触觉 JSON (仅矩阵传感器) |
| `/cb_right_hand_matrix_touch_pc` | `sensor_msgs/PointCloud2` | 矩阵触觉点云 (仅矩阵传感器) |
| `/cb_right_hand_matrix_touch_mass` | `std_msgs/String` | 每指压力总和 JSON (仅矩阵传感器) |

### 订阅话题

| 话题 | 消息类型 | 说明 |
|------|---------|------|
| `/cb_right_hand_control_cmd` | `sensor_msgs/JointState` | 10 DOF 位置命令 (0-255) |
| `/cb_hand_setting_cmd` | `std_msgs/String` | 设置命令 JSON |

### 设置命令格式

```json
{"setting_cmd": "set_speed", "params": {"speed": [200, 250, 250, 250, 250, 250, 250, 250, 250, 250]}}
{"setting_cmd": "set_max_torque_limits", "params": {"torque": [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]}}
{"setting_cmd": "clear_faults"}
{"setting_cmd": "set_electric_current"}
```

## setting.yaml 配置文件

`linkerhand/setting.yaml` 是 CAN 通信的配置文件：

| 配置项 | 说明 |
|--------|------|
| `VERSION` | 配置文件版本号 |
| `LEFT_HAND.EXISTS` | 是否连接左手 |
| `LEFT_HAND.TOUCH` | 左手是否有触觉传感器 |
| `LEFT_HAND.CAN` | 左手 CAN 端口 |
| `LEFT_HAND.JOINT` | 左手型号 |
| `RIGHT_HAND.*` | 右手对应配置 |
| `PASSWORD` | sudo 密码（用于 `ip link` 配置 CAN 接口） |

当前驱动硬编码为右手 CAN ID `0x27`，YAML 中的 `RIGHT_HAND` 配置未使用。

## OpenCan 接口管理

`open_can.py` 负责 CAN 接口的自动配置：

1. 通过 `ip link show can0` 检查接口状态
2. 若未 UP，执行 `sudo ip link set can0 up type can bitrate 1000000`
3. sudo 密码从 `setting.yaml` 的 `PASSWORD` 字段读取
4. 通过 `/sys/class/net/can0/operstate` 检查接口运行状态

## 故障排除

### CAN not found

```
致命错误：所有 CAN 接口连接尝试均失败
```

**原因**：USB-CAN 适配器未连接或驱动未加载。

**解决**：
1. 检查 USB-CAN 适配器是否已插入
2. 运行 `ip link show can0` 确认接口存在
3. 运行 `sudo ip link set can0 up type can bitrate 1000000` 手动启动
4. 检查 `dmesg | tail` 查看内核日志

### 权限被拒

```
sudo: a password is required
```

**原因**：`setting.yaml` 中的 `PASSWORD` 不正确。

**解决**：
1. 编辑 `l10_right_hand_driver/linkerhand/setting.yaml`
2. 将 `PASSWORD` 字段修改为当前用户的 sudo 密码
3. 或将用户添加到 dialout 组：`sudo usermod -aG dialout $USER`

### 设备忙

```
CanError: Cannot open CAN device
```

**原因**：CAN 接口被其他进程占用。

**解决**：
1. 运行 `sudo fuser /dev/net/tun` 查看占用进程
2. 关闭占用进程
3. 或重启 CAN 接口：`sudo ip link set can0 down && sudo ip link set can0 up type can bitrate 1000000`

## 构建

```bash
colcon build --packages-select l10_right_hand_driver
source install/setup.bash
```

## 启动

```bash
# 通过 bootstrap 启动（推荐）
ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can0 is_touch:=true topic_hz:=30

# 单独启动驱动
ros2 run l10_right_hand_driver l10_right_hand_driver --ros-args \
    -p can_port:=can0 -p is_touch:=true -p topic_hz:=30
```

## 文件清单

| 文件 | 说明 |
|------|------|
| `l10_right_hand_driver/hand_driver_node.py` | ROS2 驱动节点主文件 |
| `l10_right_hand_driver/__init__.py` | 包标记文件 |
| `l10_right_hand_driver/linkerhand/l10_can.py` | CAN 总线通信驱动核心类 |
| `l10_right_hand_driver/linkerhand/open_can.py` | CAN 接口管理工具 |
| `l10_right_hand_driver/linkerhand/color_msg.py` | 终端彩色输出工具 |
| `l10_right_hand_driver/linkerhand/load_write_yaml.py` | YAML 配置文件加载器 |
| `l10_right_hand_driver/linkerhand/setting.yaml` | CAN 通信配置文件 |
| `setup.py` | 构建配置 |
| `package.xml` | ROS2 包元数据 |
