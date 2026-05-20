#!/usr/bin/env python3
"""
L10 Hand Gateway IK Solver
纯 Python FK + 数值 IK，无 MuJoCo 依赖

提供:
  - inverse_skeleton_to_dof: 21 全局四元数 → 10 DOF (0-255)
  - ik_control_points: 5 指尖 3D 位置 → 10 DOF (0-255)
"""

import math
import itertools
import numpy as np

from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    arc_to_range_l10_right,
    expand_to_20_joints,
    collapse_20_to_10,
    compute_fk,
    axis_angle_to_quat,
    quat_mul,
    quat_rotate,
    L10_R_MIN,
    L10_R_MAX,
    L10_R_DIRECT,
    L10_JOINT_MAP,
    KINEMATIC_CHAIN,
)

# ============================================================================
# 指尖 body 索引 (FK chain 中的 body index)
# ============================================================================

FINGERTIP_BODIES = [5, 9, 12, 16, 20]  # thumb, index, middle, ring, little

# 每个手指对应的 DOF (独立 DOF, 非 mimic)
FINGER_DOFS = [
    [0, 1, 9],   # thumb: 拇指弯曲, 侧摆, 侧旋
    [2, 6],      # index: 食指弯曲, 侧摆
    [3],         # middle: 中指弯曲
    [4, 7],      # ring: 无名指弯曲, 侧摆
    [5, 8],      # little: 小指弯曲, 侧摆
]

# ============================================================================
# 逆 FK: 骨架四元数 → DOF (复用 body_relative_rotation 逻辑)
# ============================================================================

# body 父子关系 (与 body_relative_rotation.py 一致)
BODY_PARENT_MAP = {
    1: 0, 2: 1, 3: 2, 4: 3, 5: 4,
    6: 0, 7: 6, 8: 7, 9: 8,
    10: 0, 11: 10, 12: 11,
    13: 0, 14: 13, 15: 14, 16: 15,
    17: 0, 18: 17, 19: 18, 20: 19,
}

# 每个 body 的静态四元数 (w, x, y, z)
BODY_STATIC_QUAT = {
    1:  np.array([1.0, 0.0, 0.0, 0.0]),
    2:  np.array([0.872224, -0.361289, -0.126164, -0.304595]),
    3:  np.array([0.959788, 0.280726, 0.0, 0.0]),
    4:  np.array([0.99537, -0.0961214, 0.0, 0.0]),
    5:  np.array([0.998255, -0.0590506, 0.0, 0.0]),
    6:  np.array([1.0, 0.0, 0.0, 0.0]),
    7:  np.array([1.0, 0.0, 0.0, 0.0]),
    8:  np.array([1.0, 0.0, 0.0, 0.0]),
    9:  np.array([1.0, 0.0, 0.0, 0.0]),
    10: np.array([1.0, 0.0, 0.0, 0.0]),
    11: np.array([1.0, 0.0, 0.0, 0.0]),
    12: np.array([1.0, 0.0, 0.0, 0.0]),
    13: np.array([1.0, 0.0, 0.0, 0.0]),
    14: np.array([1.0, 0.0, 0.0, 0.0]),
    15: np.array([1.0, 0.0, 0.0, 0.0]),
    16: np.array([1.0, 0.0, 0.0, 0.0]),
    17: np.array([1.0, 0.0, 0.0, 0.0]),
    18: np.array([1.0, 0.0, 0.0, 0.0]),
    19: np.array([1.0, 0.0, 0.0, 0.0]),
    20: np.array([1.0, 0.0, 0.0, 0.0]),
}

# 每个关节的旋转轴 (与 MuJoCo 模型一致)
JOINT_AXES = {
    "thumb_joint0":  np.array([1, 0, 0]),
    "thumb_joint1":  np.array([0, 0, -1]),
    "thumb_joint2":  np.array([1, 0, 0]),
    "thumb_joint3":  np.array([1, 0, 0]),
    "thumb_joint4":  np.array([1, 0, 0]),
    "index_joint0":  np.array([1, 0, 0]),
    "index_joint1":  np.array([0, 1, 0]),
    "index_joint2":  np.array([0, 1, 0]),
    "index_joint3":  np.array([0, 1, 0]),
    "middle_joint0": np.array([0, 1, 0]),
    "middle_joint1": np.array([0, 1, 0]),
    "middle_joint2": np.array([0, 1, 0]),
    "ring_joint0":   np.array([1, 0, 0]),
    "ring_joint1":   np.array([0, 1, 0]),
    "ring_joint2":   np.array([0, 1, 0]),
    "ring_joint3":   np.array([0, 1, 0]),
    "little_joint0": np.array([1, 0, 0]),
    "little_joint1": np.array([0, 1, 0]),
    "little_joint2": np.array([0, 1, 0]),
    "little_joint3": np.array([0, 1, 0]),
}

# body → 关节名
BODY_JOINT_NAMES = {
    1: "thumb_joint0",  2: "thumb_joint1",  3: "thumb_joint2",
    4: "thumb_joint3",  5: "thumb_joint4",
    6: "index_joint0",  7: "index_joint1",  8: "index_joint2",
    9: "index_joint3",
    10: "middle_joint0", 11: "middle_joint1", 12: "middle_joint2",
    13: "ring_joint0",  14: "ring_joint1",  15: "ring_joint2",
    16: "ring_joint3",
    17: "little_joint0", 18: "little_joint1", 19: "little_joint2",
    20: "little_joint3",
}

# 关节名 → MuJoCo joint 索引 (与 KINEMATIC_CHAIN 顺序一致)
_JOINT_NAME_TO_IDX = {
    "thumb_joint0": 0, "thumb_joint1": 1, "thumb_joint2": 2,
    "thumb_joint3": 3, "thumb_joint4": 4,
    "index_joint0": 5, "index_joint1": 6, "index_joint2": 7,
    "index_joint3": 8,
    "middle_joint0": 9, "middle_joint1": 10, "middle_joint2": 11,
    "ring_joint0": 12, "ring_joint1": 13, "ring_joint2": 14,
    "ring_joint3": 15,
    "little_joint0": 16, "little_joint1": 17, "little_joint2": 18,
    "little_joint3": 19,
}

# 20 关节 → 10 DOF 的反向映射 (每个 DOF 取第一个对应的关节)
_DOF_TO_JOINT = {}
for _mj_idx, _dof_idx in L10_JOINT_MAP.items():
    if _dof_idx not in _DOF_TO_JOINT:
        _DOF_TO_JOINT[_dof_idx] = _mj_idx


def _quat_inv(q):
    """四元数求逆 (单位四元数 = 共轭)"""
    return np.array([q[0], -q[1], -q[2], -q[3]])


def _quat_to_rotvec(q):
    """四元数 -> 旋转向量 (axis * angle)"""
    if q[0] < 0:
        q = -q
    angle = 2.0 * math.acos(np.clip(q[0], -1.0, 1.0))
    s = math.sqrt(max(0.0, 1.0 - q[0] * q[0]))
    if s < 1e-8:
        return np.zeros(3)
    axis = q[1:4] / s
    return axis * angle


def _scale(val, a_min, a_max, b_min, b_max):
    return (val - a_min) * (b_max - b_min) / (a_max - a_min) + b_min


def inverse_skeleton_to_dof(orientations_21):
    """
    从 21 个全局四元数反推 10 DOF (0-255)

    Args:
        orientations_21: 21 个 numpy 数组 (w, x, y, z) 全局四元数

    Returns:
        list: 10 DOF 值 (0-255)
    """
    # 1. 从全局四元数提取 20 个关节角度
    angles_20 = [0.0] * 20

    for child_idx in sorted(BODY_PARENT_MAP.keys()):
        parent_idx = BODY_PARENT_MAP[child_idx]
        q_parent = orientations_21[parent_idx]
        q_child = orientations_21[child_idx]

        # q_rel = q_parent^{-1} * q_child
        q_rel = quat_mul(_quat_inv(q_parent), q_child)

        # 去除静态四元数: q_joint = static_quat^{-1} * q_rel
        q_static = BODY_STATIC_QUAT[child_idx]
        q_joint = quat_mul(_quat_inv(q_static), q_rel)

        # 转为旋转向量
        rotvec = _quat_to_rotvec(q_joint)

        # 投影到关节轴
        joint_name = BODY_JOINT_NAMES[child_idx]
        axis = JOINT_AXES[joint_name]
        angle = float(np.dot(rotvec, axis))

        # 写入对应的 MuJoCo joint 索引
        mj_idx = _JOINT_NAME_TO_IDX[joint_name]
        angles_20[mj_idx] = angle

    # 2. 折叠 20 关节 → 10 DOF 弧度
    arc_10 = [0.0] * 10
    for dof_idx, mj_idx in _DOF_TO_JOINT.items():
        arc_10[dof_idx] = angles_20[mj_idx]

    # 3. 弧度 → 0-255
    dof_10 = [0.0] * 10
    for i in range(10):
        arc_clamped = min(L10_R_MAX[i], max(L10_R_MIN[i], arc_10[i]))
        if L10_R_DIRECT[i] == -1:
            val = _scale(arc_clamped, L10_R_MAX[i], L10_R_MIN[i], 0, 255)
        else:
            val = _scale(arc_clamped, L10_R_MIN[i], L10_R_MAX[i], 0, 255)
        dof_10[i] = min(255.0, max(0.0, val))

    return dof_10


def compute_control_points_from_dof(dof_10):
    """
    从 10 DOF (0-255) 计算 5 个指尖 3D 位置

    Args:
        dof_10: 10 个 DOF 值 (0-255)

    Returns:
        list: 5 个 numpy 数组 (x, y, z)
    """
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    positions, _ = compute_fk(joints_20)
    return [positions[bi] for bi in FINGERTIP_BODIES]


def compute_skeleton_from_dof(dof_10):
    """
    从 10 DOF (0-255) 计算 21 个 body 的位姿

    Args:
        dof_10: 10 个 DOF 值 (0-255)

    Returns:
        positions: 21 个 numpy 数组 (x, y, z)
        quaternions: 21 个 numpy 数组 (w, x, y, z)
    """
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    return compute_fk(joints_20)


# ============================================================================
# IK: 控制点 3D 位置 → DOF
# ============================================================================

def _fk_fingertip(arc_10, body_idx):
    """计算单个指尖在给定弧度值下的 3D 位置"""
    joints_20 = expand_to_20_joints(arc_10)
    positions, _ = compute_fk(joints_20)
    return positions[body_idx]


def _dist3d_sq(a, b):
    """3D 距离平方"""
    d = a - b
    return float(np.dot(d, d))


def _dist3d_sq_constrained(a, b, camera_normal):
    """
    加权 3D 距离平方 — 抑制相机法向量方向的分量至 20%

    在 IK 求解中，相机只能提供 2D 投影信息，沿相机视线方向 (法向量)
    的深度信息是不可靠的。因此将深度方向的误差分量权重降低到 0.2 (20%)，
    使 IK 优化器主要关注与相机平面平行的位移，避免在不可观测方向上
    产生错误的收敛。

    具体来说:
    - d = a - b 为 3D 位移向量
    - d_par = (d · n) * n 为沿法向量方向的分量 (深度方向)
    - d_perp = d - d_par 为与法向量垂直的分量 (相机平面内)
    - 最终距离 = |d_perp|² + 0.2 × |d_par|²

    Args:
        a: 指尖当前位置 (numpy 3D 向量)
        b: 目标位置 (numpy 3D 向量)
        camera_normal: 归一化的相机视线方向单位向量

    Returns:
        float: 加权距离平方
    """
    d = a - b
    # 将误差分解为平行于法向量和垂直于法向量的两个分量
    d_par = np.dot(d, camera_normal) * camera_normal  # 平行分量 (深度方向)
    d_perp = d - d_par  # 垂直分量 (相机平面内)
    # 平面内误差全权重，深度方向误差仅保留 20%
    return float(np.dot(d_perp, d_perp) + 0.2 * np.dot(d_par, d_par))


def ik_control_points(target_positions_5, initial_dof_10, camera_normal=None):
    """
    IK 求解: 5 个指尖目标位置 → 10 DOF (0-255)

    每个手指独立求解，使用网格采样 + 数值 Jacobian 精化

    Args:
        target_positions_5: 5 个目标 3D 位置 (numpy 数组)
        initial_dof_10: 初始 10 DOF 值 (0-255)，用作搜索起点
        camera_normal: 可选相机法向量 (3D), 给定时优先匹配投影平面误差

    Returns:
        list: 10 DOF 值 (0-255)
    """
    arc_10 = list(range_to_arc_l10_right(initial_dof_10))

    # 归一化相机法向量
    cn = None
    if camera_normal is not None:
        cn = np.asarray(camera_normal, dtype=np.float64)
        norm = np.linalg.norm(cn)
        if norm > 1e-6:
            cn = cn / norm
        else:
            cn = None

    for finger_idx in range(5):
        body_idx = FINGERTIP_BODIES[finger_idx]
        dofs = FINGER_DOFS[finger_idx]
        target = target_positions_5[finger_idx]
        n = len(dofs)

        if n == 1:
            _ik_solve_1dof(arc_10, dofs[0], body_idx, target, cn)
        else:
            _ik_solve_ndof(arc_10, dofs, n, body_idx, target, cn)

    return arc_to_range_l10_right(arc_10)


def _ik_solve_1dof(arc, dof, body_idx, target, camera_normal=None):
    """1-DOF IK: 线性采样 + 黄金分割精化"""
    lo, hi = L10_R_MIN[dof], L10_R_MAX[dof]
    dist_fn = (lambda a, b: _dist3d_sq_constrained(a, b, camera_normal)
               if camera_normal is not None else _dist3d_sq)

    # Phase 1: 均匀采样 21 点
    n_samples = 20
    best_arc = arc[dof]
    best_dist = float('inf')

    for i in range(n_samples + 1):
        t = lo + (hi - lo) * i / n_samples
        arc[dof] = t
        pos = _fk_fingertip(arc, body_idx)
        d = dist_fn(pos, target)
        if d < best_dist:
            best_dist = d
            best_arc = t

    # Phase 2: 黄金分割精化
    step = (hi - lo) / n_samples
    a = max(lo, best_arc - step)
    b = min(hi, best_arc + step)
    gr = (math.sqrt(5) + 1) / 2

    for _ in range(12):
        if b - a < 1e-5:
            break
        c = b - (b - a) / gr
        d = a + (b - a) / gr

        arc[dof] = c
        pc = _fk_fingertip(arc, body_idx)
        dc = dist_fn(pc, target)

        arc[dof] = d
        pd = _fk_fingertip(arc, body_idx)
        dd = dist_fn(pd, target)

        if dc < dd:
            b = d
        else:
            a = c

    arc[dof] = (a + b) / 2


def _ik_solve_ndof(arc, dofs, n, body_idx, target, camera_normal=None):
    """N-DOF IK (N>=2): 网格采样 + 数值 Jacobian 精化"""
    dist_fn = (lambda a, b: _dist3d_sq_constrained(a, b, camera_normal)
               if camera_normal is not None else _dist3d_sq)

    # Phase 1: 网格采样
    spa = int(80 ** (1.0 / n))
    ranges = [np.linspace(L10_R_MIN[dof], L10_R_MAX[dof], spa) for dof in dofs]
    best_dist = float('inf')
    best_combo = tuple(arc[dof] for dof in dofs)

    for combo in itertools.product(*ranges):
        for col, dof in enumerate(dofs):
            arc[dof] = combo[col]
        pos = _fk_fingertip(arc, body_idx)
        d = dist_fn(pos, target)
        if d < best_dist:
            best_dist = d
            best_combo = combo

    for col, dof in enumerate(dofs):
        arc[dof] = best_combo[col]

    # Phase 2: Jacobian 精化 — 在网格采样找到的全局最优起点上进行梯度下降
    max_iter = 10
    for _ in range(max_iter):
        # Step 1: 计算当前弧度值下的指尖位置和误差向量
        base_pos = _fk_fingertip(arc, body_idx)
        err = target - base_pos  # 3D 误差向量 (从当前位置指向目标)
        if np.dot(err, err) < 1e-8:
            break  # 误差足够小，提前退出

        # Step 2: 构建数值 Jacobian 矩阵 J (3×N)
        # J[i, j] = ∂(指尖位置第i维) / ∂(第j个DOF的弧度值)
        # 采用前向差分: J[:, j] ≈ (perturbed_pos - base_pos) / eps
        J = np.zeros((3, n))
        eps = 0.01  # 数值微分的步长 (弧度)
        for col, dof in enumerate(dofs):
            arc_p = list(arc)
            new_val = arc_p[dof] + eps
            # 如果正向扰动超出关节限位，则尝试反向扰动
            clamped = max(L10_R_MIN[dof], min(L10_R_MAX[dof], new_val))
            if abs(clamped - arc_p[dof]) < 1e-9:
                clamped = max(L10_R_MIN[dof], min(L10_R_MAX[dof], arc_p[dof] - eps))
            if abs(clamped - arc_p[dof]) < 1e-9:
                continue  # 关节已达极限，无法计算梯度
            actual_eps = clamped - arc_p[dof]  # 实际扰动量 (可能被限位截断)
            arc_p[dof] = clamped
            pert_pos = _fk_fingertip(arc_p, body_idx)
            # 数值偏导: 指尖位移 / 弧度增量
            J[:, col] = (pert_pos - base_pos) / actual_eps

        # Step 3: 使用阻尼最小二乘 (Damped Least Squares / Levenberg-Marquardt)
        # 求解关节增量 dq = J^T (JJ^T + λ²I)^{-1} dp
        # 其中 λ 为阻尼因子，防止在奇异点附近步长过大
        dp = err
        # 如果有相机法向量，抑制深度方向的误差 (保留 20% 权重)
        # 这与 _dist3d_sq_constrained 的 0.2 权重一致
        if camera_normal is not None:
            dp = dp - 0.8 * np.dot(dp, camera_normal) * camera_normal
        # 自适应阻尼: Jacobian 范数越大 → λ 越大 → 步长越小
        jnorm = np.linalg.norm(J)
        lam = max(1.0, 5.0 / (jnorm + 0.01))
        JJT = J @ J.T  # 3×3 矩阵
        try:
            dq = J.T @ np.linalg.solve(JJT + lam * lam * np.eye(3), dp)
        except np.linalg.LinAlgError:
            break  # 矩阵奇异，无法求解

        # Step 4: 应用关节增量，带限幅保护
        for col, dof in enumerate(dofs):
            range_size = L10_R_MAX[dof] - L10_R_MIN[dof]
            # 单步最大不超过关节范围的 20%，防止过冲
            max_step = range_size * 0.2
            dq[col] = max(-max_step, min(max_step, dq[col]))
            arc[dof] += dq[col]
            # 限制在关节限位范围内
            arc[dof] = max(L10_R_MIN[dof], min(L10_R_MAX[dof], arc[dof]))
