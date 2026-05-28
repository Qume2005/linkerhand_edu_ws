#!/usr/bin/env python3
"""集成测试 — 用真实查找表验证碰撞防护效果"""

import unittest
import os
import sys
import json

_ws = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..'))
sys.path.insert(0, os.path.join(_ws, 'hand_forward_kinematics'))
sys.path.insert(0, os.path.join(_ws, 'l10_hand_gateway'))

import numpy as np
from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    expand_to_20_joints,
    compute_fk,
)
from l10_hand_gateway.collision_guard import JointRuleGuard

# 手指半径 (m)
BODY_RADIUS = {
    2: 0.0117, 3: 0.0105, 4: 0.0094, 5: 0.0090,
    7: 0.0084, 8: 0.0080, 9: 0.0079,
    10: 0.0084, 11: 0.0080, 12: 0.0079,
    14: 0.0084, 15: 0.0080, 16: 0.0079,
    18: 0.0084, 19: 0.0080, 20: 0.0079,
}

THUMB_BODIES = [2, 3, 4, 5]
FINGER_BODIES = {
    "index": [7, 8, 9], "middle": [10, 11, 12],
    "ring": [14, 15, 16], "pinky": [18, 19, 20],
}

TABLE_PATH = os.path.join(os.path.dirname(__file__), '..', 'l10_hand_gateway', 'collision_tables.json')


def dof_to_positions(dof_10):
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    positions, _ = compute_fk(joints_20)
    return positions


def check_thumb_collision(positions):
    """检查拇指是否与任何四指碰撞"""
    for name, bodies in FINGER_BODIES.items():
        for tb in THUMB_BODIES:
            for fb in bodies:
                d = float(np.linalg.norm(positions[tb] - positions[fb]))
                threshold = BODY_RADIUS[tb] + BODY_RADIUS[fb]
                if d < threshold:
                    return True, name, d * 1000
    return False, "", 0.0


def check_pinky_ring_collision(positions):
    """检查小指和无名指是否碰撞"""
    for rb in FINGER_BODIES["ring"]:
        for pb in FINGER_BODIES["pinky"]:
            d = float(np.linalg.norm(positions[rb] - positions[pb]))
            threshold = BODY_RADIUS[rb] + BODY_RADIUS[pb]
            if d < threshold:
                return True, d * 1000
    return False, 0.0


@unittest.skipUnless(os.path.exists(TABLE_PATH), "collision_tables.json not found")
class TestThumbCollisionPrevention(unittest.TestCase):
    """拇指碰撞防护集成测试 — 用真实查找表"""

    @classmethod
    def setUpClass(cls):
        with open(TABLE_PATH) as f:
            cls.tables = json.load(f)
        cls.guard = JointRuleGuard(tables=cls.tables)

    def test_full_fist_no_collision(self):
        """全弯曲并拢时拇指不碰撞四指"""
        dof = [0.0] * 10
        result = self.guard.check(dof)
        pos = dof_to_positions(result.safe_dof)
        coll, finger, dist = check_thumb_collision(pos)
        self.assertFalse(coll, f"拇指碰撞 {finger}，距离 {dist:.1f}mm")

    def test_thumb_opposed_flexed_no_collision(self):
        """拇指对指+弯曲+四指弯曲时不碰撞"""
        dof = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 128.0, 128.0, 128.0, 0.0]
        result = self.guard.check(dof)
        pos = dof_to_positions(result.safe_dof)
        coll, finger, dist = check_thumb_collision(pos)
        self.assertFalse(coll, f"拇指碰撞 {finger}，距离 {dist:.1f}mm")

    def test_open_hand_unchanged(self):
        """张开手时不被修改"""
        dof = [255.0] * 10
        result = self.guard.check(dof)
        self.assertEqual(result.safe_dof, dof)
        self.assertEqual(result.violations, [])

    def test_partial_flex_no_collision(self):
        """半弯曲+拇指对指时不碰撞"""
        dof = [64.0, 64.0, 64.0, 64.0, 64.0, 64.0, 128.0, 128.0, 128.0, 64.0]
        result = self.guard.check(dof)
        pos = dof_to_positions(result.safe_dof)
        coll, finger, dist = check_thumb_collision(pos)
        self.assertFalse(coll, f"拇指碰撞 {finger}，距离 {dist:.1f}mm")


@unittest.skipUnless(os.path.exists(TABLE_PATH), "collision_tables.json not found")
class TestPinkyRingCollisionPrevention(unittest.TestCase):
    """小指-无名指碰撞防护集成测试"""

    @classmethod
    def setUpClass(cls):
        with open(TABLE_PATH) as f:
            cls.tables = json.load(f)
        cls.guard = JointRuleGuard(tables=cls.tables)

    def test_ring_spread_pinky_not_no_collision(self):
        """无名指外展+小指不展开时不碰撞"""
        dof = [255.0] * 10
        dof[7] = 255.0  # ring 最大外展
        dof[8] = 0.0    # pinky 不展开
        result = self.guard.check(dof)
        pos = dof_to_positions(result.safe_dof)
        coll, dist = check_pinky_ring_collision(pos)
        self.assertFalse(coll, f"小指-无名指碰撞，距离 {dist:.1f}mm")

    def test_both_spread_passes(self):
        """两者都展开时不触发"""
        dof = [255.0] * 10
        dof[7] = 255.0
        dof[8] = 255.0
        result = self.guard.check(dof)
        lateral_violations = [v for v in result.violations if "pinky_ring" in v.rule_name]
        self.assertEqual(len(lateral_violations), 0)


@unittest.skipUnless(os.path.exists(TABLE_PATH), "collision_tables.json not found")
class TestGuardDoesNotOverRestrict(unittest.TestCase):
    """验证防护不会过度限制正常姿态"""

    @classmethod
    def setUpClass(cls):
        with open(TABLE_PATH) as f:
            cls.tables = json.load(f)
        cls.guard = JointRuleGuard(tables=cls.tables)

    def test_default_pose_unchanged(self):
        """默认初始位姿不被修改"""
        dof = [255.0, 200.0, 255.0, 255.0, 255.0, 255.0, 180.0, 180.0, 180.0, 41.0]
        result = self.guard.check(dof)
        self.assertEqual(result.violations, [])

    def test_pinch_not_over_restricted(self):
        """捏合手势不应被过度限制"""
        dof = [92.0, 112.0, 121.0, 0.0, 0.0, 0.0, 132.0, 0.0, 0.0, 48.0]
        result = self.guard.check(dof)
        # 捏合时拇指和食指需要能弯曲（DOF0 和 DOF2 不应被推到接近 255）
        self.assertLess(result.safe_dof[0], 200.0,
                        f"捏合时拇指弯曲被过度限制到 DOF0={result.safe_dof[0]:.1f}")
        # 食指不应被限制（不受拇指规则影响）
        self.assertLessEqual(result.safe_dof[2], 121.0)

    def test_ok_gesture_not_over_restricted(self):
        """OK 手势不应被过度限制"""
        # OK: 拇指和食指弯曲成圈，其他伸直
        dof = [80.0, 110.0, 116.0, 255.0, 255.0, 255.0, 255.0, 255.0, 255.0, 54.0]
        result = self.guard.check(dof)
        self.assertLess(result.safe_dof[0], 200.0,
                        f"OK 手势拇指被过度限制到 DOF0={result.safe_dof[0]:.1f}")


@unittest.skipUnless(os.path.exists(TABLE_PATH), "collision_tables.json not found")
class TestThumbVsEachFinger(unittest.TestCase):
    """拇指 vs 各手指独立碰撞测试"""

    @classmethod
    def setUpClass(cls):
        with open(TABLE_PATH) as f:
            cls.tables = json.load(f)
        cls.guard = JointRuleGuard(tables=cls.tables)

    def _check_thumb_vs_finger(self, finger_name, finger_bodies, flex_dof_idx):
        """拇指对指+全弯时，不碰撞指定手指"""
        dof = [0.0, 0.0, 255.0, 255.0, 255.0, 255.0, 0.0, 0.0, 0.0, 0.0]
        dof[flex_dof_idx] = 0.0  # 只弯目标手指
        result = self.guard.check(dof)
        pos = dof_to_positions(result.safe_dof)
        for tb in THUMB_BODIES:
            for fb in finger_bodies:
                d = float(np.linalg.norm(pos[tb] - pos[fb]))
                threshold = BODY_RADIUS[tb] + BODY_RADIUS[fb]
                self.assertGreaterEqual(d, threshold,
                    f"拇指 body[{tb}] 碰撞 {finger_name} body[{fb}]，距离 {d*1000:.1f}mm < {threshold*1000:.1f}mm")

    def test_thumb_vs_index_no_collision(self):
        """拇指不碰食指"""
        self._check_thumb_vs_finger("index", FINGER_BODIES["index"], 2)

    def test_thumb_vs_middle_no_collision(self):
        """拇指不碰中指"""
        self._check_thumb_vs_finger("middle", FINGER_BODIES["middle"], 3)

    def test_thumb_vs_ring_no_collision(self):
        """拇指不碰无名指"""
        self._check_thumb_vs_finger("ring", FINGER_BODIES["ring"], 4)

    def test_thumb_vs_pinky_no_collision(self):
        """拇指不碰小指"""
        self._check_thumb_vs_finger("pinky", FINGER_BODIES["pinky"], 5)


if __name__ == '__main__':
    unittest.main()
