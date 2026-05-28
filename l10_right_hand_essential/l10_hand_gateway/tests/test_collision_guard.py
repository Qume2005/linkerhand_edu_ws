#!/usr/bin/env python3
"""JointRuleGuard 单元测试 — TDD"""

import unittest

from l10_hand_gateway.collision_guard import JointRuleGuard, GuardResult


class TestJointRuleGuardNoRules(unittest.TestCase):
    """无规则时行为"""

    def test_no_rules_no_change(self):
        guard = JointRuleGuard(rules=[])
        dof = [128.0] * 10
        result = guard.check(dof)
        self.assertEqual(result.safe_dof, dof)
        self.assertEqual(result.violations, [])

    def test_none_rules_uses_defaults(self):
        guard = JointRuleGuard(rules=None)
        self.assertTrue(len(guard._rules) > 0)


class TestJointRuleGuardOpenHand(unittest.TestCase):
    """张开手不应被拦截"""

    def setUp(self):
        self.guard = JointRuleGuard(rules=None)

    def test_open_hand_passes(self):
        dof = [255.0] * 10
        result = self.guard.check(dof)
        self.assertEqual(result.safe_dof, dof)
        self.assertEqual(result.violations, [])


class TestJointRuleGuardAdjacentFingers(unittest.TestCase):
    """相邻手指碰撞规则测试"""

    def setUp(self):
        # 使用简化的单条规则便于测试
        self.guard = JointRuleGuard(rules=[
            {
                "name": "index_middle",
                "spread_dof": 6,
                "flex_dofs": [2, 3],
                "spread_threshold": 128,
                "min_flex_limit": 50,
                "max_flex_limit": 0,
            }
        ])

    def test_spread_ok_allows_full_flex(self):
        """展开足够时允许最大弯曲"""
        dof = [255.0] * 10
        dof[2] = 0.0   # index 全弯
        dof[3] = 0.0   # middle 全弯
        dof[6] = 200.0  # index lateral 大展开
        result = self.guard.check(dof)
        self.assertAlmostEqual(result.safe_dof[2], 0.0)
        self.assertAlmostEqual(result.safe_dof[3], 0.0)
        self.assertEqual(result.violations, [])

    def test_spread_low_clamps_flex(self):
        """展开不足时弯曲被限制"""
        dof = [255.0] * 10
        dof[2] = 0.0   # index 全弯
        dof[3] = 0.0   # middle 全弯
        dof[6] = 0.0    # index lateral 完全并拢
        result = self.guard.check(dof)
        # 弯曲 DOF 值应被抬高（限制弯曲），不低于 min_flex_limit=50
        self.assertGreaterEqual(result.safe_dof[2], 50.0)
        self.assertGreaterEqual(result.safe_dof[3], 50.0)
        self.assertTrue(len(result.violations) > 0)

    def test_partial_spread_interpolates(self):
        """部分展开时弯曲限制线性插值"""
        dof = [255.0] * 10
        dof[2] = 0.0
        dof[3] = 0.0
        dof[6] = 64.0  # 一半阈值
        result = self.guard.check(dof)
        # spread=64, threshold=128, min_limit=50, max_limit=0
        # 插值: limit = min_limit + (spread / threshold) * (max_limit - min_limit)
        #      = 50 + (64/128) * (0 - 50) = 50 - 25 = 25
        expected_limit = 50.0 + (64.0 / 128.0) * (0.0 - 50.0)
        self.assertAlmostEqual(result.safe_dof[2], expected_limit, places=2)
        self.assertAlmostEqual(result.safe_dof[3], expected_limit, places=2)

    def test_rule_does_not_relax(self):
        """规则只收紧不放松：目标已比限制更安全时不修改"""
        dof = [255.0] * 10
        dof[2] = 100.0  # index 只弯一点点
        dof[3] = 200.0  # middle 几乎不弯
        dof[6] = 0.0    # 完全并拢 → min_flex_limit=50
        result = self.guard.check(dof)
        # 100 > 50 和 200 > 50，都不需要限制
        self.assertAlmostEqual(result.safe_dof[2], 100.0)
        self.assertAlmostEqual(result.safe_dof[3], 200.0)
        self.assertEqual(result.violations, [])

    def test_one_flex_dof_violated_other_ok(self):
        """同一规则中一个 DOF 违规，另一个正常"""
        dof = [255.0] * 10
        dof[2] = 0.0    # index 全弯 → 需要限制
        dof[3] = 200.0  # middle 几乎不弯 → 不需要限制
        dof[6] = 0.0    # 并拢
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[2], 50.0)
        self.assertAlmostEqual(result.safe_dof[3], 200.0)


class TestJointRuleGuardMultipleRules(unittest.TestCase):
    """多条规则独立生效"""

    def setUp(self):
        self.guard = JointRuleGuard(rules=[
            {
                "name": "index_middle",
                "spread_dof": 6,
                "flex_dofs": [2, 3],
                "spread_threshold": 128,
                "min_flex_limit": 50,
                "max_flex_limit": 0,
            },
            {
                "name": "pinky_ring",
                "spread_dof": 8,
                "flex_dofs": [4, 5],
                "spread_threshold": 128,
                "min_flex_limit": 50,
                "max_flex_limit": 0,
            },
        ])

    def test_both_rules_trigger_independently(self):
        """两条规则各自触发各自的 DOF"""
        dof = [255.0] * 10
        dof[2] = 0.0  # index 全弯
        dof[3] = 0.0  # middle 全弯
        dof[4] = 0.0  # ring 全弯
        dof[5] = 0.0  # pinky 全弯
        dof[6] = 0.0  # index 并拢
        dof[8] = 0.0  # pinky 并拢
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[2], 50.0)
        self.assertGreaterEqual(result.safe_dof[3], 50.0)
        self.assertGreaterEqual(result.safe_dof[4], 50.0)
        self.assertGreaterEqual(result.safe_dof[5], 50.0)
        self.assertEqual(len(result.violations), 4)

    def test_one_rule_triggers_other_passes(self):
        """一条触发，另一条不触发"""
        dof = [255.0] * 10
        dof[2] = 0.0
        dof[3] = 0.0
        dof[6] = 0.0   # index_middle 规则触发
        # pinky_ring 不触发: spread_dof(8)=255 >= threshold
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[2], 50.0)
        self.assertGreaterEqual(result.safe_dof[3], 50.0)
        self.assertAlmostEqual(result.safe_dof[4], 255.0)
        self.assertAlmostEqual(result.safe_dof[5], 255.0)


class TestJointRuleGuardThumbCollision(unittest.TestCase):
    """拇指 vs 食指/中指碰撞规则"""

    def setUp(self):
        self.guard = JointRuleGuard(rules=[
            {
                "name": "thumb_index_middle",
                "condition_dofs": {9: 100, 0: 100},
                "flex_dofs": [2, 3],
                "flex_limit": 80,
            }
        ])

    def test_thumb_opposition_triggers(self):
        """拇指对指+弯曲时限制食指/中指"""
        dof = [255.0] * 10
        dof[0] = 50.0   # thumb flexed (低值=弯曲)
        dof[9] = 50.0   # thumb opposed (低值=对指)
        dof[2] = 0.0    # index 全弯
        dof[3] = 0.0    # middle 全弯
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[2], 80.0)
        self.assertGreaterEqual(result.safe_dof[3], 80.0)

    def test_thumb_no_opposition_passes(self):
        """拇指不对指时食指/中指不受限"""
        dof = [255.0] * 10
        dof[0] = 50.0   # thumb flexed
        dof[9] = 200.0  # thumb NOT opposed
        dof[2] = 0.0    # index 全弯
        dof[3] = 0.0    # middle 全弯
        result = self.guard.check(dof)
        self.assertAlmostEqual(result.safe_dof[2], 0.0)
        self.assertAlmostEqual(result.safe_dof[3], 0.0)

    def test_thumb_not_flexed_passes(self):
        """拇指弯曲度不够时不触发"""
        dof = [255.0] * 10
        dof[0] = 200.0  # thumb NOT flexed
        dof[9] = 50.0   # thumb opposed
        dof[2] = 0.0
        dof[3] = 0.0
        result = self.guard.check(dof)
        self.assertAlmostEqual(result.safe_dof[2], 0.0)
        self.assertAlmostEqual(result.safe_dof[3], 0.0)


class TestJointRuleGuardBoundaryConditions(unittest.TestCase):
    """边界条件"""

    def setUp(self):
        self.guard = JointRuleGuard(rules=[
            {
                "name": "index_middle",
                "spread_dof": 6,
                "flex_dofs": [2, 3],
                "spread_threshold": 128,
                "min_flex_limit": 50,
                "max_flex_limit": 0,
            }
        ])

    def test_dof_all_zeros(self):
        """全 0（全弯曲并拢）应被限制"""
        dof = [0.0] * 10
        result = self.guard.check(dof)
        # flex DOF 2,3 应被限制
        self.assertGreaterEqual(result.safe_dof[2], 50.0)
        self.assertGreaterEqual(result.safe_dof[3], 50.0)

    def test_dof_all_255(self):
        """全 255（全伸直）不应被限制"""
        dof = [255.0] * 10
        result = self.guard.check(dof)
        self.assertEqual(result.safe_dof, dof)

    def test_spread_exactly_at_threshold(self):
        """spread 恰好等于阈值时不触发（>= threshold 不触发）"""
        dof = [255.0] * 10
        dof[2] = 0.0
        dof[3] = 0.0
        dof[6] = 128.0  # 恰好等于阈值
        result = self.guard.check(dof)
        # threshold=128, max_flex_limit=0, 所以 limit=0, 不限制
        self.assertAlmostEqual(result.safe_dof[2], 0.0)
        self.assertAlmostEqual(result.safe_dof[3], 0.0)

    def test_spread_just_below_threshold(self):
        """spread 刚好低于阈值时触发"""
        dof = [255.0] * 10
        dof[2] = 0.0
        dof[3] = 0.0
        dof[6] = 127.0
        result = self.guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[2], 0.0)
        # 应有某种限制（limit > 0 因为 spread < threshold）
        # limit = 50 + (127/128)*(0-50) ≈ 0.39
        self.assertTrue(len(result.violations) > 0)

    def test_flex_exactly_at_limit(self):
        """flex 值恰好等于限制值时不修改"""
        dof = [255.0] * 10
        dof[6] = 0.0   # 并拢 → limit=50
        dof[2] = 50.0  # 恰好等于限制
        dof[3] = 50.0
        result = self.guard.check(dof)
        self.assertAlmostEqual(result.safe_dof[2], 50.0)
        self.assertAlmostEqual(result.safe_dof[3], 50.0)


class TestJointRuleGuardCustomRules(unittest.TestCase):
    """自定义规则"""

    def test_custom_single_rule(self):
        custom = [{
            "name": "custom",
            "spread_dof": 7,
            "flex_dofs": [4],
            "spread_threshold": 200,
            "min_flex_limit": 100,
            "max_flex_limit": 20,
        }]
        guard = JointRuleGuard(rules=custom)
        dof = [255.0] * 10
        dof[4] = 0.0   # ring 全弯
        dof[7] = 0.0   # ring 并拢
        result = guard.check(dof)
        self.assertGreaterEqual(result.safe_dof[4], 100.0)

    def test_default_rules_cover_all_collision_pairs(self):
        """默认规则集应覆盖所有碰撞对"""
        guard = JointRuleGuard(rules=None)
        names = [r["name"] for r in guard._rules]
        self.assertIn("index_middle", names)
        self.assertIn("ring_middle", names)
        self.assertIn("pinky_ring", names)
        self.assertIn("thumb_index_middle", names)


class TestJointRuleGuardInputValidation(unittest.TestCase):
    """输入校验"""

    def test_input_too_short_raises(self):
        guard = JointRuleGuard(rules=None)
        with self.assertRaises((ValueError, IndexError)):
            guard.check([128.0] * 5)

    def test_input_empty_raises(self):
        guard = JointRuleGuard(rules=None)
        with self.assertRaises((ValueError, IndexError)):
            guard.check([])

    def test_result_dof_clamped_to_0_255(self):
        """输出 DOF 值始终在 [0, 255]"""
        guard = JointRuleGuard(rules=None)
        dof = [255.0] * 10
        result = guard.check(dof)
        for v in result.safe_dof:
            self.assertGreaterEqual(v, 0.0)
            self.assertLessEqual(v, 255.0)


if __name__ == '__main__':
    unittest.main()
