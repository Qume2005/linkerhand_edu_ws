#!/usr/bin/env python3
"""ThumbRule.query_dof0_limit() 单元测试 — TDD

query_dof0_limit() 是纯查询：给定 (DOF1, DOF9, 四指弯曲度)，返回 DOF0 安全下限。
不做任何修改。
"""

import unittest

from l10_hand_gateway.collision_guard import ThumbRule


def _make_mock_tables(lookup_overrides=None):
    """构造最小 mock 查找表，便于测试。

    默认只有 thumb_vs_index 有一条有效条目。
    其他三根手指的查找表为空（无碰撞风险）。
    """
    base_index = {
        "finger": "index",
        "resolution": 4,
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
        "lookup": {
            # DOF1=0, DOF9=0, flex=0 → DOF0 >= 50 才安全
            "0,0,0": 50.0,
            # DOF1=0, DOF9=0, flex=1 → DOF0 >= 30
            "0,0,1": 30.0,
            # DOF1=1, DOF9=0, flex=0 → DOF0 >= 100
            "1,0,0": 100.0,
        },
    }
    if lookup_overrides:
        base_index["lookup"].update(lookup_overrides)

    empty_finger = {
        "resolution": 4,
        "dof1_samples": [0.0, 85.0, 170.0, 255.0],
        "dof9_samples": [0.0, 85.0, 170.0, 255.0],
        "flex_samples": [0.0, 85.0, 170.0, 255.0],
        "lookup": {},
    }

    return {
        "thumb_vs_index": base_index,
        "thumb_vs_middle": dict(empty_finger, finger="middle"),
        "thumb_vs_ring": dict(empty_finger, finger="ring"),
        "thumb_vs_pinky": dict(empty_finger, finger="pinky"),
        "pinky_ring_lateral": {
            "resolution": 4,
            "dof7_samples": [0.0, 85.0, 170.0, 255.0],
            "dof8_samples": [0.0, 85.0, 170.0, 255.0],
            "collision_map": {},
        },
    }


class TestQueryDof0LimitBasic(unittest.TestCase):
    """query_dof0_limit 基本行为"""

    def setUp(self):
        self.tables = _make_mock_tables()
        self.rule = ThumbRule(tables=self.tables)

    def test_returns_float(self):
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[0.0, 85.0, 170.0, 255.0])
        self.assertIsInstance(result, float)

    def test_no_collision_returns_zero(self):
        """无碰撞风险时返回 0.0"""
        # DOF9=255 → 完全不对指，查找表无匹配
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=255.0,
            finger_flexions=[255.0, 255.0, 255.0, 255.0])
        self.assertEqual(result, 0.0)

    def test_collision_returns_limit(self):
        """存在碰撞时返回 DOF0 安全下限"""
        # DOF1=0, DOF9=0, index_flex=0 → 查找表命中 "0,0,0" = 50.0
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        self.assertGreater(result, 0.0)

    def test_exact_sample_point(self):
        """精确采样点命中查找表"""
        # DOF1=0, DOF9=0, index_flex=0 → 命中 "0,0,0" = 50.0
        # 3×3×3 邻域包含 "0,0,0", "0,0,1", "1,0,0"
        # max(50.0, 30.0, 100.0) = 100.0
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(result, 100.0)


class TestQueryDof0LimitNeighborhoodSearch(unittest.TestCase):
    """3×3×3 邻域搜索行为"""

    def test_interpolated_value(self):
        """非精确采样点仍能通过邻域找到限制"""
        tables = _make_mock_tables()
        rule = ThumbRule(tables=tables)
        # DOF1=42 (在 0~85 之间), DOF9=0, index_flex=0
        # 邻域会覆盖 d1i=0 和 d1i=1 的点
        result = rule.query_dof0_limit(
            dof1_val=42.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        # 邻域包含 "0,0,0"=50 和 "1,0,0"=100, 取 max = 100
        self.assertGreaterEqual(result, 50.0)

    def test_takes_max_across_neighborhood(self):
        """邻域搜索取最大值（最严格限制）"""
        tables = _make_mock_tables({
            # 在 (2,1,1) 添加一个较低的限制
            "2,1,1": 20.0,
            # 在 (2,1,2) 添加一个较高的限制
            "2,1,2": 150.0,
        })
        rule = ThumbRule(tables=tables)
        # DOF1=170, DOF9=85, index_flex=85 → 命中 d1i=2, d9i=1, fi=1
        # 邻域 3×3×3 会包含 "2,1,1"=20 和 "2,1,2"=150
        result = rule.query_dof0_limit(
            dof1_val=170.0, dof9_val=85.0,
            finger_flexions=[85.0, 0.0, 0.0, 0.0])
        self.assertAlmostEqual(result, 150.0)


class TestQueryDof0LimitMultipleFingers(unittest.TestCase):
    """多根手指的综合限制"""

    def test_takes_max_across_fingers(self):
        """多根手指的碰撞限制取最严格的（最大值）"""
        tables = _make_mock_tables()
        # 给 middle 手指也添加碰撞数据
        tables["thumb_vs_middle"]["lookup"] = {
            "0,0,0": 200.0,  # middle 比 index 的 50 更严格
        }
        rule = ThumbRule(tables=tables)

        result = rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        # max(index=100.0, middle=200.0, ring=0, pinky=0) = 200.0
        self.assertGreaterEqual(result, 200.0)

    def test_zero_flex_no_collision(self):
        """手指不弯曲时没有碰撞（即使拇指对指）"""
        tables = _make_mock_tables()
        rule = ThumbRule(tables=tables)
        # 四指全部伸直 (flex=255)，碰撞风险为 0
        result = rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[255.0, 255.0, 255.0, 255.0])
        self.assertEqual(result, 0.0)


class TestQueryDof0LimitAccepts4Elements(unittest.TestCase):
    """finger_flexions 参数接受 4 元素列表"""

    def test_accepts_list(self):
        rule = ThumbRule(tables=_make_mock_tables())
        result = rule.query_dof0_limit(
            dof1_val=128.0, dof9_val=128.0,
            finger_flexions=[128.0, 128.0, 128.0, 128.0])
        self.assertIsInstance(result, float)

    def test_accepts_tuple(self):
        rule = ThumbRule(tables=_make_mock_tables())
        result = rule.query_dof0_limit(
            dof1_val=128.0, dof9_val=128.0,
            finger_flexions=(128.0, 128.0, 128.0, 128.0))
        self.assertIsInstance(result, float)


class TestQueryDof0LimitEdgeCases(unittest.TestCase):
    """边界条件"""

    def setUp(self):
        self.tables = _make_mock_tables()
        self.rule = ThumbRule(tables=self.tables)

    def test_dof1_at_max(self):
        result = self.rule.query_dof0_limit(
            dof1_val=255.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        self.assertIsInstance(result, float)

    def test_dof9_at_max(self):
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=255.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        self.assertIsInstance(result, float)

    def test_all_zeros(self):
        result = self.rule.query_dof0_limit(
            dof1_val=0.0, dof9_val=0.0,
            finger_flexions=[0.0, 0.0, 0.0, 0.0])
        self.assertGreater(result, 0.0)

    def test_all_255(self):
        result = self.rule.query_dof0_limit(
            dof1_val=255.0, dof9_val=255.0,
            finger_flexions=[255.0, 255.0, 255.0, 255.0])
        self.assertEqual(result, 0.0)


class TestQueryDof0LimitAgainstCheck(unittest.TestCase):
    """query_dof0_limit 与 check() 一致性验证"""

    def setUp(self):
        self.rule = ThumbRule()

    def test_matches_check_for_open_hand(self):
        """张开手: query 返回 0, check 不修改 DOF0"""
        dof = [255.0] * 10
        limit = self.rule.query_dof0_limit(
            dof1_val=dof[1], dof9_val=dof[9],
            finger_flexions=[dof[2], dof[3], dof[4], dof[5]])
        safe, _ = self.rule.check(dof)
        if limit == 0.0:
            self.assertEqual(safe[0], dof[0])
        else:
            self.assertGreaterEqual(safe[0], limit)

    def test_matches_check_for_opposed_thumb(self):
        """对指拇指: query 和 check 结果一致"""
        dof = [0.0, 128.0, 50.0, 50.0, 50.0, 50.0, 128.0, 128.0, 128.0, 0.0]
        limit = self.rule.query_dof0_limit(
            dof1_val=dof[1], dof9_val=dof[9],
            finger_flexions=[dof[2], dof[3], dof[4], dof[5]])
        safe, _ = self.rule.check(dof)
        if limit > 0.0:
            self.assertGreaterEqual(safe[0], limit)

    def test_matches_check_random_configs(self):
        """多个随机配置下 query 和 check 一致"""
        import random
        random.seed(42)
        for _ in range(20):
            dof = [random.uniform(0, 255) for _ in range(10)]
            limit = self.rule.query_dof0_limit(
                dof1_val=dof[1], dof9_val=dof[9],
                finger_flexions=[dof[2], dof[3], dof[4], dof[5]])
            safe, _ = self.rule.check(list(dof))
            if limit > 0.0:
                self.assertGreaterEqual(safe[0], limit - 0.1,
                    f"DOF0={safe[0]} < query limit={limit} for dof={dof}")
            else:
                # 无碰撞风险时 check 可能仍返回原始值
                pass


if __name__ == '__main__':
    unittest.main()
