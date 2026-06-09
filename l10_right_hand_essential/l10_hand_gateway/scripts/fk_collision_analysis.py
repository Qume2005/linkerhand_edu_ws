#!/usr/bin/env python3
"""
FK 碰撞分析脚本 — 生成碰撞防护查找表

分析内容：
1. 拇指 vs 食指：4D 扫描 DOF0×DOF1×DOF9×DOF6 × 食指弯曲度
2. 拇指 vs 其余三指：3D 扫描 DOF0×DOF1×DOF9 × 每指弯曲度
3. 小指 vs 无名指：扫描 DOF7×DOF8，找侧摆碰撞边界

DOF6（食指侧摆）对 thumb_vs_index 碰撞边界影响显著：
- DOF6=0（食指收拢）时食指靠近拇指，碰撞风险大幅增加
- DOF6=255（食指外展）时食指远离拇指，碰撞风险降低
因此 thumb_vs_index 使用 4D 查找表（含 DOF6 维度）。

输出：JSON 查找表数据，供 collision_guard.py 使用
"""

import sys
import os
import json
import math

_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(_ws, 'hand_forward_kinematics'))

import numpy as np
from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    expand_to_20_joints,
    compute_fk,
)

# ============================================================================
# 手指几何：body index → Y方向半径 (mm → m)
# ============================================================================

# 从 STL 网格提取的 Y 方向半径
BODY_RADIUS = {
    # 拇指
    2: 0.0117,   # thumb_proximal (cmc_roll body)
    3: 0.0105,   # thumb middle (cmc_yaw body, 插值)
    4: 0.0094,   # thumb_distal (mcp body)
    5: 0.0090,   # thumb tip (ip body)
    # 食指
    7: 0.0084,   # index proximal (mcp_pitch body)
    8: 0.0080,   # index middle (pip body)
    9: 0.0079,   # index distal (dip body)
    # 中指
    10: 0.0084,  # middle proximal
    11: 0.0080,  # middle middle
    12: 0.0079,  # middle distal
    # 无名指
    14: 0.0084,  # ring proximal
    15: 0.0080,  # ring middle
    16: 0.0079,  # ring distal
    # 小指
    18: 0.0084,  # pinky proximal
    19: 0.0080,  # pinky middle
    20: 0.0079,  # pinky distal
}

# 手指关节 body 列表（用于碰撞检测的关节点）
THUMB_BODIES = [2, 3, 4, 5]
INDEX_BODIES = [7, 8, 9]
MIDDLE_BODIES = [10, 11, 12]
RING_BODIES = [14, 15, 16]
PINKY_BODIES = [18, 19, 20]

# 手指弯曲 DOF 索引
FINGER_FLEX_DOF = {
    "index": 2,
    "middle": 3,
    "ring": 4,
    "pinky": 5,
}

# 手指 body 列表映射
FINGER_BODIES = {
    "index": INDEX_BODIES,
    "middle": MIDDLE_BODIES,
    "ring": RING_BODIES,
    "pinky": PINKY_BODIES,
}


def dof_to_positions(dof_10):
    """10 DOF (0-255) → 21 个 body 位置"""
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    positions, _ = compute_fk(joints_20)
    return positions


# 碰撞检测安全余量（m）— 使查找表更保守，补偿采样分辨率不足
COLLISION_MARGIN = 0.006  # 6mm


def check_collision(positions, bodies_a, bodies_b, margin=0.0):
    """检查两组 body 之间是否有碰撞（关节中心距 < 半径之和 + 余量）"""
    min_dist = float('inf')
    for ba in bodies_a:
        for bb in bodies_b:
            d = float(np.linalg.norm(positions[ba] - positions[bb]))
            threshold = BODY_RADIUS.get(ba, 0.008) + BODY_RADIUS.get(bb, 0.008) + margin
            if d < threshold:
                return True, d
            min_dist = min(min_dist, d)
    return False, min_dist


# ============================================================================
# 分析 1：拇指 vs 每根手指 — 生成查找表
# ============================================================================
# 食指（index）使用 4D 查找表：(DOF1, DOF9, DOF6, finger_flex) → DOF0_min_safe
#   DOF6（食指侧摆）显著影响碰撞边界：
#   DOF6=0（收拢）时食指靠近拇指，碰撞风险大幅增加
# 其余手指使用 3D 查找表：(DOF1, DOF9, finger_flex) → DOF0_min_safe
# DOF0 是 reversed (0=全弯, 255=伸直)，安全下限 = 允许的最大弯曲

def analyze_thumb_vs_finger(finger_name, resolution=16):
    """分析拇指 vs 单根手指的碰撞边界。

    对于 index 手指，生成 4D 查找表：(DOF1, DOF9, DOF6, flex) → DOF0_min_safe
    对于其余手指，生成 3D 查找表：(DOF1, DOF9, flex) → DOF0_min_safe

    DOF0_min_safe 是允许弯曲到的最小值（越小越弯），低于此值会碰撞。
    """
    flex_dof = FINGER_FLEX_DOF[finger_name]
    finger_bodies = FINGER_BODIES[finger_name]
    is_index = (finger_name == "index")

    # 采样分辨率
    dof1_samples = np.linspace(0, 255, resolution, dtype=float)
    dof9_samples = np.linspace(0, 255, resolution, dtype=float)
    flex_samples = np.linspace(0, 255, resolution, dtype=float)
    if is_index:
        dof6_samples = np.linspace(0, 255, resolution, dtype=float)

    lookup = {}

    if is_index:
        # 4D 扫描：DOF1 × DOF9 × DOF6 × flex
        for fi, flex_val in enumerate(flex_samples):
            for d1i, dof1_val in enumerate(dof1_samples):
                for d9i, dof9_val in enumerate(dof9_samples):
                    for d6i, dof6_val in enumerate(dof6_samples):
                        # 二分搜索 DOF0 的安全下限
                        lo, hi = 0.0, 255.0
                        best = 0.0
                        while hi - lo > 2.0:
                            mid = (lo + hi) / 2.0
                            dof = [255.0] * 10
                            dof[0] = mid
                            dof[1] = dof1_val
                            dof[flex_dof] = flex_val
                            dof[6] = dof6_val
                            dof[9] = dof9_val
                            pos = dof_to_positions(dof)
                            coll, _ = check_collision(pos, THUMB_BODIES, finger_bodies,
                                                         margin=COLLISION_MARGIN)
                            if coll:
                                lo = mid
                            else:
                                best = mid
                                hi = mid
                        if best > 2.0:
                            lookup[(d1i, d9i, d6i, fi)] = round(best, 1)
    else:
        # 3D 扫描：DOF1 × DOF9 × flex
        for fi, flex_val in enumerate(flex_samples):
            for d1i, dof1_val in enumerate(dof1_samples):
                for d9i, dof9_val in enumerate(dof9_samples):
                    lo, hi = 0.0, 255.0
                    best = 0.0
                    while hi - lo > 2.0:
                        mid = (lo + hi) / 2.0
                        dof = [255.0] * 10
                        dof[0] = mid
                        dof[1] = dof1_val
                        dof[flex_dof] = flex_val
                        dof[9] = dof9_val
                        pos = dof_to_positions(dof)
                        coll, _ = check_collision(pos, THUMB_BODIES, finger_bodies,
                                                     margin=COLLISION_MARGIN)
                        if coll:
                            lo = mid
                        else:
                            best = mid
                            hi = mid
                    if best > 2.0:
                        lookup[(d1i, d9i, fi)] = round(best, 1)

    result = {
        "finger": finger_name,
        "resolution": resolution,
        "dof1_samples": dof1_samples.tolist(),
        "dof9_samples": dof9_samples.tolist(),
        "flex_samples": flex_samples.tolist(),
    }
    if is_index:
        result["dof6_samples"] = dof6_samples.tolist()
        result["lookup"] = {f"{k[0]},{k[1]},{k[2]},{k[3]}": v for k, v in lookup.items()}
    else:
        result["lookup"] = {f"{k[0]},{k[1]},{k[2]}": v for k, v in lookup.items()}

    return result


# ============================================================================
# 分析 2：小指 vs 无名指 — DOF7×DOF8 碰撞边界
# ============================================================================
# 碰撞条件：DOF7 高（无名指向外展开）+ DOF8 低（小指未展开）
# 与弯曲无关

def analyze_pinky_ring_lateral(resolution=32):
    """分析小指-无名指侧摆碰撞边界。

    生成碰撞矩阵：(DOF7, DOF8) → collision (bool)
    """
    dof7_samples = np.linspace(0, 255, resolution, dtype=float)
    dof8_samples = np.linspace(0, 255, resolution, dtype=float)

    collision_map = {}
    min_safe_margin = 0.001  # 1mm 安全余量

    for d7i, dof7_val in enumerate(dof7_samples):
        for d8i, dof8_val in enumerate(dof8_samples):
            dof = [255.0] * 10  # 所有手指伸直
            dof[7] = dof7_val
            dof[8] = dof8_val
            pos = dof_to_positions(dof)
            coll, dist = check_collision(pos, RING_BODIES, PINKY_BODIES)
            # 加安全余量
            if coll or dist < (0.0084 + 0.0084 + min_safe_margin):
                collision_map[f"{d7i},{d8i}"] = True

    return {
        "resolution": resolution,
        "collision_map": collision_map,
        "dof7_samples": dof7_samples.tolist(),
        "dof8_samples": dof8_samples.tolist(),
    }


# ============================================================================
# 主流程
# ============================================================================

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="FK 碰撞分析")
    parser.add_argument("--thumb-res", type=int, default=16,
                        help="拇指扫描分辨率 (每 DOF 采样点数)")
    parser.add_argument("--lateral-res", type=int, default=32,
                        help="侧摆扫描分辨率")
    parser.add_argument("--output", type=str, default=None,
                        help="输出 JSON 文件路径")
    parser.add_argument("--finger", type=str, default=None,
                        help="只分析指定手指 (index/middle/ring/pinky)")
    args = parser.parse_args()

    results = {}

    # 分析拇指碰撞
    fingers = [args.finger] if args.finger else ["index", "middle", "ring", "pinky"]
    for finger in fingers:
        print(f"\n分析拇指 vs {finger} (分辨率={args.thumb_res})...")
        data = analyze_thumb_vs_finger(finger, resolution=args.thumb_res)
        n_entries = len(data["lookup"])
        print(f"  找到 {n_entries} 个碰撞边界点")
        results[f"thumb_vs_{finger}"] = data

    # 分析小指-无名指侧摆
    print(f"\n分析小指-无名指侧摆 (分辨率={args.lateral_res})...")
    lateral = analyze_pinky_ring_lateral(resolution=args.lateral_res)
    n_coll = len(lateral["collision_map"])
    print(f"  找到 {n_coll} 个碰撞点 (共 {args.lateral_res**2})")
    results["pinky_ring_lateral"] = lateral

    # 输出
    output_path = args.output or os.path.join(os.path.dirname(__file__), '..', 'l10_hand_gateway', 'collision_tables.json')
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n查找表已写入: {output_path}")

    # 打印摘要
    print("\n" + "=" * 60)
    print("摘要")
    print("=" * 60)
    for key, data in results.items():
        if key.startswith("thumb_vs_"):
            n = len(data["lookup"])
            print(f"  {key}: {n} 个碰撞边界点")
        elif key == "pinky_ring_lateral":
            total = data["resolution"] ** 2
            n = len(data["collision_map"])
            print(f"  {key}: {n}/{total} 碰撞点 ({100*n/total:.1f}%)")
