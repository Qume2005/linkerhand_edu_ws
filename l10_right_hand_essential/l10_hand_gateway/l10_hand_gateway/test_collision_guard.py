#!/usr/bin/env python3
"""JointRuleGuard 单元测试 — 基于查找表的碰撞防护"""

import unittest
import json
import os

# 构造最小测试用查找表，不依赖真实 collision_tables.json
_MOCK_TABLES = {
    "thumb_vs_index": {
        "resolution": 4,
        "lookup": {
            # DOF1=0, DOF9=0, flex=0 → DOF0>=100 (拇指全对指+全弯+食指全弯 → 需要伸直)
            "0,0,0": 100.0,
            # DOF1=0, DOF9=0, flex=85 → DOF0>=50 (食指半弯 → 拇指可以弯多一点)
            "0,0,1": 50.0,
            # DOF1=0, DOF9=0, flex=255 → 无碰撞 (食指伸直，不记录)
        },
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
    },
    "thumb_vs_middle": {
        "resolution": 4,
        "lookup": {
            "0,0,0": 80.0,
        },
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
    },
    "thumb_vs_ring": {
        "resolution": 4,
        "lookup": {},
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
    },
    "thumb_vs_pinky": {
        "resolution": 4,
        "lookup": {},
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
    },
    "pinky_ring_lateral": {
        "resolution": 4,
        "collision_map": {
            # DOF7=255(最大外展), DOF8=0(最小展开) → 碰撞
            "3,0": True,
            # DOF7=255, DOF8=85 → 碰撞
            "3,1": True,
            # DOF7=170, DOF8=0 → 碰撞
            "2,0": True,
            # DOF7=170, DOF8=85 → 不碰撞 (不在 map 中)
            # DOF7=85, DOF8=0 → 不碰撞
        },
        "dof7_samples": [0.0, 85.0, 170.0, 255.0],
        "dof8_samples": [0.0, 85.0, 170.0, 255.0],
    },
}

from l10_hand_gateway.collision_guard import (
    JointRuleGuard, ThumbRule, LateralRule, GuardResult, RuleResult,
)


class TestThumbRuleBasic(unittest.TestCase):
    """ThumbRule 基本行为"""

    def setUp(self):
        self.guard = JointRuleGuard(tables=_MOCK_TABLES)

    def test_open_hand_passes(self):
        """全伸直不触发任何限制"""
        dof = [255.0] * 10
        result = self.guard.check(dof)
        self.assertEqual(result.violations, [])

    def test_no_collision_no_clamp(self):
        """无碰撞时不修改"""
        # DOF1=255(不在查找表中), DOF7=0/DOF8=170(远离碰撞区) → 不触发
        dof = [0.0, 255.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 170.0, 0.0]
        result = self.guard.check(dof)
        self.assertEqual(result.violations, [])


class TestThumbRuleFlexionLimit(unittest.TestCase):
    """ThumbRule DOF0 弯曲限制"""

    def setUp(self):
        self.guard = JointRuleGuard(tables=_MOCK_TABLES)

    def test_dof0_clamped_when_collision(self):
        """碰撞时 DOF0 被限制到安全值"""
        # DOF1=0, DOF9=0, index_flex=0 → DOF0 >= 100
        dof = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 128.0, 128.0, 128.0, 0.0]
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[0], 100.0)
        # 检查 DOF0 被修改
        dof0_violations = [v for v in result.violations if v.dof_index == 0]
        self.assertTrue(len(dof0_violations) > 0)

    def test_dof0_already_safe_no_clamp(self):
        """DOF0 已经安全时不修改"""
        # DOF0=150 > 100，不需要修改
        dof = [150.0, 0.0, 0.0, 0.0, 0.0, 0.0, 128.0, 128.0, 128.0, 0.0]
        result = self.guard.check(dof)
        self.assertAlmostEqual(result.safe_dof[0], 150.0)

    def test_most_restrictive_finger_wins(self):
        """多根手指同时碰撞时，取最严格的限制"""
        # 构造：只有 middle 有限制 (DOF0>=80)，index 没有限制
        # 用 DOF1=0, DOF9=0, index_flex=255(伸直，不在表中), middle_flex=0
        # thumb_vs_index 中 lookup 没有 flex=255 附近的条目 → index 无限制
        # thumb_vs_middle 中 lookup 有 "0,0,0": 80.0 → middle 限制 80
        # 邻域检查：d1i=0,d9i=0,fi(index)=3(255) → 邻域 fi in [2,3] → 无条目
        #                  fi(middle)=0(0) → 邻域 fi in [0,1] → 有 "0,0,0": 80
        tables = json.loads(json.dumps(_MOCK_TABLES))
        # 确保 index 表中 flex=255 附近没有条目
        tables["thumb_vs_index"]["lookup"] = {}
        guard = JointRuleGuard(tables=tables)

        dof = [0.0, 0.0, 255.0, 0.0, 0.0, 0.0, 0.0, 0.0, 170.0, 0.0]
        result = guard.check(dof)
        # 只有 middle 限制 DOF0>=80，所以结果应 >= 80
        self.assertGreaterEqual(result.safe_dof[0], 80.0)
        # index 不贡献限制，所以不应被 index 的 100 推高
        self.assertLess(result.safe_dof[0], 100.0)

    def test_partial_flex_less_restrictive(self):
        """弯曲度越低（越弯曲）→ DOF0 限制越严格"""
        # 用隔离的表，只有 index 有条目，且 flex 梯度明确
        tables = json.loads(json.dumps(_MOCK_TABLES))
        tables["thumb_vs_index"]["lookup"] = {
            "1,1,1": 50.0,   # DOF1=85, DOF9=85, flex=85 → DOF0>=50
            "1,1,2": 20.0,   # DOF1=85, DOF9=85, flex=170 → DOF0>=20
        }
        tables["thumb_vs_middle"]["lookup"] = {}
        guard = JointRuleGuard(tables=tables)

        # flex=85 (index=1) → 查 flex bucket 1, 邻域只命中 "1,1,1": 50
        dof_half = [0.0, 85.0, 85.0, 255.0, 255.0, 255.0, 0.0, 0.0, 170.0, 85.0]
        r_half = guard.check(dof_half)
        # flex=170 (index=2) → 查 flex bucket 2, 邻域只命中 "1,1,2": 20
        dof_light = [0.0, 85.0, 170.0, 255.0, 255.0, 255.0, 0.0, 0.0, 170.0, 85.0]
        r_light = guard.check(dof_light)

        # 弯曲度更大（85 < 170）→ 限制更严（r_half 的 DOF0 >= r_light 的 DOF0）
        self.assertGreaterEqual(r_half.safe_dof[0], r_light.safe_dof[0])


class TestThumbRuleOppositionFallback(unittest.TestCase):
    """ThumbRule DOF9 对指回退"""

    def test_extreme_collision_limits_dof9(self):
        """极端碰撞（DOF0 限制 >= 252）时限制 DOF9"""
        # 构造极端查找表
        extreme_tables = json.loads(json.dumps(_MOCK_TABLES))
        extreme_tables["thumb_vs_index"]["lookup"]["0,0,0"] = 254.0
        guard = JointRuleGuard(tables=extreme_tables)

        dof = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 128.0, 128.0, 128.0, 0.0]
        result = guard.check(dof)
        # DOF0 应被限制到 254
        self.assertGreaterEqual(result.safe_dof[0], 254.0)
        # DOF9 应被推向 255
        self.assertGreater(result.safe_dof[9], 0.0)
        dof9_violations = [v for v in result.violations if v.dof_index == 9]
        self.assertTrue(len(dof9_violations) > 0)


class TestLateralRuleBasic(unittest.TestCase):
    """LateralRule 基本行为"""

    def setUp(self):
        self.guard = JointRuleGuard(tables=_MOCK_TABLES)

    def test_safe_combination_passes(self):
        """安全侧摆组合不触发"""
        # DOF7=0, DOF8=170 → 不在碰撞 map 中
        dof = [255.0] * 10
        dof[7] = 0.0
        dof[8] = 170.0
        result = self.guard.check(dof)
        lateral_violations = [v for v in result.violations if "pinky_ring" in v.rule_name]
        self.assertEqual(len(lateral_violations), 0)

    def test_collision_clamps_dof7_or_dof8(self):
        """碰撞时修改 DOF7 或 DOF8"""
        # DOF7=255(最大外展), DOF8=0(最小展开) → 碰撞
        dof = [255.0] * 10
        dof[7] = 255.0
        dof[8] = 0.0
        result = self.guard.check(dof)
        lateral_violations = [v for v in result.violations if "pinky_ring" in v.rule_name]
        self.assertTrue(len(lateral_violations) > 0)
        # 应该是 DOF7 降低了或 DOF8 升高了
        d7_changed = result.safe_dof[7] != 255.0
        d8_changed = result.safe_dof[8] != 0.0
        self.assertTrue(d7_changed or d8_changed)


class TestFindNearestIndex(unittest.TestCase):
    """_find_nearest_index 边界条件"""

    def test_exact_match(self):
        from l10_hand_gateway.collision_guard import _find_nearest_index
        samples = [0.0, 85.0, 170.0, 255.0]
        self.assertEqual(_find_nearest_index(samples, 85.0), 1)

    def test_between_samples(self):
        from l10_hand_gateway.collision_guard import _find_nearest_index
        samples = [0.0, 85.0, 170.0, 255.0]
        # 42.5 → 等距到 0 和 85，应返回更小的索引
        idx = _find_nearest_index(samples, 42.5)
        self.assertIn(idx, [0, 1])

    def test_below_range(self):
        from l10_hand_gateway.collision_guard import _find_nearest_index
        samples = [10.0, 50.0, 100.0]
        self.assertEqual(_find_nearest_index(samples, -5.0), 0)

    def test_above_range(self):
        from l10_hand_gateway.collision_guard import _find_nearest_index
        samples = [10.0, 50.0, 100.0]
        self.assertEqual(_find_nearest_index(samples, 300.0), 2)

    def test_single_element(self):
        from l10_hand_gateway.collision_guard import _find_nearest_index
        self.assertEqual(_find_nearest_index([42.0], 0.0), 0)
        self.assertEqual(_find_nearest_index([42.0], 100.0), 0)


class TestInputValidation(unittest.TestCase):
    """输入校验"""

    def test_too_short_raises(self):
        guard = JointRuleGuard(tables=_MOCK_TABLES)
        with self.assertRaises(ValueError):
            guard.check([128.0] * 5)

    def test_empty_raises(self):
        guard = JointRuleGuard(tables=_MOCK_TABLES)
        with self.assertRaises(ValueError):
            guard.check([])

    def test_output_never_exceeds_range(self):
        """碰撞修正后 DOF 值始终在 [0, 255]"""
        guard = JointRuleGuard(tables=_MOCK_TABLES)
        # 测试碰撞场景（会被修正）和非碰撞场景
        for dof in [
            [0.0] * 10,                    # 全弯曲 → 必触发修正
            [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 255.0, 0.0, 0.0],  # 侧摆碰撞
            [255.0] * 10,                  # 不触发
            [150.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 170.0, 0.0],  # 混合
        ]:
            result = guard.check(dof)
            for i, v in enumerate(result.safe_dof):
                self.assertGreaterEqual(v, 0.0, f"DOF[{i}] < 0: {v}")
                self.assertLessEqual(v, 255.0, f"DOF[{i}] > 255: {v}")


class TestGuardResultStructure(unittest.TestCase):
    """GuardResult 结构正确性"""

    def test_violations_have_correct_fields(self):
        guard = JointRuleGuard(tables=_MOCK_TABLES)
        dof = [0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 128.0, 255.0, 0.0, 0.0]
        result = guard.check(dof)
        for v in result.violations:
            self.assertIsInstance(v, RuleResult)
            self.assertTrue(v.blocked)
            self.assertGreaterEqual(v.dof_index, 0)
            self.assertLess(v.dof_index, 10)
            self.assertNotEqual(v.original, v.clamped)


if __name__ == '__main__':
    unittest.main()
