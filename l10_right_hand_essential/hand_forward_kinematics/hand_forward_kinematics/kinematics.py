"""
L10 Right Hand Forward Kinematics — 纯 Python 正向运动学库

本模块实现了 L10 右手从 10 自由度 (DOF) 到 21 个骨骼点位姿的完整正向运动学求解，
完全不依赖 MuJoCo 运行时。所有运动链数据均从 MuJoCo XML 模型中硬编码提取。

核心功能：
- **四元数数学**：乘法、旋转向量、轴角转四元数（w,x,y,z 约定，与 MuJoCo 一致）
- **DOF 转换**：0-255 整数 <-> 弧度值（含方向反转处理 L10_R_DIRECT）
- **20 关节映射**：10 DOF <-> 20 MuJoCo 关节（含 mimic 关节乘数展开/折叠）
- **FK 求解器**：给定 20 个关节角度，计算 21 个 body 的全局位置和四元数

设计原则：
- 所有运动链数据从 MuJoCo XML 硬编码，无 MuJoCo 运行时依赖
- 预计算 ``_CHAIN_NP`` 将列表数据转为 numpy 数组，避免每次 FK 调用时重复转换
- 与 ``l10_hand_gateway/ik_solver.py`` 构成 FK/IK 对：FK 用于骨架计算，IK 用于逆解

依赖：numpy（无 ROS 依赖，可独立使用）
"""

import math
import numpy as np

# ============================================================================
# 四元数数学 (w, x, y, z 约定，与 MuJoCo 一致)
# ============================================================================


def quat_mul(q1, q2):
    """Hamilton 四元数乘法 q1 * q2。

    Args:
        q1: 第一个四元数 (w, x, y, z)
        q2: 第二个四元数 (w, x, y, z)

    Returns:
        numpy.ndarray: 乘积四元数 (w, x, y, z)
    """
    w1, x1, y1, z1 = q1
    w2, x2, y2, z2 = q2
    return np.array([
        w1*w2 - x1*x2 - y1*y2 - z1*z2,
        w1*x2 + x1*w2 + y1*z2 - z1*y2,
        w1*y2 - x1*z2 + y1*w2 + z1*x2,
        w1*z2 + x1*y2 - y1*x2 + z1*w2,
    ])


def quat_rotate(q, v):
    """用四元数 q 旋转向量 v，即计算 q * (0, v) * q^{-1}。

    Args:
        q: 单位四元数 (w, x, y, z)
        v: 三维向量 (x, y, z)

    Returns:
        numpy.ndarray: 旋转后的三维向量
    """
    qv = np.array([0.0, v[0], v[1], v[2]])
    q_conj = np.array([q[0], -q[1], -q[2], -q[3]])
    return quat_mul(quat_mul(q, qv), q_conj)[1:]


def axis_angle_to_quat(axis, angle):
    """轴角表示转四元数 (w, x, y, z)。

    Args:
        axis: 旋转轴单位向量 (x, y, z)
        angle: 旋转角度（弧度）

    Returns:
        numpy.ndarray: 四元数 (w, x, y, z)
    """
    half = angle * 0.5
    s = math.sin(half)
    c = math.cos(half)
    return np.array([c, axis[0]*s, axis[1]*s, axis[2]*s])


# ============================================================================
# L10 右手 DOF 映射常量 (from mujoco_node.py)
# ============================================================================

# MuJoCo 关节索引 -> SDK DOF 索引 (耦合/mimic 关节共享同一 DOF)
#
# MuJoCo 模型有 20 个关节，但 L10 只驱动 10 个 DOF。
# 多个 MuJoCo 关节映射到同一个 DOF 索引，其中非 mimic 关节（主关节）的
# 角度直接等于 DOF 弧度值，mimic 关节的角度 = 主关节角度 * 乘数。
#
# 示例：MuJoCo 关节 2, 3, 4 都映射到 DOF 0（拇指弯曲），
#       其中关节 3 是主关节，关节 2 和 4 是 mimic 关节。
L10_JOINT_MAP = {
    0: 9,  1: 1,   2: 0,   3: 0,  4: 0,  5: 6,
    6: 2,  7: 2,   8: 2,   9: 3,  10: 3, 11: 3,
    12: 7, 13: 4,  14: 4,  15: 4, 16: 8, 17: 5,
    18: 5, 19: 5
}

# DOF0: 拇指弯曲  DOF1: 拇指侧摆  DOF2: 食指弯曲  DOF3: 中指弯曲  DOF4: 无名指弯曲
# DOF5: 小指弯曲  DOF6: 食指侧摆  DOF7: 无名指侧摆  DOF8: 小指侧摆  DOF9: 拇指侧旋

# 各 DOF 对应的弧度范围（从 MuJoCo XML 关节的 range 属性提取）
L10_R_MIN = [0, 0, 0, 0, 0, 0, -0.26, 0, 0, -0.52]
L10_R_MAX = [0.75, 1.43, 1.62, 1.62, 1.62, 1.62, 0, 0.13, 0.26, 1.01]

# 方向标志：-1 表示 0-255 到弧度时反向映射（255 → MIN, 0 → MAX），
# 0 表示正向映射（0 → MIN, 255 → MAX）。
# 大部分 DOF 是 -1，因为 SDK 约定 0=弯曲，但弧度值 0=伸直。
L10_R_DIRECT = [-1, -1, -1, -1, -1, -1, -1, 0, 0, -1]


# ============================================================================
# 运动链数据 (from linker_hand_l10_right.xml)
#
# 每个元组描述运动链中的一个连杆 (body)，格式为：
#   (body_idx, parent_idx, pos[], quat[], joint_axis[], mj_joint_idx)
#
# - body_idx:     MuJoCo body 编号（0 = 世界/基座，1-20 = 手指各连杆）
# - parent_idx:   父 body 编号（构成树形层级结构）
# - pos[]:        相对于父 body 的平移偏移 (3D)
# - quat[]:       相对于父 body 的静态旋转四元数 (w,x,y,z)，表示关节零位的朝向
# - joint_axis[]: 关节旋转轴方向 (3D)，如 [1,0,0] 表示绕局部 X 轴旋转
# - mj_joint_idx: 对应的 MuJoCo 关节索引（0-19）
#
# 拇指有 5 个关节 (0-4)，其余四指各有 3-4 个关节。
# body 0 为世界原点，不在此表中（位姿初始化为单位变换）。
# ============================================================================

KINEMATIC_CHAIN = [
    # 拇指 (joints 0-4)
    (1,  0, [-0.017939, 0.018426, 0.057469],
            [1.0, 0.0, 0.0, 0.0],
            [1, 0, 0], 0),
    (2,  1, [0.0303, -0.0097852, -0.0097852],
            [0.872224, -0.361289, -0.126164, -0.304595],
            [0, 0, -1], 1),
    (3,  2, [0.0039399, 0.028731, 0.012357],
            [0.959788, 0.280726, 0.0, 0.0],
            [1, 0, 0], 2),
    (4,  3, [-0.01062, 0.050514, 0.0],
            [0.99537, -0.0961214, 0.0, 0.0],
            [1, 0, 0], 3),
    (5,  4, [0.00532, 0.036667, 0.0],
            [0.998255, -0.0590506, 0.0, 0.0],
            [1, 0, 0], 4),

    # 食指 (joints 5-8)
    (6,  0, [0.011645, 0.02293, 0.12973],
            [1.0, 0.0, 0.0, 0.0],
            [1, 0, 0], 5),
    (7,  6, [-0.012765, 0.0085, 0.017575],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 6),
    (8,  7, [-0.0051959, -0.0031156, 0.033276],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 7),
    (9,  8, [-0.0094663, -5.4404e-05, 0.024474],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 8),

    # 中指 (joints 9-11)
    (10, 0, [-0.0031059, 0.01243, 0.1523],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 9),
    (11, 10, [-0.0051959, -0.0031156, 0.033276],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 10),
    (12, 11, [-0.0094663, -5.4404e-05, 0.024474],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 11),

    # 无名指 (joints 12-15)
    (13, 0, [0.011645, -0.01507, 0.12973],
            [1.0, 0.0, 0.0, 0.0],
            [1, 0, 0], 12),
    (14, 13, [-0.012765, 0.0085, 0.017575],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 13),
    (15, 14, [-0.0051959, -0.0031156, 0.033276],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 14),
    (16, 15, [-0.0094663, -5.4399e-05, 0.024474],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 15),

    # 小指 (joints 16-19)
    (17, 0, [0.013645, -0.03407, 0.12473],
            [1.0, 0.0, 0.0, 0.0],
            [1, 0, 0], 16),
    (18, 17, [-0.012765, 0.0085, 0.017575],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 17),
    (19, 18, [-0.0051959, -0.0031156, 0.033276],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 18),
    (20, 19, [-0.0094663, -5.4404e-05, 0.024474],
            [1.0, 0.0, 0.0, 0.0],
            [0, 1, 0], 19),
]

# 预计算：将运动链数据从 Python 列表转为 numpy 数组
#
# 这一步在模块加载时执行一次，避免每次调用 compute_fk() 时重复创建 numpy 数组。
# FK 求解在每次收到手部状态时都会调用（可达 30Hz+），预计算可显著减少 GC 压力。
_CHAIN_NP = []
for body_idx, parent_idx, pos, quat, axis, mj_joint in KINEMATIC_CHAIN:
    _CHAIN_NP.append((
        body_idx, parent_idx,
        np.array(pos, dtype=np.float64),       # 平移偏移
        np.array(quat, dtype=np.float64),      # 静态四元数
        np.array(axis, dtype=np.float64),      # 关节轴
        mj_joint                                # 关节索引（int）
    ))


# ============================================================================
# Range-to-Arc 转换
# ============================================================================


def _scale(val, a_min, a_max, b_min, b_max):
    """线性映射（线性插值）：将 val 从 [a_min, a_max] 区间映射到 [b_min, b_max] 区间。

    Args:
        val:     待映射的值
        a_min:   源区间下界
        a_max:   源区间上界
        b_min:   目标区间下界
        b_max:   目标区间上界

    Returns:
        float: 映射后的值
    """
    return (val - a_min) * (b_max - b_min) / (a_max - a_min) + b_min


def range_to_arc_l10_right(position_range):
    """将 10 DOF 的 0-255 整数值转换为对应的弧度值。

    根据 L10_R_DIRECT 标志决定映射方向：
    - DIRECT == -1 时反向映射：0 → MAX, 255 → MIN（"弯曲"语义与弧度方向相反）
    - DIRECT ==  0 时正向映射：0 → MIN, 255 → MAX

    Args:
        position_range: 10 个 DOF 值的列表，每个值范围 [0, 255]

    Returns:
        list[float]: 10 个弧度值的列表
    """
    hand_arc = [0.0] * 10
    for i in range(10):
        val = min(255, max(0, position_range[i]))
        if L10_R_DIRECT[i] == -1:
            hand_arc[i] = _scale(val, 0, 255, L10_R_MAX[i], L10_R_MIN[i])
        else:
            hand_arc[i] = _scale(val, 0, 255, L10_R_MIN[i], L10_R_MAX[i])
    return hand_arc


def arc_to_range_l10_right(arc_values):
    """将 10 DOF 弧度值转换回 0-255 整数值（range_to_arc 的逆运算）。

    Args:
        arc_values: 10 个弧度值的列表

    Returns:
        list[float]: 10 个 0-255 范围内的值（已 clamp）
    """
    position_range = [0.0] * 10
    for i in range(10):
        arc_clamped = min(L10_R_MAX[i], max(L10_R_MIN[i], arc_values[i]))
        if L10_R_DIRECT[i] == -1:
            # range_to_arc: arc = scale(val, 0,255, MAX,MIN)
            # 逆运算:       val = scale(arc, MAX,MIN, 0,255)
            val = _scale(arc_clamped, L10_R_MAX[i], L10_R_MIN[i], 0, 255)
        else:
            # range_to_arc: arc = scale(val, 0,255, MIN,MAX)
            # 逆运算:       val = scale(arc, MIN,MAX, 0,255)
            val = _scale(arc_clamped, L10_R_MIN[i], L10_R_MAX[i], 0, 255)
        position_range[i] = min(255, max(0, val))
    return position_range


# ============================================================================
# Mimic 关节（耦合关节）概念说明
#
# L10 有 10 个电机 DOF，但 MuJoCo 模型有 20 个关节。为了在仿真中逼真地
# 模拟手指运动，部分关节的角度由主关节的角度乘以一个固定系数得到——
# 这些关节称为 "mimic 关节"（或耦合关节）。
#
# 例如：
#   - 食指有 3 个弯曲关节 (MuJoCo 6, 7, 8)，但只有 1 个电机 (DOF 2)
#   - MuJoCo 关节 7 是主关节，关节 6 = 主 * 0.87，关节 8 = 主 * 0.59
#   - 这模拟了人手指近端弯曲时远端自然跟随的力学耦合效果
#
# 20 关节 → 10 DOF 时：取每个 DOF 对应的主关节角度（忽略 mimic）
# 10 DOF → 20 关节时：先映射主关节，再通过乘数展开 mimic 关节
# ============================================================================

# 20 关节 → 10 DOF 的反向映射
# 每个 DOF 索引对应的主 (非 mimic) MuJoCo 关节索引
# mimic 关节的角度 = 主关节 * multiplier，读回时必须取主关节
_DOF_TO_PRIMARY_JOINT = {
    0: 3,   # DOF0 拇指弯曲 → thumb_joint3 (primary)
    1: 1,   # DOF1 拇指侧摆 → thumb_joint1 (独立)
    2: 7,   # DOF2 食指弯曲 → index_joint2 (primary)
    3: 10,  # DOF3 中指弯曲 → middle_joint1 (primary)
    4: 14,  # DOF4 无名指弯曲 → ring_joint2 (primary)
    5: 18,  # DOF5 小指弯曲 → little_joint2 (primary)
    6: 5,   # DOF6 食指侧摆 → index_joint0 (独立)
    7: 12,  # DOF7 无名指侧摆 → ring_joint0 (独立)
    8: 16,  # DOF8 小指侧摆 → little_joint0 (独立)
    9: 0,   # DOF9 拇指侧旋 → thumb_joint0 (独立)
}


def collapse_20_to_10(joint_angles_20):
    """将 20 个 MuJoCo 关节角度折叠回 10 DOF（只读取主关节角度）。

    忽略所有 mimic 关节，只取每个 DOF 对应的主关节角度值。

    Args:
        joint_angles_20: 20 个 MuJoCo 关节角度的列表（弧度）

    Returns:
        list[float]: 10 个 DOF 对应的主关节角度值
    """
    dof_values = [0.0] * 10
    for dof_idx, mj_idx in _DOF_TO_PRIMARY_JOINT.items():
        dof_values[dof_idx] = joint_angles_20[mj_idx]
    return dof_values


# URDF mimic 关系 (同 mujoco_node.py)
_MIMIC_JOINTS = {
    2:  (3,  0.58),   # thumb_joint2 = thumb_joint3 * 0.58
    4:  (3,  0.93),   # thumb_joint4 = thumb_joint3 * 0.93
    6:  (7,  0.87),   # index_joint1 = index_joint2 * 0.87
    8:  (7,  0.59),   # index_joint3 = index_joint2 * 0.59
    9:  (10, 0.87),   # middle_joint0 = middle_joint1 * 0.87
    11: (10, 0.59),   # middle_joint2 = middle_joint1 * 0.59
    13: (14, 0.87),   # ring_joint1 = ring_joint2 * 0.87
    15: (14, 0.59),   # ring_joint3 = ring_joint2 * 0.59
    17: (18, 0.87),   # little_joint1 = little_joint2 * 0.87
    19: (18, 0.59),   # little_joint3 = little_joint2 * 0.59
}


def expand_to_20_joints(arc_10):
    """将 10 DOF 弧度值扩展为 20 个 MuJoCo 关节角度（含 mimic 乘数展开）。

    先通过 L10_JOINT_MAP 将 10 DOF 映射到对应的 MuJoCo 关节，
    再根据 _MIMIC_JOINTS 中的乘数关系填充耦合关节。

    Args:
        arc_10: 10 个 DOF 弧度值的列表

    Returns:
        list[float]: 20 个 MuJoCo 关节角度（弧度）
    """
    mapped = [0.0] * 20
    for mj_idx, dof_idx in L10_JOINT_MAP.items():
        mapped[mj_idx] = arc_10[dof_idx]
    # 应用 mimic 乘数
    for mimic_idx, (primary_idx, multiplier) in _MIMIC_JOINTS.items():
        mapped[mimic_idx] = mapped[primary_idx] * multiplier
    return mapped


# ============================================================================
# FK 求解器
# ============================================================================


def compute_fk(joint_angles_20):
    """
    正向运动学：给定 20 个关节角度，计算 21 个 body 的全局位姿。

    Args:
        joint_angles_20: 20 个关节角度 (弧度)

    Returns:
        positions: 21 个 numpy 数组 (x, y, z)
        quaternions: 21 个 numpy 数组 (w, x, y, z)
    """
    positions = [np.zeros(3) for _ in range(21)]
    quaternions = [np.array([1.0, 0.0, 0.0, 0.0]) for _ in range(21)]

    # body 0 = world (原点 + 单位四元数, 已初始化)

    for body_idx, parent_idx, pos, static_quat, joint_axis, mj_joint in _CHAIN_NP:
        q_parent = quaternions[parent_idx]
        p_parent = positions[parent_idx]
        angle = joint_angles_20[mj_joint]

        # MuJoCo 约定: T = Trans(pos) * Rot(static_quat) * Rot(axis, angle)
        q_joint = axis_angle_to_quat(joint_axis, angle)
        q_frame = quat_mul(static_quat, q_joint)
        q_global = quat_mul(q_parent, q_frame)
        p_global = quat_rotate(q_parent, pos) + p_parent

        positions[body_idx] = p_global
        quaternions[body_idx] = q_global

    return positions, quaternions
