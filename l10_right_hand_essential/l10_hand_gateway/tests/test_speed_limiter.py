#!/usr/bin/env python3
"""SpeedLimiter 单元测试 — 纯速度映射

SpeedLimiter 仅负责百分比 ↔ max_speed 映射。
轨迹规划测试见 test_motion_planner.py。
"""

import unittest

from l10_hand_gateway.speed_limiter import (
    SpeedLimiter,
    NUM_DOF,
    FULL_RANGE,
    MAX_PHYSICAL_SPEED,
)


class TestUnlimitedMode(unittest.TestCase):
    """不限制模式（max_speed=None）"""

    def test_default_is_unlimited(self):
        sl = SpeedLimiter()
        self.assertFalse(sl.is_limited)
        self.assertIsNone(sl.max_speed)

    def test_100_percent_unlimited(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(100.0)
        self.assertFalse(sl.is_limited)
        self.assertIsNone(sl.max_speed)

    def test_over_100_clamps_to_100(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(150.0)
        self.assertFalse(sl.is_limited)


class TestPercentageMapping(unittest.TestCase):
    """百分比映射正确性"""

    def test_0_percent_frozen(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(0.0)
        self.assertTrue(sl.is_limited)
        self.assertEqual(sl.max_speed, 0.0)

    def test_50_percent_moderate(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(50.0)
        self.assertAlmostEqual(sl.max_speed, 120.0)

    def test_25_percent(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(25.0)
        self.assertAlmostEqual(sl.max_speed, 60.0)

    def test_75_percent(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(75.0)
        self.assertAlmostEqual(sl.max_speed, 180.0)

    def test_negative_clamps_to_0(self):
        sl = SpeedLimiter()
        sl.set_from_percentage(-10.0)
        self.assertEqual(sl.max_speed, 0.0)

    def test_monotonic_mapping(self):
        sl = SpeedLimiter()
        speeds = []
        for pct in [1, 10, 25, 50, 75, 99]:
            sl.set_from_percentage(float(pct))
            speeds.append(sl.max_speed)
        for i in range(1, len(speeds)):
            self.assertGreater(speeds[i], speeds[i - 1],
                               f"pct={speeds[i]} not > previous={speeds[i - 1]}")


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
        sl = SpeedLimiter(max_speed=120.0)
        pct = sl.get_percentage()
        sl2 = SpeedLimiter()
        sl2.set_from_percentage(pct)
        self.assertAlmostEqual(sl2.max_speed, 120.0, places=1)


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


class TestConstantsExported(unittest.TestCase):
    """模块级常量"""

    def test_max_physical_speed(self):
        self.assertEqual(MAX_PHYSICAL_SPEED, 240.0)

    def test_num_dof_and_full_range(self):
        self.assertEqual(NUM_DOF, 10)
        self.assertEqual(FULL_RANGE, 255.0)


if __name__ == '__main__':
    unittest.main()
