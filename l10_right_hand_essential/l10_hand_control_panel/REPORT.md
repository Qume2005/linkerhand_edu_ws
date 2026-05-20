# L10 手部 3D 模型交互控件 — 技术文档

## 1. 概述

为 L10 右手控制面板实现了一个基于 MuJoCo 离屏渲染的 3D 手模型交互控件。用户在 3D 模型的指尖处拖拽控制点，实时控制手指弯曲与侧摆。控件位于面板右侧，与左侧的 10 个 DOF 滑块双向同步。

核心代码在 `skeleton_widget.py`（~500 行），主窗口集成在 `control_panel.py`。

---

## 2. 架构

```
ControlPanelWindow
  ├─ 左侧: 10 个 DualSlider (灰色=当前状态, 白色=目标, 0-255 范围)
  └─ 右侧: HandModelWidget
       ├─ MuJoCo model/data (自有实例, 独立于仿真节点)
       ├─ mujoco.Renderer (离屏渲染 640×480)
       ├─ MjvCamera (自由摄像机, azimuth=-135°, elevation=-25°)
       ├─ QTimer 30 FPS 渲染循环
       └─ 5 个控制点 (每个指尖一个)
```

### 2.1 控制点定义

| 控制点 | Geom ID | 对应网格 | DOF | 求解器 |
|--------|---------|---------|-----|-------|
| 拇指尖 | 5 | thumb_distal | 0(弯曲), 1(侧摆), 9(侧旋) | 网格采样 + Jacobian |
| 食指尖 | 9 | index_distal | 2(弯曲), 6(侧摆) | 网格采样 + Jacobian |
| 中指尖 | 12 | middle_distal | 3(弯曲) | 采样 + 黄金分割 |
| 无名指尖 | 16 | ring_distal | 4(弯曲), 7(侧摆) | 网格采样 + Jacobian |
| 小指尖 | 20 | pinky_distal | 5(弯曲), 8(侧摆) | 网格采样 + Jacobian |

> 中指没有侧摆 DOF，所以只有 1 个 DOF，用更高效的采样法。

### 2.2 数据流

```
鼠标拖拽
  ↓
目标屏幕坐标 = 鼠标位置 + grab_offset + 轨迹预测偏移
  ↓
IK 求解 (1-DOF: 采样+黄金分割 / N-DOF: 网格采样+Jacobian)
  ↓
arc[10] (浮点弧度值) ──→ expand_to_20_joints → MuJoCo qpos → mj_forward → 渲染
  ↓
arc_to_range_l10_right → dof_values[10] (0-255 整数)
  ↓
发布到 /cb_right_hand_control_cmd
```

---

## 3. IK 控制算法

### 3.1 问题建模

每个控制点在屏幕上有 2 个自由度 (X, Y)。手指的 DOF 数量决定了问题的维度：

- **1 DOF（中指）**: 指尖在屏幕上只能沿一条 1D 曲线运动。问题：在曲线上找离目标最近的点。
- **2 DOF（食指、无名指、小指）**: 指尖在屏幕上可覆盖一个 2D 区域。问题：在区域中找离目标最近的点。
- **3 DOF（拇指）**: 指尖在屏幕上可覆盖一个 2D 区域（3 个 DOF 映射到 2D 屏幕，有 1 个零空间维度）。问题同上但带冗余。

### 3.2 1-DOF 求解器：采样 + 黄金分割

中指只有 1 个弯曲 DOF，指尖轨迹是屏幕上的一条弧线。直接搜索整条弧线上离鼠标最近的点：

**Phase 1 — 均匀采样 21 点**

在 `[L10_R_MIN[dof], L10_R_MAX[dof]]` 区间均匀取 21 个弧度值，对每个值调用 `mj_forward` + `_project` 得到屏幕坐标，计算与目标的距离，取最小值。

**Phase 2 — 黄金分割精化**

在 Phase 1 最优点的 ±1/20 弧度范围内，用黄金分割法（12 轮）精化到 ~0.01 弧度精度。

```
总调用: 21 (采样) + 24 (黄金分割) ≈ 45 次 mj_forward
```

**为什么不直接用 Jacobian？** Jacobian 是增量方法，从当前位姿出发逐步迭代。在关节限位处 Jacobian 列可能为零或方向反转，导致卡住或跳到反面。采样法穷举整个范围，从根本上避免了这些问题。

### 3.3 N-DOF 求解器 (N≥2)：网格采样 + Jacobian 精化

两阶段策略，结合了全局搜索的鲁棒性和局部优化的精度：

**Phase 1 — 网格采样（全局搜索）**

在每个 DOF 的弧度范围内均匀采样，对组合的笛卡尔积穷举：

| DOF 数 | 每轴采样数 | 总网格点 |
|--------|-----------|---------|
| 2 | 8 | 64 |
| 3 | 4 | 64 |

采样数由 `int(80 ** (1/n))` 自动计算，总点数控制在 ~64。

对每个网格点：设置 qpos → `mj_forward` → 投影到屏幕 → 计算距离 → 取最小值。

**Phase 2 — Jacobian 精化（局部优化）**

从 Phase 1 找到的全局最优点出发，迭代 10 轮阻尼最小二乘 Jacobian：

1. 投影当前控制点到屏幕，计算误差 `dp = target - current`
2. 数值差分计算 Jacobian `J`（2×N 矩阵）：
   - 对每个 DOF，扰动 ±0.01 弧度，计算屏幕位移
   - 正向扰动被 clamp 时自动反向扰动
3. 阻尼最小二乘求解：`dq = J^T (JJ^T + λ²I)^{-1} dp`
4. 自适应阻尼：`λ = max(1.0, 5.0 / (|J| + 0.01))`，Jacobian 小时加大阻尼防止步长爆炸
5. 步长钳制：每步最多移动该 DOF 弧度范围的 20%
6. 更新弧度值并 clamp 到关节限位

```
总调用: 64 (网格) + ~40 (Jacobian) ≈ 104 次 mj_forward
```

**为什么需要 Phase 1？** 纯 Jacobian 迭代从当前位姿出发，只能到达局部最优。如果当前位姿在一个错误的收敛域（例如手指在 DOF=0 处卡住），Jacobian 无法跳到正确解。网格采样保证找到全局最优的收敛域。

### 3.4 轨迹预测

每次鼠标移动时，用指数移动平均 (EMA, α=0.5) 维护一个平滑速度向量：

```python
velocity = 0.5 * raw_displacement + 0.5 * velocity
predicted_target = mouse_position + velocity * 1.0
```

IK 求解器的目标是预测位置而非实际鼠标位置，让手指"提前"走向拖拽方向。

---

## 4. 关键实现细节

### 4.1 摄像机投影必须匹配 MuJoCo 约定

**坑：** 最初使用 `cam_pos = lookat + dist * forward`（加号），但 MuJoCo 的约定是 `headpos = lookat - dist * forward`（减号）。这导致摄像机被放在 lookat 的错误一侧，投影结果水平镜像。

MuJoCo 的摄像机坐标系（来自 `engine_vis_visualize.c`）：

```
forward = (cos(e)*cos(a), cos(e)*sin(a), sin(e))
headpos = lookat - distance * forward
right   = (sin(a), -cos(a), 0)
up      = (-sin(e)*cos(a), -sin(e)*sin(a), cos(e))
```

投影函数使用相同的公式计算 `cam_pos`，然后用 `lookAt` 风格的投影计算屏幕坐标。

### 4.2 Geom 位置 vs Body 位置

**坑：** MuJoCo 的 `data.xpos[body_id]` 是 body 的质心位置，`data.geom_xpos[geom_id]` 是 geom（网格）的位置。指尖 mesh 偏离 body 质心很多（手指末端的指尖 mesh 在 body 下方），所以必须用 `geom_xpos` 而非 `xpos`。

验证方法：在 XML 中数 geom 出现顺序确定 geom_id：
- geom 5 = thumb_distal（指尖网格，在 thumb_distal body 内）
- geom 9 = index_distal（指尖网格）
- geom 12 = middle_distal（指尖网格）
- geom 16 = ring_distal（指尖网格）
- geom 20 = pinky_distal（指尖网格）

### 4.3 DOF 反转映射

8/10 个 DOF 是反转的（`L10_R_DIRECT == -1`）：

| DOF | 名称 | MIN (rad) | MAX (rad) | DOF=0 → arc | DOF=255 → arc |
|-----|------|-----------|-----------|-------------|---------------|
| 0 | 拇指弯曲 | 0 | 0.5146 | **0.5146 (MAX)** | **0 (MIN)** |
| 1 | 拇指侧摆 | 0 | 1.43 | 1.43 | 0 |
| 2 | 食指弯曲 | 0 | 1.3607 | 1.3607 | 0 |
| 3 | 中指弯曲 | 0 | 1.3607 | 1.3607 | 0 |
| 4 | 无名指弯曲 | 0 | 1.3607 | 1.3607 | 0 |
| 5 | 小指弯曲 | 0 | 1.3607 | 1.3607 | 0 |
| 6 | 食指侧摆 | 0 | 0.21 | **0 (MIN)** | **0.21 (MAX)** |
| 7 | 无名指侧摆 | 0 | 0.21 | **0 (MIN)** | **0.21 (MAX)** |
| 8 | 小指侧摆 | 0 | 0.34 | **0 (MIN)** | **0.34 (MAX)** |
| 9 | 拇指侧旋 | 0 | 1.01 | 1.01 | 0 |

DOF 6、7、8（侧摆）和 9（侧旋）是正向的，其余 6 个弯曲 DOF 是反向的。这意味着 DOF=0（"握拳"）对应大部分关节的最大弯曲角度。

IK 在**弧度空间**求解，通过 `range_to_arc_l10_right` / `arc_to_range_l10_right` 与 DOF 空间转换，无需关心反转方向。

### 4.4 拖拽期间浮点精度 (`_drag_arc`)

**坑：** DOF 值是 0-255 整数。IK 求解器产生浮点弧度值，经 `arc_to_range_l10_right` 转为 0-255 后再 `int()` 取整。如果求解器产生的变化对应不到 1 个 DOF 单位，取整后变化为零。下一次求解从取整后的值出发，重复同样的问题——**永远卡住**。

解决方案：拖拽期间用 `_drag_arc`（float list[10]）保存弧度值。每次鼠标移动时，IK 从 `_drag_arc` 出发，结果也写回 `_drag_arc`。只有发布给手部和同步到滑块时才转换为整数。渲染也优先使用 `_drag_arc`（`_sync_mujoco` 检查 `_drag_arc is not None`）。

### 4.5 Jacobian 关节限位处理

当弧度值在 `L10_R_MAX` 时，正向扰动 +ε 被 clamp 到相同值，Jacobian 列为零。此时自动反向扰动 -ε：

```python
clamped = max(MIN, min(MAX, arc[dof] + eps))
if abs(clamped - arc[dof]) < 1e-9:       # 正向被吃掉
    clamped = max(MIN, min(MAX, arc[dof] - eps))  # 反向
```

Jacobian 值用 `delta_screen / actual_eps` 计算，`actual_eps` 可正可负，但结果始终是正确的偏导数。

### 4.6 自适应阻尼防止步长爆炸

当 Jacobian 很小时（DOF 对屏幕位置影响微弱），标准阻尼最小二乘的步长 `dq = J^T(JJT+λ²I)^{-1}dp` 会变得极大，一步跳到关节范围的另一端。

自适应阻尼公式：`λ = max(1.0, 5.0 / (|J| + 0.01))`

- |J| 正常（~5-10 pixels/rad）时：`5.0 / 5 ≈ 1.0`，使用 λ=1.0
- |J| 很小（~0.1 pixels/rad）时：`5.0 / 0.1 = 50`，使用 λ=50，大幅抑制步长

配合步长钳制（每步 ≤ 20% 弧度范围），彻底消除过冲。

### 4.7 Grab Offset

点击控制点时记录 `_drag_offset = cp_screen - mouse_pos`。拖拽过程中，IK 目标 = 鼠标位置 + offset。这样控制点不会跳到鼠标位置，而是以点击时的相对偏移跟随。

---

## 5. 摄像机控制

- **右键拖拽**: 轴锁定旋转（仅水平或仅竖直方向），修改 azimuth/elevation
- **滚轮**: 缩放 distance
- 旋转方向取反（`azimuth -= dx * 0.3`），匹配 MuJoCo 的 "拖右 → 场景右移" 惯例

---

## 6. 性能

| 手指 | 方法 | mj_forward 调用 | 预计耗时 |
|------|------|----------------|---------|
| 中指 (1-DOF) | 采样+黄金分割 | ~45 | ~0.5ms |
| 食指/无名指/小指 (2-DOF) | 8×8网格+Jacobian | ~104 | ~1ms |
| 拇指 (3-DOF) | 4×4×4网格+Jacobian | ~104 | ~1ms |

60Hz 鼠标事件下，最坏情况 ~6240 次 mj_forward/秒。每次 ~0.01-0.02ms，总开销 ~60-125ms/秒，不阻塞 Qt 事件循环。

---

## 7. 依赖

- MuJoCo Python ≥ 3.4.0（离屏渲染 + 运动学计算）
- PySide2（Qt GUI）
- ROS2 Jazzy（rclpy, sensor_msgs/JointState）
- hand_forward_kinematics（workspace 内部包，提供 FK 映射）

---

## 8. 开发过程中踩过的坑

### 8.1 投影镜像 — 摄像机位置符号错误

**现象：** 控制点位置与渲染的手指不重合，四指顺序反了。

**原因：** `_project` 中用了 `lookat + dist * forward`（+），MuJoCo 用 `lookat - dist * forward`（-）。摄像机被放在了 lookat 的对面，导致投影水平翻转。

**定位过程：** 对比 MuJoCo 源码 `engine_vis_visualize.c` 中的 `mjv_cameraFrame` 函数，发现公式不一致。

### 8.2 Geom vs Body 位置偏差

**现象：** 四指控制点位置偏移严重，不在指尖而在指根附近。

**原因：** 使用 `data.xpos[body_id]`（body 质心）而非 `data.geom_xpos[geom_id]`（网格位置）。指尖 mesh 偏离其所属 body 的质心很多。

### 8.3 整数量化导致拖不动

**现象：** DOF 到达 0 或 255 后再也拖不动。

**原因：** IK 求解器产生浮点弧度变化，经 `int()` 取整后丢失。在限位附近变化量小，取整后为零，下一帧从同样的整数出发，死循环。

**修复：** 引入 `_drag_arc` 在拖拽期间保持浮点精度。

### 8.4 Jacobian 步长爆炸

**现象：** 拖动时手指突然跳到完全相反的位置。

**原因：** 当 Jacobian 很小时（DOF 对屏幕位置影响微弱），阻尼最小二乘步长 `dq ∝ dp/|J|` 巨大，一步跳过整个关节范围。

**修复：** 自适应阻尼 + 步长钳制 + 最终改为网格采样避免依赖 Jacobian 的全局收敛性。

### 8.5 旋转方向反了

**现象：** 右键向右拖，场景向左转。

**原因：** MuJoCo azimuth 增加方向与直觉相反。`azimuth += dx` 应改为 `azimuth -= dx`。

### 8.6 纯 Jacobian 在关节限位处卡住

**现象：** 手指到 0 或 255 后无法拖回。

**原因：** Jacobian 是增量方法，从当前点出发。在限位处，扰动被 clamp 导致 Jacobian 列为零或方向反转，无法找到正确方向。

**修复：** 对 1-DOF 用采样法（穷举全范围），对 N-DOF 用网格采样找全局最优点再 Jacobian 精化。

---

## 9. 文件清单

| 文件 | 说明 |
|------|------|
| `l10_hand_control_panel/skeleton_widget.py` | 3D 交互控件核心 (~500 行) |
| `l10_hand_control_panel/control_panel.py` | 主窗口，双面板布局 |
| `l10_hand_control_panel/urdf/linker_hand_l10_right/` | MuJoCo XML + 26 STL 网格 |
| `hand_forward_kinematics/kinematics.py` | FK 引擎 |
