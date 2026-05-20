# l10_right_hand_mujoco_sim

L10 右手 MuJoCo 物理仿真 ROS2 后端 -- 提供与真实硬件驱动完全相同的 ROS2 话题接口，使下游节点无需区分仿真与实体。

## 功能概述

本包使用 MuJoCo 物理引擎模拟 L10 右手的运动学和触觉响应，是整个系统的**仿真后端**。它与真实硬件驱动包 `l10_right_hand_driver` 发布/订阅完全相同的话题，可直接替换，实现"仿真开发、实体部署"的工作流。

核心能力：

- **关节状态仿真**：接收 0-255 DOF 命令，驱动 MuJoCo 物理引擎，反馈实际关节角度
- **触觉数据仿真**：从 MuJoCo 接触力反算 5 指压力值（单点压力 + 12x6 矩阵 + PointCloud2）
- **手部信息仿真**：模拟 SDK 信息回报（版本号、速度、力矩、温度等静态数据）

## 话题接口

仿真后端与真实驱动的话题接口**完全一致**（接口契约）：

### 发布话题

| 话题 | 消息类型 | 说明 |
|------|---------|------|
| `/cb_right_hand_state` | `sensor_msgs/JointState` | 10 DOF 关节位置 (0-255)，名称按 `L10_FINGER_ORDER` |
| `/cb_right_hand_info` | `std_msgs/String` | 手部信息 JSON（版本、速度、温度、故障等） |
| `/cb_right_hand_force` | `std_msgs/Float32MultiArray` | 5 指压力值（`is_touch=true` 时） |
| `/cb_right_hand_matrix_touch` | `std_msgs/String` | 5 指 12x6 矩阵触觉 JSON |
| `/cb_right_hand_matrix_touch_pc` | `sensor_msgs/PointCloud2` | 矩阵触觉点云格式 |
| `/cb_right_hand_matrix_touch_mass` | `std_msgs/String` | 每指压力总和 JSON |

### 订阅话题

| 话题 | 消息类型 | 说明 |
|------|---------|------|
| `/cb_right_hand_control_cmd` | `sensor_msgs/JointState` | 10 DOF 关节位置命令 (0-255) |
| `/cb_hand_setting_cmd` | `std_msgs/String` | 设置命令 JSON（速度、力矩等） |

## ROS 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `topic_hz` | int | 30 | 状态发布频率 (Hz) |
| `is_touch` | bool | True | 是否仿真触觉传感器数据 |

## 线程架构

```
主线程 (ROS2 spin)                  MuJoCo 仿真线程 (daemon)
┌────────────────────┐              ┌─────────────────────────┐
│  hand_cb()         │              │  while rclpy.ok():       │
│    收到控制命令     │              │    data.ctrl = ctrl_vals │
│    转弧度 -> ctrl   │──shared──>  │    mujoco.mj_step()      │
│                    │   memory     │    publish_joint_states() │
│  hand_setting_cb() │              │    sleep(0.001)          │
│    更新 hand_info  │              └─────────────────────────┘
└────────────────────┘
```

- **主线程**：运行 ROS2 spin，处理 `/cb_right_hand_control_cmd` 和 `/cb_hand_setting_cmd` 回调
- **仿真线程**：独立守护线程，以 1ms 间隔步进 MuJoCo，按 `topic_hz` 频率发布状态
- **线程安全**：`ctrl_values` 通过 numpy 数组原子赋值实现简单同步，无需加锁

## 触觉数据仿真

### fingertip_geom_map 映射逻辑

MuJoCo 模型中每个连杆 (body) 关联若干几何体 (geom)。触觉仿真通过以下步骤建立 geom 到手指的映射：

1. 定义指尖 body 名称：`thumb_distal`, `index_distal`, `middle_distal`, `ring_distal`, `pinky_distal`
2. 遍历模型所有 geom，检查其所属 body 名称
3. 匹配时记录 `geom_id -> finger_idx` 映射到 `finger_geom_map`

### 接触力到压力值的转换

```python
# 遍历所有接触对
for contact in data.contact:
    # 检查接触的 geom 是否属于指尖
    finger_idx = finger_geom_map.get(geom1) or finger_geom_map.get(geom2)

    # 计算法向力
    normal_force = abs(mj_contactForce(...)[0])

    # 累加到该手指的总力
    finger_forces[finger_idx] += normal_force

# 缩放到 0-255 范围（缩放因子 100.0）
force_scaled = min(255.0, force * 100.0)
```

### 矩阵触觉模拟

将单指总力均匀分配到 12x6=72 个网格单元：

```python
per_cell = total_force / 72.0
matrix = [[per_cell] * 6 for _ in range(12)]
```

这是简化的均匀分布模型，真实矩阵传感器的压力分布更复杂。

## 仿真参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `dof_damping` | 0.8 | 全关节阻尼，防止无限振荡 |
| `disableflags` | 1 | 禁用重力，模拟手臂水平放置 |
| 接触力缩放因子 | 100.0 | MuJoCo 力值(N) -> 0-255 压力值 |
| 步进间隔 | 1ms | MuJoCo 步进频率 ~1000Hz |

阻尼 0.8 让手指运动平滑但不过度迟缓；禁用重力避免手掌在无支撑时下坠。接触力缩放因子 100.0 是经验值，使得正常抓取力度映射到约 100-200 的触觉读数。

## Mimic 关节配置

20 个 MuJoCo 关节中，10 个是主关节（直接由 DOF 控制），10 个是 mimic 关节（由主关节角度 * 乘数得到）：

| Mimic 关节 | 主关节 | 乘数 | 说明 |
|-----------|--------|------|------|
| 3 (thumb_mcp) | 2 (thumb_cmc_pitch) | 1.3898 | 拇指 MCP 跟随 CMC pitch |
| 4 (thumb_ip) | 2 (thumb_cmc_pitch) | 1.508 | 拇指 IP 跟随 CMC pitch |
| 7 (index_pip) | 6 (index_mcp_pitch) | 1.3462 | 食指 PIP 跟随 MCP pitch |
| 8 (index_dip) | 6 (index_mcp_pitch) | 0.4616 | 食指 DIP 跟随 MCP pitch |
| 10 (middle_pip) | 9 (middle_mcp_pitch) | 1.3462 | 中指 PIP 跟随 MCP pitch |
| 11 (middle_dip) | 9 (middle_mcp_pitch) | 0.4616 | 中指 DIP 跟随 MCP pitch |
| 14 (ring_pip) | 13 (ring_mcp_pitch) | 1.3462 | 无名指 PIP 跟随 MCP pitch |
| 15 (ring_dip) | 13 (ring_mcp_pitch) | 0.4616 | 无名指 DIP 跟随 MCP pitch |
| 18 (pinky_pip) | 17 (pinky_mcp_pitch) | 1.3462 | 小指 PIP 跟随 MCP pitch |
| 19 (pinky_dip) | 17 (pinky_mcp_pitch) | 0.4616 | 小指 DIP 跟随 MCP pitch |

四指模式一致：PIP = MCP_pitch × 1.3462，DIP = MCP_pitch × 0.4616。拇指 MCP/IP 分别以 1.3898/1.508 跟随 cmc_pitch。

## 构建

```bash
colcon build --packages-select l10_right_hand_mujoco_sim
source install/setup.bash
```

依赖会自动构建：`linker_hand_description` -> `hand_forward_kinematics` -> `l10_right_hand_mujoco_sim`。

## 启动

```bash
# 通过 bootstrap 启动（推荐，会依次启动 backend -> gateway -> viz -> panel）
ros2 launch l10_right_hand_bootstrap sim.launch.py

# 单独启动仿真节点
ros2 run l10_right_hand_mujoco_sim l10_right_mujoco_node

# 自定义参数
ros2 run l10_right_hand_mujoco_sim l10_right_mujoco_node --ros-args \
    -p topic_hz:=50 -p is_touch:=false
```

## 文件清单

| 文件 | 说明 |
|------|------|
| `l10_right_hand_mujoco_sim/mujoco_node.py` | MuJoCo 仿真 ROS2 节点 |
| `l10_right_hand_mujoco_sim/__init__.py` | 包标记文件 |
| `launch/l10_right_mujoco.launch.py` | 节点启动文件 |
| `requirements.txt` | Python 依赖 (mujoco, pyqt5, numpy) |
| `setup.py` | 构建配置 |
| `package.xml` | ROS2 包元数据 |
