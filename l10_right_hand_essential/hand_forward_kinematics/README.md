# hand_forward_kinematics

L10 右手纯 Python 正向运动学库 -- 将 10 自由度 (DOF) 关节值映射为 21 个骨骼体的三维空间位姿。

## 功能概述

本包实现了 LinkerHand L10 右手从关节空间到笛卡尔空间的完整正向运动学 (Forward Kinematics, FK) 求解。核心特点：

- **零 MuJoCo 运行时依赖**：所有运动链数据从 MuJoCo XML 模型中硬编码提取，FK 计算只需 numpy
- **完整的 DOF 转换管线**：0-255 整数 <-> 弧度值 <-> 20 关节展开 <-> 21 body 位姿
- **Mimic 关节支持**：自动处理 20 MuJoCo 关节与 10 DOF 之间的耦合展开/折叠
- **ROS2 节点可选**：可独立作为库使用，也可通过 `hand_fk_node` 作为 ROS2 节点运行

本包与 `l10_hand_gateway/ik_solver.py` 构成 FK/IK 对：
- FK（本包）：DOF -> 骨架位姿，用于可视化
- IK（gateway）：骨架位姿 -> DOF，用于手势控制

## 核心概念

### 20 关节 MuJoCo 模型 vs 10-DOF 映射

MuJoCo 模型为了逼真模拟手指运动，使用了 20 个关节。但 L10 硬件只有 10 个电机（10 DOF）。二者之间的映射通过 `L10_JOINT_MAP` 字典实现：

```
MuJoCo 关节 0   -> DOF 9  (拇指侧旋)
MuJoCo 关节 1   -> DOF 1  (拇指侧摆)
MuJoCo 关节 2,3,4 -> DOF 0  (拇指弯曲，其中关节3是主关节)
MuJoCo 关节 5   -> DOF 6  (食指侧摆)
MuJoCo 关节 6,7,8 -> DOF 2  (食指弯曲，其中关节7是主关节)
... 以此类推
```

### Mimic 关节（耦合关节）

L10 的每根手指只有 1 个弯曲电机，但人手手指有 2-3 个弯曲关节。MuJoCo 模型通过 **mimic 关节** 模拟这一力学耦合：非主关节的角度 = 主关节角度 * 固定乘数。

```
食指 (DOF 2):
  MuJoCo 关节 6 (近端指间关节) = 关节 7 * 0.87
  MuJoCo 关节 7 (掌指关节)     = DOF 2 值 (主关节)
  MuJoCo 关节 8 (远端指间关节) = 关节 7 * 0.59
```

乘数含义：近端关节跟随幅度大 (0.87)，远端跟随幅度小 (0.59)，符合人手运动学规律。

### DOF 值约定与方向反转

DOF 值为 0-255 无符号整数，但 SDK 约定和弧度值方向存在反转：

| DOF | 名称 | 0 = | 255 = | L10_R_DIRECT |
|-----|------|-----|-------|-------------|
| 0 | 拇指弯曲 | 弯曲 | 伸直 | -1 (反向) |
| 1 | 拇指侧摆 | 收拢 | 展开 | -1 (反向) |
| 2 | 食指弯曲 | 弯曲 | 伸直 | -1 (反向) |
| 3 | 中指弯曲 | 弯曲 | 伸直 | -1 (反向) |
| 4 | 无名指弯曲 | 弯曲 | 伸直 | -1 (反向) |
| 5 | 小指弯曲 | 弯曲 | 伸直 | -1 (反向) |
| 6 | 食指侧摆 | 并拢 | 展开 | -1 (反向) |
| 7 | 无名指侧摆 | 并拢 | 展开 | 0 (正向) |
| 8 | 小指侧摆 | 并拢 | 展开 | 0 (正向) |
| 9 | 拇指侧旋 | 朝掌心 | 外翻 | -1 (反向) |

当 `L10_R_DIRECT[i] == -1` 时，`range_to_arc` 函数执行反向映射（255 -> MIN, 0 -> MAX），确保 "255 = 伸直" 的 SDK 约定与 "弧度 0 = 伸直" 的物理约定一致。

## FK 算法原理

### 四元数链式变换

FK 的核心是沿运动链从基座到指尖逐层累积变换：

```
对于运动链中的每个 body：
  1. 取父 body 的全局位姿 (q_parent, p_parent)
  2. 计算当前关节的旋转变换: q_frame = static_quat * axis_angle_quat(axis, angle)
  3. 累积全局四元数: q_global = q_parent * q_frame
  4. 累积全局位置: p_global = rotate(q_parent, local_pos) + p_parent
```

其中 `static_quat` 是 MuJoCo XML 中定义的关节零位朝向，`axis` 是关节旋转轴，`angle` 是当前关节角度。

### `_CHAIN_NP` 预计算

模块加载时，将 `KINEMATIC_CHAIN` 列表中的 Python 列表转为 numpy 数组（`_CHAIN_NP`）。由于 FK 在 30Hz+ 频率下调用，这一预计算避免了每次调用时重复创建 numpy 数组，减少 GC 压力。

## 模块结构

### `kinematics.py` -- 核心算法库

#### 四元数数学

| 函数 | 说明 |
|------|------|
| `quat_mul(q1, q2)` | Hamilton 四元数乘法 |
| `quat_rotate(q, v)` | 用四元数旋转向量：q*(0,v)*q^{-1} |
| `axis_angle_to_quat(axis, angle)` | 轴角转四元数 |

#### DOF 转换

| 函数 | 说明 |
|------|------|
| `_scale(val, a, b, c, d)` | 线性区间映射 |
| `range_to_arc_l10_right(position_range)` | 0-255 -> 弧度（含方向反转） |
| `arc_to_range_l10_right(arc_values)` | 弧度 -> 0-255（逆运算） |

#### 关节映射

| 函数 | 说明 |
|------|------|
| `collapse_20_to_10(joint_angles_20)` | 20 MuJoCo 关节 -> 10 DOF（取主关节） |
| `expand_to_20_joints(arc_10)` | 10 DOF -> 20 MuJoCo 关节（展开 mimic） |

#### FK 求解

| 函数 | 说明 |
|------|------|
| `compute_fk(joint_angles_20)` | 20 关节角度 -> 21 body 全局位姿 (位置+四元数) |

### `fk_node.py` -- ROS2 节点

可选的 ROS2 节点 `HandFKNode`，订阅后端状态话题并发布骨骼位姿：

- **订阅**: `/cb_right_hand_state` (JointState, 10 DOF 0-255)
- **发布**: `/skeleton_body_positions` (PoseArray, 21 poses)

4 步管线：
1. 0-255 -> 弧度
2. 10 DOF -> 20 关节 (expand mimic)
3. FK 求解
4. 打包 PoseArray 发布

## 话题接口

### 订阅话题

| 话题 | 类型 | 说明 |
|------|------|------|
| `/cb_right_hand_state` | `sensor_msgs/JointState` | 10 DOF 手部状态 (0-255) |

### 发布话题

| 话题 | 类型 | 说明 |
|------|------|------|
| `/skeleton_body_positions` | `geometry_msgs/PoseArray` | 21 个骨骼体的全局位姿 |

## 依赖

| 依赖 | 用途 |
|------|------|
| `numpy` | 数组运算、四元数计算 |
| `rclpy` | ROS2 节点（仅 fk_node.py 需要） |
| `sensor_msgs` | JointState 消息（仅 fk_node.py 需要） |
| `geometry_msgs` | PoseArray 消息（仅 fk_node.py 需要） |
| `linker_hand_description` | 运动链数据硬编码，**无运行时依赖** |

`kinematics.py` 可完全独立于 ROS 使用。

## 文件清单

| 文件 | 说明 |
|------|------|
| `hand_forward_kinematics/kinematics.py` | 核心算法：四元数数学、DOF 转换、FK 求解器 |
| `hand_forward_kinematics/fk_node.py` | ROS2 节点：订阅状态 -> FK -> 发布骨架位姿 |
| `hand_forward_kinematics/__init__.py` | 包标记文件 |
| `launch/hand_fk.launch.py` | 节点启动文件 |
| `setup.py` | 构建配置 |
| `package.xml` | ROS2 包元数据 |

## 技术深潜

### DOF 反转坑

最易出错的地方是 `L10_R_DIRECT` 方向反转。以 DOF 0（拇指弯曲）为例：

```
SDK 约定:  0 = 弯曲,  255 = 伸直
弧度约定:  0 = 伸直,  0.75 = 最大弯曲

L10_R_DIRECT[0] = -1  (反向)

range_to_arc:
  弧度 = _scale(val, 0, 255, MAX=0.75, MIN=0)  # 注意 MAX 在前
  val=0   -> arc=0.75  (最大弯曲)  ✓
  val=255 -> arc=0.0   (完全伸直)  ✓

arc_to_range (逆运算):
  val = _scale(arc, MAX=0.75, MIN=0, 0, 255)
  arc=0.75 -> val=0    (弯曲)  ✓
  arc=0.0  -> val=255  (伸直)  ✓
```

如果遗漏反转，手指会在弯曲命令时伸直、伸直命令时弯曲。

### 与 gateway ik_solver.py 的关系

FK 和 IK 构成互逆操作：

```
FK (本包):  DOF [0-255] x 10  -->  21 个 body 位姿 (位置 + 四元数)
IK (gateway):  目标骨架/指尖位姿  -->  DOF [0-255] x 10
```

Gateway 调用 IK 时，会使用本包的 `arc_to_range_l10_right()`、`L10_JOINT_MAP` 等常量完成逆映射。
