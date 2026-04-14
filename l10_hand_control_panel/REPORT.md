# L10 手部控制面板 — 3D 模型交互控件开发报告

## 概述

为 L10 右手控制面板的右侧区域实现了基于 MuJoCo 离屏渲染的 3D 手模型交互控件，支持指尖拖拽控制 DOF。用户可以通过拖动 3D 模型上的控制点来控制手指运动，实现所见即所得的手部姿态调节。

---

## 架构

```
ControlPanelWindow (control_panel.py)
  ├─ 左侧: 10 个 DualSlider (0-255 滑块)
  └─ 右侧: HandModelWidget (skeleton_widget.py)
       ├─ MuJoCo model/data (自有实例)
       ├─ mujoco.Renderer (离屏渲染 640×480)
       ├─ MjvCamera (自由摄像机)
       ├─ QTimer 30 FPS 渲染循环
       └─ 6 个控制点 (指尖 + 拇指关节)
```

### 控制点定义

| 控制点 | MuJoCo Geom ID | 控制 DOF | 求解方法 |
|--------|---------------|----------|---------|
| 拇指尖 | 6 (thumb_link5) | DOF0 (拇指弯曲) | 采样 + 黄金分割 |
| 拇指关节 | 2 (thumb_link1) | DOF1 + DOF9 (侧摆+侧旋) | Jacobian 迭代 |
| 食指尖 | 11 (index_link4) | DOF2 (食指弯曲) | 采样 + 黄金分割 |
| 中指尖 | 15 (middle_link3) | DOF3 (中指弯曲) | 采样 + 黄金分割 |
| 无名指尖 | 20 (ring_link4) | DOF4 (无名指弯曲) | 采样 + 黄金分割 |
| 小指尖 | 25 (little_link4) | DOF5 (小指弯曲) | 采样 + 黄金分割 |

### 数据流

```
鼠标拖拽 → 目标屏幕坐标 (+ 轨迹预测)
    ↓
IK 求解 (1-DOF: 采样+黄金分割 / 2-DOF: Jacobian)
    ↓
弧度值 (float, 高精度) → expand_to_20_joints → MuJoCo qpos
    ↓                                        ↓
arc_to_range_l10_right → 0-255 整数      mj_forward → 渲染
    ↓                                        ↓
发布到 /cb_right_hand_control_cmd        QImage → paintEvent
```

---

## 关键设计决策

### 1. 摄像机投影匹配 MuJoCo 约定

MuJoCo 的摄像机位置公式为 `headpos = lookat - distance * forward`（`forward = (cos(e)*cos(a), cos(e)*sin(a), sin(e))`）。手动投影函数必须与渲染器使用完全相同的约定，否则控制点会与渲染图像错位。

### 2. DOF 反转映射

8/10 个 DOF 是反转的 (`L10_R_DIRECT == -1`)：DOF=0 对应弧度最大值（手指弯曲），DOF=255 对应弧度最小值（手指伸直）。IK 在弧度空间求解，不依赖 DOF 方向。

### 3. 拖拽期间浮点精度 (`_drag_arc`)

DOF 值是 0-255 整数。如果每次 IK 求解都经过 `int()` 转换，小变化会被量化吃掉。解决方案：拖拽期间用 `_drag_arc` 保存浮点弧度值作为内部状态，只有发布给手部时才转整数。

### 4. 1-DOF 手指：采样 + 黄金分割

四指各有 1 个 DOF，指尖在屏幕上只能沿一条 1D 曲线运动。直接搜索这条曲线上离鼠标最近的点：
- **Phase 1**: 均匀采样 20 个弧度值，计算屏幕位置，找最小距离
- **Phase 2**: 黄金分割在最近点邻域精化 12 轮（精度 ~0.01 弧度）

优势：穷举整个范围，不可能卡住、不可能跳到反面、鼠标在不可达区域时自动贴到最近边界。

### 5. 2-DOF 拇指：Jacobian 迭代

拇指关节控制 DOF1 + DOF9，2D 搜索空间不适合 1D 搜索。使用阻尼最小二乘 Jacobian 迭代，配合：
- 自适应阻尼（`lam = max(1.0, 5.0 / (|J| + 0.01))`）
- 单步步长钳制（每次最多移动 20% 弧度范围）
- 关节限位反向扰动（正向被 clamp 时自动反向）

### 6. 轨迹预测

用指数移动平均 (EMA, alpha=0.5) 平滑鼠标速度向量，IK 目标 = 鼠标位置 + 速度 × 1.0 步，让手指"提前"走向拖拽方向。

---

## 交互方式

| 操作 | 行为 |
|------|------|
| 左键拖拽控制点 | 控制对应手指 DOF |
| 右键拖拽 | 旋转摄像机（轴锁定：仅水平或仅竖直） |
| 滚轮 | 缩放摄像机距离 |
| 鼠标悬停控制点 | 高亮显示 + 光标变化 |

---

## 文件清单

| 文件 | 说明 |
|------|------|
| `l10_hand_control_panel/skeleton_widget.py` | 3D 模型交互控件 (HandModelWidget) |
| `l10_hand_control_panel/control_panel.py` | 主窗口，双面板布局 |
| `l10_hand_control_panel/urdf/linker_hand_l10_right/` | MuJoCo XML + 26 个 STL 网格 |
| `hand_forward_kinematics/kinematics.py` | FK 引擎 (range_to_arc, expand_to_20_joints) |

## 依赖

- MuJoCo Python ≥ 3.4.0
- PySide2
- ROS2 (rclpy, sensor_msgs)
- hand_forward_kinematics (workspace 内部包)
