#!/usr/bin/env python3
"""SpeedLimiter 单元测试 — 全局速度限制（临界阻尼弹簧-阻尼器算法）

TDD 测试优先：定义期望行为，再驱动实现。
"""

import unittest
import time

from l10_hand_gateway.speed_limiter import (
    SpeedLimiter,
    SpeedLimitResult,
    MAX_PHYSICAL_SPEED,
    MAX_DT,
    OMEGA_N_MIN,
    OMEGA_N_MAX,
    NUM_DOF,
    FULL_RANGE,
)


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
    """百分比映射正确性 — 0%=静止, 1-99%=线性, 100%=不限速"""

    def test_100_percent_unlimited(self):
        """100% = 不限制"""
        sl = SpeedLimiter()
        sl.set_from_percentage(100.0)
        self.assertFalse(sl.is_limited)
        self.assertIsNone(sl.max_speed)

    def test_0_percent_frozen(self):
        """0% = 完全静止 (0 units/s)"""
        sl = SpeedLimiter()
        sl.set_from_percentage(0.0)
        self.assertTrue(sl.is_limited)
        self.assertEqual(sl.max_speed, 0.0)

    def test_50_percent_moderate(self):
        """50% = 120.0 units/s"""
        sl = SpeedLimiter()
        sl.set_from_percentage(50.0)
        self.assertTrue(sl.is_limited)
        self.assertAlmostEqual(sl.max_speed, 120.0)

    def test_25_percent(self):
        """25% = 60.0 units/s"""
        sl = SpeedLimiter()
        sl.set_from_percentage(25.0)
        self.assertAlmostEqual(sl.max_speed, 60.0)

    def test_75_percent(self):
        """75% = 180.0 units/s"""
        sl = SpeedLimiter()
        sl.set_from_percentage(75.0)
        self.assertAlmostEqual(sl.max_speed, 180.0)

    def test_negative_clamps_to_0(self):
        """负值钳制到 0%（静止）"""
        sl = SpeedLimiter()
        sl.set_from_percentage(-10.0)
        self.assertEqual(sl.max_speed, 0.0)

    def test_over_100_clamps_to_100(self):
        """超过 100 钳制到 100%（无限速）"""
        sl = SpeedLimiter()
        sl.set_from_percentage(150.0)
        self.assertFalse(sl.is_limited)

    def test_monotonic_mapping(self):
        """百分比越高速度越快（单调递增）"""
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
        """直接设置 max_speed 后，通过百分比往返应保持一致"""
        sl = SpeedLimiter(max_speed=120.0)
        pct = sl.get_percentage()
        sl2 = SpeedLimiter()
        sl2.set_from_percentage(pct)
        self.assertAlmostEqual(sl2.max_speed, 120.0, places=1)


class TestZeroSpeedFrozen(unittest.TestCase):
    """max_speed=0 时完全静止"""

    def test_no_movement_at_zero_speed(self):
        """0% 时无论目标如何变化，位置不变"""
        sl = SpeedLimiter(max_speed=0.0)
        sl.reset([128.0] * 10)
        time.sleep(0.02)
        result = sl.advance([255.0] * 10)
        for v in result.dof:
            self.assertEqual(v, 128.0)

    def test_frozen_reports_active(self):
        """0% 时 active=False（不在前进，因为没有意义）"""
        sl = SpeedLimiter(max_speed=0.0)
        sl.reset([0.0] * 10)
        time.sleep(0.02)
        result = sl.advance([255.0] * 10)
        self.assertFalse(result.active)


class TestBasicAdvance(unittest.TestCase):
    """基本前进行为 — 临界阻尼弹簧"""

    def setUp(self):
        self.sl = SpeedLimiter(max_speed=240.0)
        self.sl.reset([0.0] * 10)

    def test_no_change_when_desired_equals_current(self):
        """目标与当前位置相同时不移动"""
        result = self.sl.advance([0.0] * 10)
        self.assertEqual(result.dof, [0.0] * 10)
        self.assertFalse(result.active)

    def test_large_delta_smooth_start(self):
        """大幅跳变：首步位移远小于 max_speed × dt（平滑启动）"""
        time.sleep(0.03)  # ~60Hz tick
        result = self.sl.advance([255.0] * 10)
        max_expected_linear = 240.0 * 0.03  # 旧算法的 max_delta
        # 临界阻尼首步远小于线性钳位
        for v in result.dof:
            self.assertLess(v, max_expected_linear,
                            "弹簧首步应远小于线性钳位")
            self.assertGreaterEqual(v, 0.0)
        self.assertTrue(result.active)

    def test_direction_increasing(self):
        """向增大方向前进"""
        self.sl.reset([100.0] * 10)
        time.sleep(0.03)
        result = self.sl.advance([200.0] * 10)
        # 弹簧保证向目标方向移动（即使位移很小）
        for v in result.dof:
            self.assertGreater(v, 100.0, "应向增大方向移动")

    def test_direction_decreasing(self):
        """向减小方向前进"""
        self.sl.reset([100.0] * 10)
        time.sleep(0.03)
        result = self.sl.advance([50.0] * 10)
        for v in result.dof:
            self.assertLess(v, 100.0, "应向减小方向移动")


class TestSmoothingBehavior(unittest.TestCase):
    """临界阻尼平滑特性"""

    def test_start_velocity_is_low(self):
        """初始速度接近零（无急加速）"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        time.sleep(0.016)
        result = sl.advance([255.0] * 10)
        # 首步位移应很小（远低于线性钳位的 240*0.016=3.84）
        for v in result.dof:
            self.assertLess(v, 2.0, "首步位移过大，缺少平滑启动")

    def test_velocity_increases_then_decreases(self):
        """速度先增后减（S 曲线特征）"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        target = [200.0] * 10

        positions = []
        for _ in range(80):
            time.sleep(0.02)
            result = sl.advance(target)
            positions.append(result.dof[0])

        velocities = [positions[i + 1] - positions[i]
                      for i in range(len(positions) - 1)]
        # 早期阶段速度应递增
        self.assertLess(velocities[0], velocities[len(velocities) // 4],
                        "早期速度应递增")
        # 最终收敛到目标
        self.assertAlmostEqual(positions[-1], 200.0, delta=5.0,
                               msg="应收敛到目标")

    def test_no_overshoot(self):
        """临界阻尼不应明显超调"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        target = [100.0] * 10

        max_val = 0.0
        for _ in range(200):
            time.sleep(0.02)
            result = sl.advance(target)
            max_val = max(max_val, max(result.dof))

        self.assertLessEqual(max_val, 105.0,
                             "临界阻尼不应超调超过 5 units")


class TestConvergence(unittest.TestCase):
    """持续前进最终收敛到目标"""

    def test_converges_to_target(self):
        """多步 advance 后到达目标"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)

        for _ in range(120):
            time.sleep(0.02)
            result = sl.advance([100.0] * 10)

        for v in result.dof:
            self.assertAlmostEqual(v, 100.0, delta=3.0)

    def test_active_flag_becomes_false(self):
        """到达目标后 active 变为 False"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        # 临界阻尼弹簧需要多步收敛（settle time ≈ 4/omega_n ≈ 0.4s）
        for _ in range(50):
            time.sleep(0.02)
            result = sl.advance([10.0] * 10)
        self.assertFalse(result.active)

    def test_partial_convergence(self):
        """未到达目标时 active 为 True"""
        sl = SpeedLimiter(max_speed=10.0)
        sl.reset([0.0] * 10)
        time.sleep(0.01)
        result = sl.advance([255.0] * 10)
        self.assertTrue(result.active)


class TestBoundaryClamping(unittest.TestCase):
    """DOF 值边界钳制"""

    def test_output_never_below_zero(self):
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([5.0] * 10)
        time.sleep(0.01)
        result = sl.advance([-100.0] * 10)
        for v in result.dof:
            self.assertGreaterEqual(v, 0.0)

    def test_output_never_above_255(self):
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([250.0] * 10)
        time.sleep(0.01)
        result = sl.advance([500.0] * 10)
        for v in result.dof:
            self.assertLessEqual(v, 255.0)


class TestDtClamping(unittest.TestCase):
    """dt 上限钳制（防止暂停后跳变）"""

    def test_long_pause_no_jump(self):
        """长时间暂停后不产生大幅跳变"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        # 模拟长时间暂停
        sl._last_time = time.monotonic() - 10.0
        result = sl.advance([255.0] * 10)
        # MAX_DT=0.05，弹簧速度从 0 起步，位移远小于 240*0.05=12
        for v in result.dof:
            self.assertLess(v, 15.0)


class TestReset(unittest.TestCase):
    """reset() 行为"""

    def test_reset_syncs_position(self):
        """reset 将内部位置同步到指定值"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        time.sleep(0.01)
        sl.advance([100.0] * 10)

        sl.reset([128.0] * 10)
        time.sleep(0.01)
        result = sl.advance([130.0] * 10)
        for v in result.dof:
            self.assertGreater(v, 128.0)
            self.assertLessEqual(v, 130.0)

    def test_reset_clears_velocity(self):
        """reset 清零速度状态，避免残留动量"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        time.sleep(0.03)
        sl.advance([255.0] * 10)  # 积累速度

        sl.reset([128.0] * 10)
        # reset 后从 128 出发，不应有残留速度导致跳变
        time.sleep(0.01)
        result = sl.advance([128.0] * 10)
        for v in result.dof:
            self.assertAlmostEqual(v, 128.0, delta=1.0)

    def test_reset_allows_immediate_pass_through_after_unlimited(self):
        """reset 后设置无限速仍透传"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        sl.max_speed = None
        result = sl.advance([255.0] * 10)
        self.assertEqual(result.dof, [255.0] * 10)


class TestPerDofIndependence(unittest.TestCase):
    """各 DOF 独立运动"""

    def test_mixed_directions(self):
        """不同 DOF 可以独立向不同方向移动"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([128.0] * 10)
        time.sleep(0.03)

        desired = [138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0]
        result = sl.advance(desired)
        # 弹簧保证方向正确
        for i in [0, 3, 6, 9]:
            self.assertGreater(result.dof[i], 128.0, f"DOF[{i}] 应增大")
        for i in [1, 4, 7]:
            self.assertLess(result.dof[i], 128.0, f"DOF[{i}] 应减小")
        for i in [2, 5, 8]:
            self.assertAlmostEqual(result.dof[i], 128.0, delta=0.5,
                                   msg=f"DOF[{i}] 应不变")

    def test_independent_convergence(self):
        """各 DOF 独立收敛到各自目标"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        targets = [50.0, 100.0, 150.0, 200.0, 250.0, 50.0, 100.0, 150.0, 200.0, 250.0]

        for _ in range(120):
            time.sleep(0.02)
            result = sl.advance(targets)

        for i, t in enumerate(targets):
            self.assertAlmostEqual(result.dof[i], t, delta=5.0,
                                   msg=f"DOF[{i}] 未收敛到 {t}")


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
        sl = SpeedLimiter(max_speed=240.0)
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
        """运动中途降速：位置持续前进但速度受控"""
        sl = SpeedLimiter(max_speed=240.0)
        sl.reset([0.0] * 10)
        time.sleep(0.03)
        r1 = sl.advance([255.0] * 10)
        pos1 = r1.dof[0]

        # 降速
        sl.max_speed = 50.0
        time.sleep(0.03)
        r2 = sl.advance([255.0] * 10)
        # 位置应继续前进（有残留速度 + 弹簧驱动）
        self.assertGreater(r2.dof[0], pos1)

    def test_speed_up_mid_motion(self):
        """运动中途加速：更快到达目标"""
        sl = SpeedLimiter(max_speed=10.0)
        sl.reset([0.0] * 10)
        time.sleep(0.03)
        r1 = sl.advance([255.0] * 10)

        # 加速
        sl.max_speed = 240.0
        time.sleep(0.05)
        r2 = sl.advance([255.0] * 10)
        self.assertGreater(r2.dof[0], r1.dof[0])

    def test_unlimited_to_limited_resets(self):
        """从无限速切换到有限速时 reset 同步位置"""
        sl = SpeedLimiter()
        sl.advance([255.0] * 10)

        sl.set_from_percentage(50.0)
        sl.reset([200.0] * 10)

        time.sleep(0.01)
        result = sl.advance([255.0] * 10)
        # 从 200 出发，弹簧首步位移很小
        for v in result.dof:
            self.assertGreaterEqual(v, 200.0)
            self.assertLessEqual(v, 205.0)


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


class TestConstantsExported(unittest.TestCase):
    """模块级常量可导入，供外部测试/文档引用"""

    def test_max_physical_speed(self):
        self.assertEqual(MAX_PHYSICAL_SPEED, 240.0)

    def test_max_dt(self):
        self.assertEqual(MAX_DT, 0.05)

    def test_omega_n_range(self):
        self.assertLess(OMEGA_N_MIN, OMEGA_N_MAX)

    def test_num_dof_and_full_range(self):
        self.assertEqual(NUM_DOF, 10)
        self.assertEqual(FULL_RANGE, 255.0)


if __name__ == '__main__':
    unittest.main()
