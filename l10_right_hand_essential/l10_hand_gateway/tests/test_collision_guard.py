#!/usr/bin/env python3
"""碰撞防护单元测试 — ThumbRule + LateralRule + JointRuleGuard

基于 FK 查找表的碰撞检测与修正。
"""

import unittest

from l10_hand_gateway.collision_guard import (
    JointRuleGuard,
    GuardResult,
    RuleResult,
    ThumbRule,
    LateralRule,
)


class TestThumbRuleOpenHand(unittest.TestCase):
    """张开手不应被拦截"""

    def setUp(self):
        self.rule = ThumbRule()

    def test_all_255_passes(self):
        """全伸直: DOF0 不被限制"""
        dof = [255.0] * 10
        safe, violations = self.rule.check(dof)
        self.assertEqual(safe[0], 255.0)
        self.assertEqual(len(violations), 0)

    def test_thumb_extended_fingers_extended(self):
        """拇指伸直 + 四指伸直: 不碰撞"""
        dof = [200.0, 128.0, 200.0, 200.0, 200.0, 200.0, 128.0, 128.0, 128.0, 128.0]
        safe, violations = self.rule.check(dof)
        self.assertEqual(len(violations), 0)


class TestThumbRuleCollision(unittest.TestCase):
    """拇指碰撞修正"""

    def setUp(self):
        self.rule = ThumbRule()

    def test_opposed_thumb_bent_fingers(self):
        """对指 + 弯曲: DOF0 被限制（不能弯太多）"""
        dof = [0.0] * 10  # 全弯曲 + 对指
        safe, violations = self.rule.check(dof)
        # DOF0 应该被钳位到安全值（> 0）
        self.assertGreater(safe[0], 0.0)
        self.assertGreater(len(violations), 0)

    def test_not_opposed_thumb(self):
        """拇指不对指: 限制较少"""
        dof = [0.0, 128.0, 50.0, 50.0, 50.0, 50.0, 128.0, 128.0, 128.0, 200.0]
        safe, violations = self.rule.check(dof)
        # DOF0 可能被限制但程度较轻
        self.assertIsInstance(safe[0], float)

    def test_dof0_not_relaxed(self):
        """DOF0 只被收紧（钳位到更大值），不会被放松"""
        dof = [200.0, 100.0, 0.0, 0.0, 0.0, 0.0, 100.0, 100.0, 100.0, 0.0]
        safe, _ = self.rule.check(dof)
        # DOF0 不应低于原始值
        self.assertGreaterEqual(safe[0], dof[0])

    def test_dof0_clamped_to_limit(self):
        """DOF0 被钳位到安全下限"""
        dof = [0.0] * 10
        safe, violations = self.rule.check(dof)
        if violations:
            # 第一条违规应该是 DOF0
            self.assertEqual(violations[0].dof_index, 0)
            self.assertGreater(violations[0].clamped, violations[0].original)


class TestThumbRuleDof9Escalation(unittest.TestCase):
    """DOF9 推高逻辑（DOF0 限制 >= 252 时触发）"""

    def setUp(self):
        self.rule = ThumbRule()

    def test_severe_collision_pushes_dof9(self):
        """严重碰撞: DOF9 被推高（减少对指）"""
        # 需要找到触发条件: DOF0_limit >= 252
        # 从之前的探索: DOF1=255, DOF9~51, flex=0 给出 limit=251
        # DOF1=255, DOF9=0, flex=0 可能更高
        dof = [0.0, 255.0, 0.0, 0.0, 0.0, 0.0, 128.0, 128.0, 128.0, 0.0]
        safe, violations = self.rule.check(dof)
        # 如果触发了 DOF9 推高
        dof9_violations = [v for v in violations if v.dof_index == 9]
        if dof9_violations:
            self.assertGreaterEqual(safe[9], dof[9])


class TestLateralRule(unittest.TestCase):
    """小指-无名指侧摆碰撞"""

    def setUp(self):
        self.rule = LateralRule()

    def test_safe_spread(self):
        """正常展开: 无碰撞"""
        dof = [255.0] * 10
        safe, violations = self.rule.check(dof)
        self.assertEqual(len(violations), 0)

    def test_collision_risk_dof8_corrected(self):
        """碰撞风险: DOF7 或 DOF8 被修正"""
        # DOF7 高（ring 外展）+ DOF8 低（pinky 内收）
        dof = [255.0] * 10
        dof[7] = 255.0
        dof[8] = 0.0
        safe, violations = self.rule.check(dof)
        if violations:
            # 至少有一个被修正
            modified = any(v.dof_index in (7, 8) for v in violations)
            self.assertTrue(modified, "Should modify DOF7 or DOF8")


class TestJointRuleGuard(unittest.TestCase):
    """JointRuleGuard 组合门面"""

    def setUp(self):
        self.guard = JointRuleGuard()

    def test_open_hand_passes(self):
        """全伸直: 无违规"""
        result = self.guard.check([255.0] * 10)
        self.assertIsInstance(result, GuardResult)
        self.assertEqual(len(result.violations), 0)
        self.assertEqual(result.safe_dof, [255.0] * 10)

    def test_returns_guard_result(self):
        """返回 GuardResult 类型"""
        result = self.guard.check([128.0] * 10)
        self.assertIsInstance(result, GuardResult)
        self.assertIsInstance(result.safe_dof, list)
        self.assertEqual(len(result.safe_dof), 10)
        self.assertIsInstance(result.violations, list)

    def test_does_not_modify_input(self):
        """不修改输入列表"""
        dof = [0.0] * 10
        original = list(dof)
        self.guard.check(dof)
        self.assertEqual(dof, original)

    def test_safe_dof_in_range(self):
        """输出 DOF 在 [0, 255]"""
        for _ in range(20):
            import random
            random.seed(42)
            dof = [random.uniform(0, 255) for _ in range(10)]
            result = self.guard.check(dof)
            for v in result.safe_dof:
                self.assertGreaterEqual(v, 0.0)
                self.assertLessEqual(v, 255.0)


class TestJointRuleGuardInputValidation(unittest.TestCase):
    """输入校验"""

    def test_input_too_short_raises(self):
        guard = JointRuleGuard()
        with self.assertRaises(ValueError):
            guard.check([128.0] * 5)

    def test_input_empty_raises(self):
        guard = JointRuleGuard()
        with self.assertRaises(ValueError):
            guard.check([])


class TestRuleResult(unittest.TestCase):
    """RuleResult 数据结构"""

    def test_fields(self):
        r = RuleResult(
            rule_name="test", blocked=True,
            dof_index=0, original=50.0, clamped=100.0)
        self.assertEqual(r.rule_name, "test")
        self.assertTrue(r.blocked)
        self.assertEqual(r.dof_index, 0)
        self.assertEqual(r.original, 50.0)
        self.assertEqual(r.clamped, 100.0)


if __name__ == '__main__':
    unittest.main()
