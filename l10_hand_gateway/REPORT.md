# L10 手部网关节点 — 技术文档

## 1. 概述

`l10_hand_gateway` 是 L10 右手控制系统的中间件层，位于前端面板 (`l10_hand_control_panel`) 和后端仿真/硬件 (`l10_right_hand_mujoco_sim` / SDK) 之间，提供控制 topic 反向代理和状态 topic 代理服务。

网关的职责：
1. 统一接收多种格式的控制命令（DOF、骨架四元数、控制点位置、控制点差分），转换为 DOF 命令后转发后端
2. 从后端读取当前手部状态，计算派生数据（骨架、控制点），统一广播给所有前端
3. 管理相机状态（投影面法向量 + 距离）的广播与接收

核心代码在 `gateway_node.py`（网关节点，~230 行）和 `ik_solver.py`（IK 求解器，~280 行）。

---

## 2. 架构

```
外部控制源 / l10_hand_control_panel (前端)
       │
       │ /l10_gateway/cmd/dof          (10 DOF 0-255)
       │ /l10_gateway/cmd/skeleton     (21 Pose 四元数)
       │ /l10_gateway/cmd/control_points (5 指尖位置)
       │ /l10_gateway/cmd/control_points_diff (5 指尖差分)
       │ /l10_gateway/cmd/camera       (法向量 + 距离)
       ▼
┌──────────────────────────────┐
│     l10_hand_gateway         │
│                              │
│  ┌────────────────────────┐  │
│  │ 命令转换层             │  │
│  │  DOF → 直接传递        │  │
│  │  骨架 → 逆 FK → DOF   │  │
│  │  控制点 → IK → DOF     │  │
│  │  CP差分 → CP+当前→IK   │  │
│  └────────────────────────┘  │
│              │               │
│              ▼               │
│  ┌────────────────────────┐  │
│  │ 状态管理               │  │
│  │  _current_dof ← 后端   │  │
│  │  _target_dof  ← 命令   │  │
│  └────────────────────────┘  │
│       │            │         │
│       ▼            ▼         │
│   FK引擎(纯Python)          │
│   current/*      target/*    │
│       │            │         │
└───────┼────────────┼─────────┘
        │            │
        │ 广播 7 个话题:
        │  /l10_gateway/current/dof
        │  /l10_gateway/current/skeleton
        │  /l10_gateway/current/control_points
        │  /l10_gateway/target/dof
        │  /l10_gateway/target/skeleton
        │  /l10_gateway/target/control_points
        │  /l10_gateway/camera
        ▼
前端面板 / 其他订阅者
```

后端接口：
- 订阅 `/cb_right_hand_state` (JointState, 10 DOF 0-255) → 更新 `_current_dof`
- 发布 `/cb_right_hand_control_cmd` (JointState, 10 DOF 0-255) ← 命令转发

---

## 3. 话题设计

### 3.1 广播话题（网关 → 前端/外部）

| Topic | 消息类型 | 数据描述 |
|-------|---------|---------|
| `/l10_gateway/camera` | `Float32MultiArray` | `[nx, ny, nz, distance]` 相机投影面法向量 + 距离 |
| `/l10_gateway/current/dof` | `JointState` | 10 DOF 0-255 当前实际值（来自后端反馈） |
| `/l10_gateway/current/skeleton` | `PoseArray` | 21 个 body 的位姿（位置 + 四元数），FK 从 current/dof 计算 |
| `/l10_gateway/current/control_points` | `PoseArray` | 5 个指尖 3D 位置（thumb/index/middle/ring/little body 位置） |
| `/l10_gateway/target/dof` | `JointState` | 10 DOF 0-255 目标值（来自最近一条命令） |
| `/l10_gateway/target/skeleton` | `PoseArray` | 21 个 body 位姿，FK 从 target/dof 计算 |
| `/l10_gateway/target/control_points` | `PoseArray` | 5 个指尖目标位置 |

### 3.2 命令话题（前端/外部 → 网关）

| Topic | 消息类型 | 处理逻辑 |
|-------|---------|---------|
| `/l10_gateway/cmd/dof` | `JointState` | 直接设置 `_target_dof`，FK 广播 target/*，转发后端 |
| `/l10_gateway/cmd/skeleton` | `PoseArray` (21 poses) | 逆 FK 提取关节角 → 弧度 → 0-255 → 同 DOF 命令流程 |
| `/l10_gateway/cmd/control_points` | `PoseArray` (5 poses) | 每指独立 IK 求解 → DOF → 同上 |
| `/l10_gateway/cmd/control_points_diff` | `PoseArray` (5 poses) | 当前控制点 + 差分 → 目标控制点 → IK → DOF |
| `/l10_gateway/cmd/camera` | `Float32MultiArray` | 存储并广播相机状态 |

### 3.3 消息格式约定

**DOF 值** (`JointState`):
- `position`: 10 个 float，范围 0-255
- `header.stamp`: 网关时间戳

**骨架** (`PoseArray`, 21 poses):
- `header.frame_id = "world"`
- 每个 Pose 包含完整位置 (x,y,z) 和四元数方向 (w,x,y,z)
- body 索引 0 = world 原点，1-20 按拇指→食指→中指→无名指→小指排列

**控制点** (`PoseArray`, 5 poses):
- 仅使用 `position` 字段 (x,y,z)
- `orientation` 设为单位四元数 (w=1)
- 顺序: thumb_tip(body 5), index_tip(body 9), middle_tip(body 12), ring_tip(body 16), little_tip(body 20)

**相机** (`Float32MultiArray`):
- `data = [nx, ny, nz, distance]`
- 法向量 `(nx, ny, nz)` 为相机 forward 方向（单位向量）
- `distance` 为相机到 lookat 点的距离

---

## 4. IK 求解器

IK 求解器位于 `ik_solver.py`，使用 `hand_forward_kinematics` 的纯 Python FK 引擎，无 MuJoCo 运行时依赖。

### 4.1 骨架 → DOF（逆 FK）

复用 `body_relative_rotation.py` 的逻辑：

1. 从 21 个全局四元数，计算每个 body 相对于父 body 的局部四元数：`q_rel = q_parent⁻¹ * q_child`
2. 去除静态帧旋转：`q_joint = static_quat⁻¹ * q_rel`
3. 转旋转向量，投影到关节轴，提取单轴角度
4. 20 个关节角度折叠为 10 DOF（取主关节，忽略 mimic 关节）
5. 弧度 → 0-255（考虑 DIRECT 反转方向）

### 4.2 控制点 → DOF（数值 IK）

每个手指独立求解（DOF 之间无耦合）：

| 手指 | 指尖 Body | DOF | 方法 |
|------|----------|-----|------|
| 拇指 | 5 | 0(弯曲), 1(侧摆), 9(侧旋) | 4³ 网格(64点) + 3D Jacobian |
| 食指 | 9 | 2(弯曲), 6(侧摆) | 8² 网格(64点) + 3D Jacobian |
| 中指 | 12 | 3(弯曲) | 21 点采样 + 黄金分割 |
| 无名指 | 16 | 4(弯曲), 7(侧摆) | 8² 网格(64点) + 3D Jacobian |
| 小指 | 20 | 5(弯曲), 8(侧摆) | 8² 网格(64点) + 3D Jacobian |

**求解流程:**

1. 输入的 10 DOF (0-255) 通过 `range_to_arc_l10_right` 转为弧度
2. 每个手指:
   - **网格采样**: 在各 DOF 弧度范围内均匀采样，对组合的笛卡尔积穷举。采样数由 `int(80^(1/n))` 自动计算，总点数控制在 ~64
   - **Jacobian 精化**: 从网格最优解出发，迭代 10 轮阻尼最小二乘
3. 求解后通过 `arc_to_range_l10_right` 转回 0-255

**3D Jacobian IK 与屏幕空间 IK 的区别:**

面板的 IK (`skeleton_widget.py`) 在屏幕空间求解（目标 = 2D 屏幕坐标，Jacobian 是 2×N 矩阵）。网关的 IK 在 3D 世界空间求解（目标 = 3D 坐标，Jacobian 是 3×N 矩阵）。

阻尼最小二乘公式: `dq = Jᵀ (JJᵀ + λ²I)⁻¹ dp`
- `dp`: 3D 位置误差向量
- `J`: 3×N 数值 Jacobian（对每个 DOF 扰动 ±0.01 rad，计算指尖 3D 位移差分）
- `λ = max(1.0, 5.0 / (|J| + 0.01))`: 自适应阻尼
- 步长钳制: 每步 ≤ 20% 弧度范围

**关节限位处理:** 正向扰动被 clamp 到极限时，自动反向扰动。用 `actual_eps` (可正可负) 计算 Jacobian，保证偏导数正确。

### 4.3 控制点差分命令处理

1. 从 `_current_dof` 用 FK 计算当前 5 个指尖位置
2. 目标位置 = 当前位置 + 差分值
3. 对目标位置执行 IK → DOF
4. 按正常 DOF 命令流程处理

---

## 5. 循环防护

网关与面板之间可能形成消息环路。防护机制:

### 5.1 网关侧

- **状态严格分离**: `_current_dof` 仅从 `/cb_right_hand_state` 更新，`_target_dof` 仅从命令回调更新。两者数据来源互不交叉
- **不回发原则**: 网关不在同一个话题上回发收到的消息。收到命令 → 只往 target/* 和后端发布；收到后端状态 → 只往 current/* 发布
- **广播时机**: current/* 仅在收到后端新状态时触发，target/* 仅在收到新命令时触发

### 5.2 面板侧

- **`_syncing` 标志**: 面板收到外部目标状态 (`_apply_target_state`) 时设置 `_syncing=True`，阻止滑块回调重新发布命令
- **用户驱动发布**: 面板只在用户交互事件（滑块拖动、3D 拖拽、预设按钮）中发布命令，绝不在收到消息的回调中发布
- **相机回声检测**: `_camera_echo_guard` 记录面板最近发布的相机状态。收到网关广播后，如果与记录值差异 < 0.001，判定为自回声并忽略

---

## 6. 面板重构要点

`l10_hand_control_panel` 从直接与后端通信改为通过网关通信:

| 改动 | 旧 | 新 |
|------|----|----|
| DOF 命令发布 | `/cb_right_hand_control_cmd` | `/l10_gateway/cmd/dof` |
| 当前状态订阅 | `/cb_right_hand_state` (→灰色指示器) | `/l10_gateway/current/dof` (→灰色指示器) |
| 目标状态订阅 | 无 | `/l10_gateway/target/dof` (→白色指示器, 不发布) |
| 相机状态发布 | 无 | `/l10_gateway/cmd/camera` |
| 相机状态接收 | 无 | `apply_camera_state()` (外部设置) |

**回调拆分:**

旧代码中 `_apply_state` 同时更新灰色指示器。新代码拆分为:
- `_apply_current_state(values)`: 更新灰色指示器（当前位姿），不触发任何发布
- `_apply_target_state(values)`: 更新白色指示器 + 骨架模型（目标位姿），设置 `_syncing=True`，不触发发布

**骨架控件相机回调:**

`skeleton_widget.py` 新增:
- `on_camera_changed = None`: 相机旋转/缩放时计算法向量并调用
- `apply_camera_state(data)`: 外部设置相机，从法向量反推 azimuth/elevation/distance
- `_emit_camera_state()`: 在 `_rotate_camera()` 和 `wheelEvent()` 中调用

---

## 7. 数据流图

```
用户交互 (滑块拖动 / 3D 拖拽 / 预设按钮)
       │
       ▼
l10_hand_control_panel
       │ /l10_gateway/cmd/dof
       ▼
l10_hand_gateway ←── /l10_gateway/cmd/skeleton
       │            /l10_gateway/cmd/control_points
       │            /l10_gateway/cmd/control_points_diff
       │            /l10_gateway/cmd/camera
       │
       ├─ 命令转换 (逆FK / IK / 差分叠加)
       ├─ FK 计算 target skeleton + control_points
       ├─ 广播 target/* (7 话题)
       │
       │ /cb_right_hand_control_cmd
       ▼
l10_right_hand_mujoco_sim (或真实硬件 SDK)
       │
       │ /cb_right_hand_state
       ▼
l10_hand_gateway
       ├─ FK 计算 current skeleton + control_points
       ├─ 广播 current/* (3 话题) + camera
       │
       ▼
l10_hand_control_panel → 更新灰色指示器 + 白色指示器 (不回发)
```

---

## 8. 性能

网关的 FK 计算使用纯 Python 实现（无 MuJoCo），单次 FK 调用 ~0.01ms:

| 操作 | FK 调用次数 | 预计耗时 |
|------|-----------|---------|
| 广播 current/* (状态回调) | 1 | ~0.01ms |
| DOF 命令 → 广播 target/* | 1 | ~0.01ms |
| 骨架命令 → 逆 FK | 1 | ~0.01ms |
| 控制点命令 → IK (5 指) | ~300 (采样) + ~50 (Jacobian) | ~3.5ms |
| 控制点差分 → FK + IK | 1 + ~350 | ~3.5ms |

后端状态以 30Hz 推送时，网关额外开销 ~0.3ms/s，不影响实时性。

---

## 9. 依赖

- ROS2 Jazzy (rclpy, sensor_msgs, std_msgs, geometry_msgs)
- hand_forward_kinematics (workspace 内部包，纯 Python FK 引擎 + DOF 映射)
- numpy (数组运算)

---

## 10. 文件清单

| 文件 | 说明 |
|------|------|
| `l10_hand_gateway/gateway_node.py` | 网关主节点 (~230 行) |
| `l10_hand_gateway/ik_solver.py` | IK 求解器 + 逆 FK (~280 行) |
| `l10_hand_control_panel/control_panel.py` | 面板主窗口 (重构为网关前端) |
| `l10_hand_control_panel/skeleton_widget.py` | 3D 交互控件 (添加相机回调) |