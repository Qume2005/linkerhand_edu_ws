# l10_right_hand_viz

L10 右手可视化节点 —— 将网关 DOF 状态转换为 RViz2 可渲染的关节角度。

## 概述

`l10_right_hand_viz` 是手部可视化管道的核心组件，负责将网关广播的 10 DOF 值
转换为 RViz2 可以理解的 20 关节角度格式。配合 `robot_state_publisher` 和
RViz2，实现带网格模型的实时手部可视化。

## 可视化管道

```
网关 DOF (10 值, 0-255)
       │
       ▼
  HandVizNode._dof_cb()
       │
       ├─ range_to_arc_l10_right()     DOF (0-255) → 弧度值 (10 个)
       ├─ expand_to_20_joints()        10 弧度 → 20 关节弧度 (含 mimic 关节)
       │
       ▼
  /joint_states (JointState, 20 关节)
       │
       ▼
  robot_state_publisher
       │  读取 URDF + /joint_states
       ▼
  TF 变换 (world → base_link → ... → 各指尖)
       │
       ▼
  RViz2 渲染带网格的手部模型
```

## hand_viz.launch.py 包含的 4 个节点

| 节点 | 包 | 功能 |
|------|-----|------|
| `static_transform_publisher` | tf2_ros | 发布 world → base_link 静态变换 |
| `robot_state_publisher` | robot_state_publisher | 读取 URDF，订阅 /joint_states，发布 TF |
| `hand_viz_node` | l10_right_hand_viz | DOF → 20 关节转换 |
| `rviz2` | rviz2 | 3D 可视化渲染 (使用 hand_viz.rviz 配置) |

### 节点启动顺序

launch 文件同时启动 4 个节点，不使用 TimerAction 延迟。这是因为:
- `robot_state_publisher` 可以在收到第一条 `/joint_states` 之前空闲等待
- `hand_viz_node` 订阅的 `/l10_gateway/current/dof` 由网关提供，网关在 bootstrap 的更早阶段就已启动
- RViz2 启动后立即显示配置文件中定义的显示项

## Joint Name Mapping (JOINT_NAMES 常量)

`hand_viz_node.py` 中定义了 20 个 MuJoCo 关节名，按 qpos 索引顺序排列:

```
索引  关节名              对应手指
────  ──────────────────  ────────
0-4   thumb_joint0-4      拇指 (5 个关节)
5-8   index_joint0-3      食指 (4 个关节)
9-11  middle_joint0-2     中指 (3 个关节)
12-15 ring_joint0-3       无名指 (4 个关节)
16-19 little_joint0-3     小指 (4 个关节)
```

这些名称与 URDF 文件中的关节名完全一致，确保 `robot_state_publisher` 能正确匹配。

## 配置文件

- `config/hand_viz.rviz`: RViz2 配置文件，定义了显示项 (网格模型、TF 坐标轴等)
- URDF 模型由 `linker_hand_description` 包提供

## 依赖说明

| 依赖 | 用途 |
|------|------|
| `hand_forward_kinematics` | DOF → 弧度 → 20 关节转换 (range_to_arc_l10_right, expand_to_20_joints) |
| `robot_state_publisher` | URDF → TF 变换发布 |
| `rviz2` | 3D 可视化渲染 |
| `tf2_ros` | world → base_link 静态变换 |
| `linker_hand_description` | URDF 模型文件路径 |
| `sensor_msgs` | JointState 消息类型 |

## 文件清单

```
l10_right_hand_viz/
├── README.md                        # 本文件
├── package.xml                      # ROS 2 包描述
├── setup.py                         # Python 包配置
├── resource/
│   └── l10_right_hand_viz           # ament 资源标记
├── config/
│   └── hand_viz.rviz                # RViz2 配置文件
├── launch/
│   └── hand_viz.launch.py           # 可视化 launch 文件 (4 个节点)
└── l10_right_hand_viz/
    ├── __init__.py
    └── hand_viz_node.py             # 可视化节点 — DOF → 20 关节转换
```
