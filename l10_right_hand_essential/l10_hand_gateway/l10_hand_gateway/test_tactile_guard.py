#!/usr/bin/env python3
"""TactileGuard 单元测试 — 触觉紧急停止"""

import unittest
import json
import time

from l10_hand_gateway.tactile_guard import TactileGuard, TactileResult


def _make_pressures(values):
    """构造 5 元素压力列表 (每指总压力)。"""
    return list(values)


class TestFreezeBehavior(unittest.TestCase):
    """retreat_units=0 时：冻结手指弯曲 DOF"""

    def setUp(self):
        self.guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                                  freeze_duration=2.0)

    def test_no_pressure_no_freeze(self):
        """无压力时 DOF 不被修改"""
        dof = [100.0] * 10
        result = self.guard.filter(dof)
        self.assertEqual(result.safe_dof, dof)
        self.assertEqual(result.frozen_fingers, set())

    def test_below_threshold_no_freeze(self):
        """压力低于阈值时不冻结"""
        self.guard.update_forces(_make_pressures([140.0, 0, 0, 0, 0]))
        result = self.guard.filter([100.0] * 10)
        self.assertEqual(result.frozen_fingers, set())

    def test_above_threshold_freezes_finger(self):
        """压力超阈值时冻结对应手指"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        dof = [50.0] * 10
        result = self.guard.filter(dof)
        self.assertIn(0, result.frozen_fingers)
        self.assertGreaterEqual(result.safe_dof[0], 50.0)

    def test_freeze_prevents_further_flexion(self):
        """冻结后不允许更弯（DOF 值更小）"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result1 = self.guard.filter([100.0] * 10)
        frozen_dof0 = result1.safe_dof[0]

        result2 = self.guard.filter([50.0] * 10)
        self.assertGreaterEqual(result2.safe_dof[0], frozen_dof0)

    def test_freeze_allows_extension(self):
        """冻结后允许伸直（DOF 值更大）"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        self.guard.filter([100.0] * 10)

        result = self.guard.filter([200.0, 100.0, 100.0, 100.0, 100.0,
                                    100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertAlmostEqual(result.safe_dof[0], 200.0)

    def test_freeze_does_not_affect_other_fingers(self):
        """冻结拇指不影响其他手指"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result = self.guard.filter([100.0] * 10)
        self.assertEqual(result.frozen_fingers, {0})
        self.assertEqual(result.safe_dof[2], 100.0)

    def test_multiple_fingers_freeze(self):
        """多根手指同时超阈值时都冻结"""
        self.guard.update_forces(_make_pressures([200.0, 0, 200.0, 0, 200.0]))
        result = self.guard.filter([50.0] * 10)
        self.assertEqual(result.frozen_fingers, {0, 2, 4})

    def test_lateral_dof_not_frozen(self):
        """冻结时不锁定侧摆 DOF"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        dof = [100.0, 50.0, 100.0, 100.0, 100.0, 100.0,
               100.0, 100.0, 100.0, 50.0]
        result = self.guard.filter(dof)
        self.assertAlmostEqual(result.safe_dof[1], 50.0)
        self.assertAlmostEqual(result.safe_dof[9], 50.0)

    def test_thumb_freeze_locks_dof0(self):
        """拇指冻结锁定 DOF0"""
        self.guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        self.guard.filter([100.0] * 10)
        result = self.guard.filter([50.0] * 10)
        self.assertGreaterEqual(result.safe_dof[0], 100.0)

    def test_index_freeze_locks_dof2(self):
        """食指冻结锁定 DOF2"""
        self.guard.update_forces(_make_pressures([0, 200.0, 0, 0, 0]))
        self.guard.filter([100.0] * 10)
        result = self.guard.filter([100.0, 100.0, 50.0, 100.0, 100.0,
                                    100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertGreaterEqual(result.safe_dof[2], 100.0)

    def test_middle_freeze_locks_dof3(self):
        """中指冻结锁定 DOF3"""
        self.guard.update_forces(_make_pressures([0, 0, 200.0, 0, 0]))
        result = self.guard.filter([100.0] * 10)
        self.assertIn(2, result.frozen_fingers)
        result2 = self.guard.filter([100.0, 100.0, 100.0, 50.0, 100.0,
                                     100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertGreaterEqual(result2.safe_dof[3], 100.0)

    def test_ring_freeze_locks_dof4(self):
        """无名指冻结锁定 DOF4"""
        self.guard.update_forces(_make_pressures([0, 0, 0, 200.0, 0]))
        result = self.guard.filter([100.0] * 10)
        self.assertIn(3, result.frozen_fingers)
        result2 = self.guard.filter([100.0, 100.0, 100.0, 100.0, 50.0,
                                     100.0, 100.0, 100.0, 100.0, 100.0])
        self.assertGreaterEqual(result2.safe_dof[4], 100.0)

    def test_pinky_freeze_locks_dof5(self):
        """小指冻结锁定 DOF5"""
        self.guard.update_forces(_make_pressures([0, 0, 0, 0, 200.0]))
        result = self.guard.filter([100.0] * 10)
        self.assertIn(4, result.frozen_fingers)
        result2 = self.guard.filter([100.0, 100.0, 100.0, 100.0, 100.0,
                                     50.0, 100.0, 100.0, 100.0, 100.0])
        self.assertGreaterEqual(result2.safe_dof[5], 100.0)


class TestRetreatBehavior(unittest.TestCase):
    """retreat_units > 0 时：冻结 + 回退"""

    def test_retreat_extends_finger(self):
        """回退将弯曲 DOF 向伸直方向移动"""
        guard = TactileGuard(threshold=150.0, retreat_units=20.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertAlmostEqual(result.safe_dof[0], 120.0)

    def test_retreat_clamps_at_255(self):
        """回退不超过 255"""
        guard = TactileGuard(threshold=150.0, retreat_units=200.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertLessEqual(result.safe_dof[0], 255.0)

    def test_retreat_then_freeze_at_retreated_position(self):
        """回退后在回退位置冻结"""
        guard = TactileGuard(threshold=150.0, retreat_units=20.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result1 = guard.filter([100.0] * 10)
        retreated_dof0 = result1.safe_dof[0]

        result2 = guard.filter([50.0] * 10)
        self.assertGreaterEqual(result2.safe_dof[0], retreated_dof0)

    def test_retreat_zero_same_as_freeze(self):
        """retreat=0 时等价于纯冻结"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertAlmostEqual(result.safe_dof[0], 100.0)


class TestAutoUnfreeze(unittest.TestCase):
    """自动解除冻结"""

    def test_pressure_drop_unfreezes(self):
        """压力降到阈值 80% 以下时自动解除"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=5.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertIn(0, guard.frozen_fingers)

        guard.update_forces(_make_pressures([100.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertNotIn(0, guard.frozen_fingers)

    def test_pressure_still_high_stays_frozen(self):
        """压力仍在高位时不解除"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=5.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)

        guard.update_forces(_make_pressures([160.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertIn(0, guard.frozen_fingers)

    def test_timeout_refreeze_immediately(self):
        """超时解冻后压力仍高时立即重新冻结（无冷却期）"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=0.1)
        # 触发冻结
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertIn(0, guard.frozen_fingers)

        # 等待超时 → 解冻，但压力仍高 → 立即重新冻结
        time.sleep(0.2)
        guard.filter([100.0] * 10)
        self.assertIn(0, guard.frozen_fingers)


class TestManualReset(unittest.TestCase):
    """手动重置"""

    def test_reset_clears_all_freezes(self):
        """reset() 解除所有冻结"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=10.0)
        guard.update_forces(_make_pressures([200.0, 200.0, 200.0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertTrue(len(guard.frozen_fingers) > 0)

        guard.reset()
        self.assertEqual(guard.frozen_fingers, set())

    def test_after_reset_dof_not_modified(self):
        """重置后 DOF 不被限制"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=10.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)

        guard.reset()
        dof = [50.0] * 10
        result = guard.filter(dof)
        self.assertEqual(result.safe_dof, dof)

    def test_reset_allows_immediate_refreeze(self):
        """reset() 后压力仍高时立即重新冻结"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=10.0)
        guard.update_forces(_make_pressures([200.0, 0, 0, 0, 0]))
        guard.filter([100.0] * 10)
        self.assertIn(0, guard.frozen_fingers)

        # 手动重置
        guard.reset()
        self.assertEqual(guard.frozen_fingers, set())

        # 压力仍高 → 立即重新冻结
        result = guard.filter([100.0] * 10)
        self.assertIn(0, result.frozen_fingers)


class TestEdgeCases(unittest.TestCase):
    """边界条件"""

    def test_short_pressure_data(self):
        """压力数组不足 5 个元素时不崩溃"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=2.0)
        guard.update_forces([0.0, 0.0])
        result = guard.filter([100.0] * 10)
        self.assertEqual(result.frozen_fingers, set())

    def test_output_always_in_range(self):
        """过滤后 DOF 始终在 [0, 255]"""
        guard = TactileGuard(threshold=100.0, retreat_units=50.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([200.0, 200.0, 200.0, 200.0, 200.0]))
        for dof in [
            [0.0] * 10,
            [255.0] * 10,
            [100.0, 0.0, 50.0, 100.0, 150.0, 200.0, 100.0, 100.0, 100.0, 50.0],
        ]:
            result = guard.filter(dof)
            for i, v in enumerate(result.safe_dof):
                self.assertGreaterEqual(v, 0.0, f"DOF[{i}] < 0: {v}")
                self.assertLessEqual(v, 255.0, f"DOF[{i}] > 255: {v}")

    def test_threshold_at_boundary(self):
        """压力恰好等于阈值时触发"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([150.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertIn(0, result.frozen_fingers)

    def test_threshold_just_below(self):
        """压力恰好低于阈值时不触发"""
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=2.0)
        guard.update_forces(_make_pressures([149.9, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertNotIn(0, result.frozen_fingers)

    def test_default_threshold_triggers_on_nonzero(self):
        """默认阈值 0.1 在任意非零压力下触发"""
        guard = TactileGuard()  # 默认 threshold=0.1
        guard.update_forces(_make_pressures([1.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertIn(0, result.frozen_fingers)

    def test_zero_pressure_no_trigger_with_default(self):
        """默认阈值下零压力不触发"""
        guard = TactileGuard()
        guard.update_forces(_make_pressures([0.0, 0, 0, 0, 0]))
        result = guard.filter([100.0] * 10)
        self.assertEqual(result.frozen_fingers, set())


class TestResultStructure(unittest.TestCase):
    """TactileResult 结构正确性"""

    def test_result_has_correct_fields(self):
        guard = TactileGuard(threshold=150.0, retreat_units=0.0,
                             freeze_duration=2.0)
        result = guard.filter([100.0] * 10)
        self.assertTrue(hasattr(result, 'safe_dof'))
        self.assertTrue(hasattr(result, 'frozen_fingers'))
        self.assertIsInstance(result.safe_dof, list)
        self.assertIsInstance(result.frozen_fingers, set)


class TestMatrixParsing(unittest.TestCase):
    """验证网关从 matrix_touch JSON 提取每指最大值的逻辑"""

    @staticmethod
    def _parse_matrix_max(msg_data):
        """模拟 gateway_node._on_backend_matrix 中的解析逻辑"""
        data = json.loads(msg_data)
        return [
            max((v for row in data.get("thumb_matrix", []) for v in row), default=0.0),
            max((v for row in data.get("index_matrix", []) for v in row), default=0.0),
            max((v for row in data.get("middle_matrix", []) for v in row), default=0.0),
            max((v for row in data.get("ring_matrix", []) for v in row), default=0.0),
            max((v for row in data.get("little_matrix", []) for v in row), default=0.0),
        ]

    def test_all_zero(self):
        """全零矩阵不触发"""
        zeros = [[0] * 6 for _ in range(12)]
        msg = json.dumps({
            "thumb_matrix": zeros, "index_matrix": zeros,
            "middle_matrix": zeros, "ring_matrix": zeros,
            "little_matrix": zeros,
        })
        result = self._parse_matrix_max(msg)
        self.assertEqual(result, [0.0, 0.0, 0.0, 0.0, 0.0])

    def test_single_cell_nonzero(self):
        """单格非零 → 最大值为该格"""
        matrix = [[0] * 6 for _ in range(12)]
        matrix[3][2] = 42.0
        zeros = [[0] * 6 for _ in range(12)]
        msg = json.dumps({
            "thumb_matrix": matrix,
            "index_matrix": zeros, "middle_matrix": zeros,
            "ring_matrix": zeros, "little_matrix": zeros,
        })
        result = self._parse_matrix_max(msg)
        self.assertEqual(result[0], 42.0)
        self.assertEqual(result[1], 0.0)

    def test_multiple_cells_takes_max(self):
        """多格有值取最大"""
        matrix = [[0] * 6 for _ in range(12)]
        matrix[0][0] = 10.0
        matrix[5][3] = 200.0
        matrix[11][5] = 50.0
        zeros = [[0] * 6 for _ in range(12)]
        msg = json.dumps({
            "thumb_matrix": zeros, "index_matrix": matrix,
            "middle_matrix": zeros, "ring_matrix": zeros,
            "little_matrix": zeros,
        })
        result = self._parse_matrix_max(msg)
        self.assertEqual(result[1], 200.0)

    def test_each_finger_independent(self):
        """各手指独立计算"""
        matrices = {}
        for i, name in enumerate(["thumb", "index", "middle", "ring", "little"]):
            m = [[0] * 6 for _ in range(12)]
            m[0][0] = (i + 1) * 50.0  # 50, 100, 150, 200, 250
            matrices[f"{name}_matrix"] = m
        msg = json.dumps(matrices)
        result = self._parse_matrix_max(msg)
        self.assertEqual(result, [50.0, 100.0, 150.0, 200.0, 250.0])

    def test_missing_key_defaults_zero(self):
        """缺少某个手指的矩阵时不崩溃，默认 0"""
        msg = json.dumps({"thumb_matrix": [[1] * 6] * 12})
        result = self._parse_matrix_max(msg)
        self.assertEqual(result[0], 1.0)
        self.assertEqual(result[1], 0.0)

    def test_end_to_end_with_guard(self):
        """解析 + guard 联动：矩阵有值 → 冻结"""
        matrix = [[0] * 6 for _ in range(12)]
        matrix[0][0] = 1.0  # 一个格有最小值
        zeros = [[0] * 6 for _ in range(12)]
        msg = json.dumps({
            "thumb_matrix": matrix,
            "index_matrix": zeros, "middle_matrix": zeros,
            "ring_matrix": zeros, "little_matrix": zeros,
        })
        pressures = self._parse_matrix_max(msg)
        guard = TactileGuard()  # 默认 threshold=0.1
        guard.update_forces(pressures)
        result = guard.filter([100.0] * 10)
        self.assertIn(0, result.frozen_fingers)


if __name__ == '__main__':
    unittest.main()
