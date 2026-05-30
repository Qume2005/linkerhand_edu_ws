#!/usr/bin/env python3
"""SpeedLimiter 单元测试 — 全局速度限制"""

import unittest
import time

from l10_hand_gateway.speed_limiter import SpeedLimiter, SpeedLimitResult


class TestUnlimitedMode(unittest.TestCase):
    """不限制模式（max_speed=None）"""

    def test_default_is_unlimited(self):
        """默认构造为无限速"""
        sl = SpeedLimiter()
        self.assertFalse(sl.is_limited)
        self.assertIsNone(sl.max_speed)

    def test_pass_through_any_dof(self):
        """无限速时直接透传任意 DOF"""
        sl = SpeedLimiter()
        for dof in [
            [0.0] * 10,
            [255.0] * 10,
            [128.0, 64.0, 200.0, 10.0, 50.0, 100.0, 180.0, 0.0, 255.0, 41.0],
        ]:
            result = sl.advance(dof)
            self.assertEqual(result.dof, dof)
            self.assertFalse(result.active)

    def test_pass_through_after_reset(self):
        """reset 后仍然无限速透传"""
        sl = SpeedLimiter()
        sl.reset([128.0] * 10)
        result = sl.advance([255.0] * 10)
        self.assertEqual(result.dof, [255.0] * 10)


class TestPercentageMapping(unittest.TestCase):
    """百分比映射正确性"""

    def test_100_percent_unlimited(self):
        """100% = 不限制"""
        sl = SpeedLimiter()
        sl.set_from_percentage(100.0)
        self.assertFalse(sl.is_limited)
        self.assertIsNone(sl.max_speed)

    def test_0_percent_slowest(self):
        """0% = 最慢 (5 units/s)"""
        sl = SpeedLimiter()
        sl.set_from_percentage(0.0)
        self.assertTrue(sl.is_limited)
        self.assertEqual(sl.max_speed, 5.0)

    def test_50_percent_moderate(self):
        """50% = 中等速度"""
        sl = SpeedLimiter()
        sl.set_from_percentage(50.0)
        self.assertTrue(sl.is_limited)
        self.assertAlmostEqual(sl.max_speed, 255.0)

    def test_25_percent(self):
        """25% = 较慢"""
        sl = SpeedLimiter()
        sl.set_from_percentage(25.0)
        self.assertAlmostEqual(sl.max_speed, 130.0)

    def test_negative_clamps_to_0(self):
        """负值钳制到 0%"""
        sl = SpeedLimiter()
        sl.set_from_percentage(-10.0)
        self.assertEqual(sl.max_speed, 5.0)

    def test_over_100_clamps_to_100(self):
        """超过 100 钳制到 100%（无限速）"""
        sl = SpeedLimiter()
        sl.set_from_percentage(150.0)
        self.assertFalse(sl.is_limited)

    def test_monotonic_mapping(self):
        """百分比越高速度越快（单调递增）"""
        sl = SpeedLimiter()
        speeds = []
        for pct in [0, 10, 25, 50, 75, 99]:
            sl.set_from_percentage(float(pct))
            speeds.append(sl.max_speed)
        for i in range(1, len(speeds)):
            self.assertGreater(speeds[i], speeds[i - 1],
                               f"pct={i * 10} speed={speeds[i]} not > pct={(i - 1) * 10} speed={speeds[i - 1]}")


class TestBasicAdvance(unittest.TestCase):
    """基本前进行为"""

    def setUp(self):
        self.sl = SpeedLimiter(max_speed=100.0)  # 100 units/s
        self.sl.reset([0.0] * 10)

    def test_no_change_when_desired_equals_current(self):
        """目标与当前位置相同时不移动"""
        result = self.sl.advance([0.0] * 10)
        self.assertEqual(result.dof, [0.0] * 10)
        self.assertFalse(result.active)

    def test_small_delta_within_limit(self):
        """变化在限速内时直接到达目标"""
        # 100 units/s * dt(~0s) ≈ 0 → 需要等一段时间
        time.sleep(0.01)  # 10ms → max_delta = 1.0
        result = self.sl.advance([0.5] * 10)
        # 0.5 < 1.0 max_delta → 应该到达
        for v in result.dof:
            self.assertAlmostEqual(v, 0.5, places=2)

    def test_large_delta_clamped(self):
        """大幅跳变被限速"""
        time.sleep(0.05)  # 50ms → max_delta ≈ 5.0
        result = self.sl.advance([255.0] * 10)
        # 不应超过 6.0 (容差考虑 sleep 精度)
        for v in result.dof:
            self.assertLessEqual(v, 6.0)
            self.assertGreaterEqual(v, 0.0)
        self.assertTrue(result.active)

    def test_direction_increasing(self):
        """向增大方向前进"""
        self.sl.reset([100.0] * 10)
        time.sleep(0.02)  # max_delta ≈ 2.0
        result = self.sl.advance([110.0] * 10)
        for v in result.dof:
            self.assertLess(v, 103.0)  # 容差 1.0
            self.assertGreater(v, 101.0)

    def test_direction_decreasing(self):
        """向减小方向前进"""
        self.sl.reset([100.0] * 10)
        time.sleep(0.02)  # max_delta ≈ 2.0
        result = self.sl.advance([90.0] * 10)
        for v in result.dof:
            self.assertGreater(v, 97.0)  # 容差 1.0
            self.assertLess(v, 99.0)


class TestConvergence(unittest.TestCase):
    """持续前进最终收敛到目标"""

    def test_converges_to_target(self):
        """多步 advance 后到达目标"""
        sl = SpeedLimiter(max_speed=500.0)
        sl.reset([0.0] * 10)

        for _ in range(20):
            time.sleep(0.05)  # max_delta = 25.0
            result = sl.advance([100.0] * 10)

        # 20 步 × 25 units = 500 units > 100，应已到达
        for v in result.dof:
            self.assertAlmostEqual(v, 100.0, places=1)

    def test_active_flag_becomes_false(self):
        """到达目标后 active 变为 False"""
        sl = SpeedLimiter(max_speed=1000.0)
        sl.reset([0.0] * 10)
        time.sleep(0.05)  # max_delta = 50.0
        sl.advance([50.0] * 10)

        # 已到达或超过目标
        time.sleep(0.01)
        result = sl.advance([50.0] * 10)
        self.assertFalse(result.active)

    def test_partial_convergence(self):
        """未到达目标时 active 为 True"""
        sl = SpeedLimiter(max_speed=10.0)  # 很慢
        sl.reset([0.0] * 10)
        time.sleep(0.01)  # max_delta = 0.1
        result = sl.advance([255.0] * 10)
        self.assertTrue(result.active)


class TestBoundaryClamping(unittest.TestCase):
    """DOF 值边界钳制"""

    def test_output_never_below_zero(self):
        """输出不低于 0"""
        sl = SpeedLimiter(max_speed=10000.0)  # 超快
        sl.reset([5.0] * 10)
        time.sleep(0.01)
        result = sl.advance([-100.0] * 10)
        for v in result.dof:
            self.assertGreaterEqual(v, 0.0)

    def test_output_never_above_255(self):
        """输出不超过 255"""
        sl = SpeedLimiter(max_speed=10000.0)
        sl.reset([250.0] * 10)
        time.sleep(0.01)
        result = sl.advance([500.0] * 10)
        for v in result.dof:
            self.assertLessEqual(v, 255.0)


class TestDtClamping(unittest.TestCase):
    """dt 上限钳制（防止暂停后跳变）"""

    def test_long_pause_no_jump(self):
        """长时间暂停后不产生大幅跳变"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([0.0] * 10)
        # 模拟长时间暂停：手动设置 _last_time
        sl._last_time = time.monotonic() - 10.0  # 10 秒前
        result = sl.advance([255.0] * 10)
        # max_delta 应被钳制到 100 * 0.2 = 20.0
        for v in result.dof:
            self.assertLessEqual(v, 20.0)


class TestReset(unittest.TestCase):
    """reset() 行为"""

    def test_reset_syncs_position(self):
        """reset 将内部位置同步到指定值"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([0.0] * 10)
        time.sleep(0.01)
        sl.advance([100.0] * 10)

        # 重置到中间位置
        sl.reset([128.0] * 10)
        time.sleep(0.01)
        result = sl.advance([130.0] * 10)
        # 从 128 开始，1ms ≈ 1 units max_delta，130-128=2 可能到达或接近
        for v in result.dof:
            self.assertGreater(v, 128.0)
            self.assertLessEqual(v, 130.0)

    def test_reset_allows_immediate_pass_through_after_unlimited(self):
        """reset 后设置无限速仍透传"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([0.0] * 10)
        sl.max_speed = None
        result = sl.advance([255.0] * 10)
        self.assertEqual(result.dof, [255.0] * 10)


class TestPerDofIndependence(unittest.TestCase):
    """各 DOF 独立限速"""

    def test_mixed_directions(self):
        """不同 DOF 可以独立向不同方向移动"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([128.0] * 10)
        time.sleep(0.01)  # max_delta ≈ 1.0

        desired = [138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0]
        result = sl.advance(desired)
        for i in range(10):
            diff = abs(result.dof[i] - 128.0)
            self.assertLess(diff, 1.5, f"DOF[{i}] moved {diff} > 1.5")

    def test_some_limited_some_free(self):
        """部分 DOF 在限速内，部分被钳制"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([0.0] * 10)
        time.sleep(0.01)  # max_delta = 1.0

        desired = [0.5, 200.0, 0.5, 200.0, 0.5, 200.0, 0.5, 200.0, 0.5, 200.0]
        result = sl.advance(desired)
        # 偶数 DOF: 0.5 < 1.0 → 到达
        for i in range(0, 10, 2):
            self.assertAlmostEqual(result.dof[i], 0.5, places=2)
        # 奇数 DOF: 200.0 >> 1.0 → 被钳制到 ~1.0
        for i in range(1, 10, 2):
            self.assertLess(result.dof[i], 1.5)


class TestResultStructure(unittest.TestCase):
    """SpeedLimitResult 结构正确性"""

    def test_has_correct_fields(self):
        sl = SpeedLimiter()
        result = sl.advance([128.0] * 10)
        self.assertTrue(hasattr(result, 'dof'))
        self.assertTrue(hasattr(result, 'active'))
        self.assertIsInstance(result.dof, list)
        self.assertIsInstance(result.active, bool)

    def test_dof_always_10_elements(self):
        sl = SpeedLimiter()
        result = sl.advance([128.0] * 10)
        self.assertEqual(len(result.dof), 10)

    def test_dof_always_in_range(self):
        """DOF 值始终在 [0, 255]"""
        sl = SpeedLimiter(max_speed=100.0)
        sl.reset([128.0] * 10)
        for desired in [
            [0.0] * 10,
            [255.0] * 10,
            [-50.0] * 10,
            [300.0] * 10,
        ]:
            time.sleep(0.01)
            result = sl.advance(desired)
            for i, v in enumerate(result.dof):
                self.assertGreaterEqual(v, 0.0, f"DOF[{i}] < 0: {v}")
                self.assertLessEqual(v, 255.0, f"DOF[{i}] > 255: {v}")


class TestMaxSpeedTransition(unittest.TestCase):
    """速度切换时的行为"""

    def test_slow_down_mid_motion(self):
        """运动中途降速：跟踪位置正确"""
        sl = SpeedLimiter(max_speed=500.0)
        sl.reset([0.0] * 10)
        time.sleep(0.02)  # max_delta = 10.0
        r1 = sl.advance([255.0] * 10)
        pos = r1.dof[0]

        # 降速到 50
        sl.max_speed = 50.0
        time.sleep(0.02)  # max_delta = 1.0
        r2 = sl.advance([255.0] * 10)
        self.assertAlmostEqual(r2.dof[0], pos + 1.0, places=1)

    def test_speed_up_mid_motion(self):
        """运动中途加速：更快到达目标"""
        sl = SpeedLimiter(max_speed=50.0)
        sl.reset([0.0] * 10)
        time.sleep(0.02)  # max_delta = 1.0
        r1 = sl.advance([255.0] * 10)
        self.assertLess(r1.dof[0], 5.0)

        # 加速
        sl.max_speed = 500.0
        time.sleep(0.05)  # max_delta = 25.0
        r2 = sl.advance([255.0] * 10)
        self.assertGreater(r2.dof[0], 20.0)

    def test_unlimited_to_limited_resets(self):
        """从无限速切换到有限速时 reset 同步位置"""
        sl = SpeedLimiter()
        # 无限速透传到 255
        sl.advance([255.0] * 10)

        # 切换到有限速并 reset
        sl.set_from_percentage(50.0)
        sl.reset([200.0] * 10)

        time.sleep(0.01)  # max_delta ≈ 2.55
        result = sl.advance([255.0] * 10)
        # 应从 200 开始前进，而不是从 255 或旧位置
        for v in result.dof:
            self.assertGreaterEqual(v, 200.0)
            self.assertLessEqual(v, 205.0)  # 约 200 + 2.55


class TestSpeedPropertyValue(unittest.TestCase):
    """max_speed 属性读写"""

    def test_constructor_sets_max_speed(self):
        sl = SpeedLimiter(max_speed=42.0)
        self.assertEqual(sl.max_speed, 42.0)

    def test_setter_updates_max_speed(self):
        sl = SpeedLimiter()
        sl.max_speed = 100.0
        self.assertEqual(sl.max_speed, 100.0)
        self.assertTrue(sl.is_limited)

    def test_set_to_none_disables(self):
        sl = SpeedLimiter(max_speed=100.0)
        sl.max_speed = None
        self.assertFalse(sl.is_limited)


class TestGetPercentage(unittest.TestCase):
    """get_percentage 与 set_from_percentage 互逆"""

    def test_round_trip_at_0(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(0.0)
        self.assertAlmostEqual(sl.get_percentage(), 0.0)

    def test_round_trip_at_50(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(50.0)
        self.assertAlmostEqual(sl.get_percentage(), 50.0)

    def test_round_trip_at_100(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(100.0)
        self.assertAlmostEqual(sl.get_percentage(), 100.0)

    def test_round_trip_at_75(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(75.0)
        self.assertAlmostEqual(sl.get_percentage(), 75.0)

    def test_default_unlimited_returns_100(self):
        sl = SpeedLimiter()
        self.assertEqual(sl.get_percentage(), 100.0)

    def test_direct_max_speed_round_trip(self):
        sl = SpeedLimiter(max_speed=130.0)
        pct = sl.get_percentage()
        sl2 = SpeedLimiter()
        sl2.set_from_percentage(pct)
        self.assertAlmostEqual(sl2.max_speed, 130.0, places=2)


class TestInputValidation(unittest.TestCase):
    """输入校验"""

    def test_advance_too_short_raises(self):
        sl = SpeedLimiter()
        with self.assertRaises(ValueError):
            sl.advance([128.0] * 5)

    def test_advance_empty_raises(self):
        sl = SpeedLimiter()
        with self.assertRaises(ValueError):
            sl.advance([])

    def test_advance_exact_length_ok(self):
        sl = SpeedLimiter()
        result = sl.advance([128.0] * 10)
        self.assertEqual(len(result.dof), 10)


if __name__ == '__main__':
    unittest.main()
