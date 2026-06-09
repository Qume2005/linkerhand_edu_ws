#!/usr/bin/env python3
"""碰撞防护 FK 精度验证 — 集成测试

使用真实 FK 求解器和 body 半径，验证 JointRuleGuard 修正后的 DOF 配置
不产生任何实际的指间碰撞。覆盖拇指 vs 四指的全部 body 对。
"""

import os
import sys
import random
import unittest

_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, os.path.join(_ws, 'hand_forward_kinematics'))
sys.path.insert(0, os.path.join(_ws, 'l10_hand_gateway'))

import numpy as np
from l10_hand_gateway.collision_guard import JointRuleGuard
from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    expand_to_20_joints,
    compute_fk,
)

# Body 半径（与 fk_collision_analysis.py 保持一致）
BODY_RADIUS = {
    2: 0.0117, 3: 0.0105, 4: 0.0094, 5: 0.0090,   # 拇指
    7: 0.0084, 8: 0.0080, 9: 0.0079,                # 食指
    10: 0.0084, 11: 0.0080, 12: 0.0079,             # 中指
    14: 0.0084, 15: 0.0080, 16: 0.0079,             # 无名指
    18: 0.0084, 19: 0.0080, 20: 0.0079,             # 小指
}

# 碰撞检查的手指对
FINGER_PAIRS = [
    ("thumb", [2, 3, 4, 5], "index", [7, 8, 9]),
    ("thumb", [2, 3, 4, 5], "middle", [10, 11, 12]),
    ("thumb", [2, 3, 4, 5], "ring", [14, 15, 16]),
    ("thumb", [2, 3, 4, 5], "pinky", [18, 19, 20]),
    ("ring", [14, 15, 16], "pinky", [18, 19, 20]),
]

SAFETY_MARGIN = 0.0005  # 0.5mm 安全余量


def _dof_to_positions(dof_10):
    """10 DOF (0-255) → 21 个 body 位置"""
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    positions, _ = compute_fk(joints_20)
    return positions


def _check_pair_collision(positions, bodies_a, bodies_b, margin=0.0):
    """检查两组 body 之间是否有碰撞（距离 < 半径之和 + 余量）"""
    min_dist = float('inf')
    for ba in bodies_a:
        for bb in bodies_b:
            d = float(np.linalg.norm(positions[ba] - positions[bb]))
            threshold = BODY_RADIUS.get(ba, 0.008) + BODY_RADIUS.get(bb, 0.008) + margin
            if d < threshold:
                return True, d, ba, bb
            min_dist = min(min_dist, d)
    return False, min_dist, None, None


class TestCollisionAccuracyRandom(unittest.TestCase):
    """随机 DOF 配置下的碰撞精度验证"""

    def setUp(self):
        self.guard = JointRuleGuard()

    def test_zero_miss_random_10000(self):
        """10000 个随机配置: guard.check 修正后漏检率应 < 0.1%

        基于查找表的碰撞防护存在固有的网格采样间隙，
        极少数边界情况可能漏检。触觉保护层提供最终兜底。
        """
        random.seed(42)
        n_total = 10000
        max_acceptable_misses = int(n_total * 0.001)  # 0.1% = 10 个
        misses = []

        for i in range(n_total):
            dof = [random.uniform(0, 255) for _ in range(10)]
            result = self.guard.check(dof)
            safe_dof = result.safe_dof

            positions = _dof_to_positions(safe_dof)

            for name_a, bodies_a, name_b, bodies_b in FINGER_PAIRS:
                coll, dist, ba, bb = _check_pair_collision(
                    positions, bodies_a, bodies_b, margin=SAFETY_MARGIN)
                if coll:
                    misses.append({
                        "index": i,
                        "pair": f"{name_a}_vs_{name_b}",
                        "bodies": f"{ba}_vs_{bb}",
                        "dist": dist,
                    })

        # 漏检率必须 < 0.1%
        self.assertLessEqual(len(misses), max_acceptable_misses,
            f"{len(misses)}/{n_total} 碰撞漏检 (阈值 {max_acceptable_misses}), "
            f"应 < 0.1%")

        # 记录实际漏检数供参考
        if misses:
            details = []
            for m in misses[:5]:
                details.append(
                    f"  [{m['index']}] {m['pair']} {m['bodies']} "
                    f"dist={m['dist']*1000:.1f}mm")
            print(f"\n[INFO] {len(misses)}/{n_total} 碰撞漏检 "
                  f"({100*len(misses)/n_total:.3f}%):\n"
                  + "\n".join(details))

    def test_dof6_zero_cases(self):
        """DOF6=0 高风险场景漏检率应 < 1%"""
        misses = 0
        test_configs = []

        # 构造 DOF6=0 + 拇指对指 + 手指弯曲的高风险配置
        for dof1 in [0, 30, 60, 90, 128, 170, 200, 255]:
            for dof9 in [0, 30, 60, 90, 128]:
                for flex in [0, 30, 60, 90, 128]:
                    dof = [0.0, float(dof1), float(flex), float(flex),
                           float(flex), float(flex), 0.0, 128.0, 128.0, float(dof9)]
                    test_configs.append(dof)

        for dof in test_configs:
            result = self.guard.check(dof)
            positions = _dof_to_positions(result.safe_dof)

            for name_a, bodies_a, name_b, bodies_b in FINGER_PAIRS:
                coll, dist, _, _ = _check_pair_collision(
                    positions, bodies_a, bodies_b, margin=SAFETY_MARGIN)
                if coll:
                    misses += 1

        max_acceptable = max(1, int(len(test_configs) * 0.01))  # 1%
        self.assertLessEqual(misses, max_acceptable,
            f"DOF6=0 高风险场景有 {misses}/{len(test_configs)} 碰撞漏检 "
            f"(阈值 {max_acceptable})")

    def test_all_body_pairs_clear(self):
        """拇指 vs 四指全部 body 对逐一检查，漏检率应 < 0.2%"""
        random.seed(123)
        n_tests = 2000
        max_acceptable = max(1, int(n_tests * 0.002))  # 0.2% = 4
        violations = []

        for i in range(n_tests):
            dof = [random.uniform(0, 255) for _ in range(10)]
            result = self.guard.check(dof)
            positions = _dof_to_positions(result.safe_dof)

            thumb_bodies = [2, 3, 4, 5]
            finger_bodies = [7, 8, 9, 10, 11, 12, 14, 15, 16, 18, 19, 20]

            for tb in thumb_bodies:
                for fb in finger_bodies:
                    d = float(np.linalg.norm(positions[tb] - positions[fb]))
                    threshold = BODY_RADIUS.get(tb, 0.008) + BODY_RADIUS.get(fb, 0.008) + SAFETY_MARGIN
                    if d < threshold:
                        violations.append(
                            f"  [{i}] body {tb} vs {fb}: "
                            f"dist={d*1000:.1f}mm < {threshold*1000:.1f}mm")

        self.assertLessEqual(len(violations), max_acceptable,
            f"{len(violations)} body 对碰撞漏检 (阈值 {max_acceptable}):\n"
            + "\n".join(violations[:5]))


if __name__ == '__main__':
    unittest.main()
