# l10_hand_gateway

L10 右手网关节点 —— 控制话题反向代理 + 正运动学计算服务。

> 详见 [技术设计文档](REPORT.md)

## 概述

`l10_hand_gateway` 是整个系统的中枢节点，位于后端（仿真/真机驱动）和前端（控制面板、可视化、应用）之间。它的核心职责是：

1. **反向代理**：后端和前端完全解耦，前端只与网关通信，不直接操作后端
2. **正/逆运动学**：将 DOF 值转换为骨架 (21 个位姿) 和控制点 (5 个指尖位置)，以及反向转换
3. **命令格式转换**：支持 5 种不同格式的命令输入，统一转换为 DOF 后转发给后端

## 网关反向代理模式

```
后端 (仿真/真机)                     前端 (面板/可视化/应用)
┌─────────────┐                   ┌──────────────────┐
│ 发布:        │                   │ 订阅:             │
│ /cb_right_  │  ──► 网关 ──►    │ /l10_gateway/     │
│ hand_state  │      代理         │ current/*         │
│             │                   │                    │
│ 订阅:        │  ◄── 网关 ◄──    │ 发布:             │
│ /cb_right_  │      转发         │ /l10_gateway/     │
│ hand_       │                   │ cmd/*              │
│ control_cmd │                   └──────────────────┘
└─────────────┘
```

网关作为"中间人"，使后端可以在仿真 (MuJoCo) 和真机 (CAN 驱动) 之间无缝切换，而前端代码完全不需要改动。

## 5 种命令格式 → DOF 转换

| 命令话题 | 消息类型 | 转换方式 | 说明 |
|----------|----------|----------|------|
| `/l10_gateway/cmd/dof` | JointState (10) | 直接设置 | 直接指定 10 DOF 值，无转换 |
| `/l10_gateway/cmd/skeleton` | PoseArray (21) | 逆 FK | 21 个全局四元数 → 提取关节旋转 → 折叠为 10 DOF |
| `/l10_gateway/cmd/control_points` | PoseArray (5) | IK | 5 个指尖目标位置 → 网格采样 + Jacobian 精化 → 10 DOF |
| `/l10_gateway/cmd/control_points_diff` | PoseArray (5) | 当前 CP + 差分 → IK | 在当前控制点基础上叠加差分，再做 IK |
| `/l10_gateway/cmd/camera` | Float32MultiArray | 直接存储 | 设置相机距离和法向量，用于 IK 的深度抑制 |
| `/l10_gateway/cmd/camera_diff` | Float32MultiArray | 四元数旋转差分 | 通过四元数旋转更新相机法向量 |

## 广播话题列表 (10 个)

网关持续广播以下话题，供所有前端节点订阅：

| 话题 | 消息类型 | 频率 | 说明 |
|------|----------|------|------|
| `/l10_gateway/current/dof` | JointState (10) | 跟随后端 | 当前实际位姿的 10 DOF 值 (0-255) |
| `/l10_gateway/current/skeleton` | PoseArray (21) | 跟随后端 | 当前位姿的 21 个 body 全局位姿 |
| `/l10_gateway/current/control_points` | PoseArray (5) | 跟随后端 | 当前位姿的 5 个指尖 3D 位置 |
| `/l10_gateway/target/dof` | JointState (10) | 跟随命令 | 目标位姿的 10 DOF 值 |
| `/l10_gateway/target/skeleton` | PoseArray (21) | 跟随命令 | 目标位姿的 21 个 body 全局位姿 |
| `/l10_gateway/target/control_points` | PoseArray (5) | 跟随命令 | 目标位姿的 5 个指尖 3D 位置 |
| `/l10_gateway/camera` | Float32MultiArray (4) | 跟随命令 | 相机状态 [distance, nx, ny, nz] |
| `/l10_gateway/sensor/force` | Float32MultiArray | 跟随后端 | 力传感器数据 (透传) |
| `/l10_gateway/sensor/matrix_touch` | String (JSON) | 跟随后端 | 触觉矩阵数据 (透传) |
| `/l10_gateway/sensor/matrix_touch_mass` | String (JSON) | 跟随后端 | 触觉质量数据 (透传) |

## IK 求解器详解

IK 求解器位于 `ik_solver.py`，用于将 5 个指尖目标位置转换为 10 DOF 值。采用 **两阶段求解** 策略：

### 阶段 1: 网格采样 (全局搜索)

对每个手指的 DOF 空间进行均匀网格采样，确保找到全局最优的起始点：

- **1-DOF 手指** (中指): 21 个均匀采样点
- **2-DOF 手指** (食指、无名指、小指): 每轴 ~9 个采样点，共 ~81 个组合
- **3-DOF 手指** (拇指): 每轴 ~4 个采样点，共 ~64 个组合

采样密度通过 `spa = int(80 ** (1.0 / n))` 自适应计算，保证总采样量约 80 次左右。

### 阶段 2: Jacobian 精化 (局部优化)

在全局最优起点上，使用**阻尼最小二乘法** (Damped Least Squares / Levenberg-Marquardt) 进行迭代精化：

1. 计算数值 Jacobian 矩阵 J (3xN)，表示每个 DOF 变化对指尖位置的影响
2. 求解关节增量: `dq = J^T (JJ^T + λ²I)^{-1} dp`
3. 自适应阻尼因子 λ，Jacobian 范数越大 → 阻尼越大 → 步长越小
4. 单步限幅为关节范围的 20%，防止过冲
5. 最多迭代 10 次

### 相机深度抑制

当提供相机法向量时，IK 误差函数会抑制沿视线方向的深度分量至 20% 权重。这是因为从相机只能获取 2D 投影信息，深度方向不可靠。

## Debounce 机制 (delta < 3 抑制)

网关在将命令转发给后端时，会与上次转发的 DOF 进行比较。如果所有 DOF 的变化量均小于 3，则**跳过转发**。这有效避免了：

- 频繁发布微小变化导致 CAN 总线拥堵
- 仿真后端处理不必要的更新
- IK 求解过程中间状态的抖动

## 相机状态管理

网关维护一个相机状态 `[distance, nx, ny, nz]`，用于 IK 求解时的深度抑制。支持两种更新方式：

1. **直接设置** (`/l10_gateway/cmd/camera`): 完全替换相机状态
2. **差分更新** (`/l10_gateway/cmd/camera_diff`): 通过四元数旋转增量更新法向量

差分更新只传输 4 个浮点数 `[delta_distance, qx, qy, qz]`，其中 `qw` 通过 `sqrt(1 - qx² - qy² - qz²)` 恢复，节省带宽。

## 性能特征

- **单次 IK 求解**: ~2-5ms (1-DOF) / ~5-20ms (3-DOF)，取决于采样密度和 Jacobian 迭代次数
- **FK 计算**: < 1ms (纯 Python，无 MuJoCo 依赖)
- **Debounce**: 每 3 个 DOF 单位过滤一次无效更新
- **内存占用**: 低，不依赖 MuJoCo 运行时

## 依赖说明

| 依赖 | 用途 |
|------|------|
| `hand_forward_kinematics` | FK/IK 计算核心 (纯 Python) |
| `rclpy` | ROS 2 节点框架 |
| `sensor_msgs` | JointState 消息 |
| `geometry_msgs` | PoseArray, Pose 消息 |
| `std_msgs` | Float32MultiArray, String 消息 |
| `numpy` | 线性代数运算 |

## 文件清单

```
l10_hand_gateway/
├── README.md                        # 本文件
├── REPORT.md                        # 技术设计文档
├── package.xml                      # ROS 2 包描述
├── setup.py                         # Python 包配置
├── resource/
│   └── l10_hand_gateway             # ament 资源标记
└── l10_hand_gateway/
    ├── __init__.py
    ├── gateway_node.py              # 网关节点 — 反向代理 + 命令分发
    └── ik_solver.py                 # IK 求解器 — 网格采样 + Jacobian 精化
```
