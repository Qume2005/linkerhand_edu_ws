#!/usr/bin/env python3
"""MotionPlanner 单元测试 — 五次样条轨迹规划

TDD 测试优先：定义期望行为，再驱动实现。
"""

import unittest
import time

from l10_hand_gateway.motion_planner import (
    MotionPlanner,
    MotionPlanResult,
    NUM_DOF,
    FULL_RANGE,
    SNAP_THRESHOLD,
    PEAK_VEL_FACTOR,
    T_FLOOR,
    MAX_DT,
    MAX_PHYSICAL_SPEED,
)


class TestPassThrough(unittest.TestCase):
    """不限速（max_speed=None）和首次调用时的透传行为"""

    def test_unlimited_pass_through(self):
        """max_speed=None 时直接透传"""
        mp = MotionPlanner()
        dof = [128.0] * 10
        result = mp.advance(dof, max_speed=None)
        self.assertEqual(result.dof, dof)
        self.assertFalse(result.active)

    def test_first_call_pass_through(self):
        """首次调用直接透传，建立初始位置"""
        mp = MotionPlanner()
        dof = [100.0] * 10
        result = mp.advance(dof, max_speed=240.0)
        self.assertEqual(result.dof, dof)
        self.assertFalse(result.active)

    def test_different_dof_values_pass_through(self):
        """不限速时任意 DOF 值透传"""
        mp = MotionPlanner()
        for dof in [
            [0.0] * 10,
            [255.0] * 10,
            [128.0, 64.0, 200.0, 10.0, 50.0, 100.0, 180.0, 0.0, 255.0, 41.0],
        ]:
            result = mp.advance(dof, max_speed=None)
            self.assertEqual(result.dof, dof)


class TestFrozenMode(unittest.TestCase):
    """max_speed=0 时完全静止"""

    def test_no_movement_at_zero_speed(self):
        """0 速度时无论目标如何变化，位置不变"""
        mp = MotionPlanner()
        mp.advance([128.0] * 10, max_speed=None)  # 建立初始位置
        mp.reset([128.0] * 10)
        time.sleep(0.02)
        result = mp.advance([255.0] * 10, max_speed=0.0)
        for v in result.dof:
            self.assertEqual(v, 128.0)

    def test_frozen_reports_inactive(self):
        """0 速度时 active=False（没有运动）"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=None)
        mp.reset([0.0] * 10)
        time.sleep(0.02)
        result = mp.advance([255.0] * 10, max_speed=0.0)
        self.assertFalse(result.active)


class TestBasicAdvance(unittest.TestCase):
    """基本前进行为"""

    def setUp(self):
        self.mp = MotionPlanner()
        self.mp.advance([0.0] * 10, max_speed=240.0)  # 建立初始位置
        self.mp.reset([0.0] * 10)

    def test_no_change_when_at_target(self):
        """目标与当前位置相同时不移动"""
        time.sleep(0.02)
        result = self.mp.advance([0.0] * 10, max_speed=240.0)
        self.assertEqual(result.dof, [0.0] * 10)
        self.assertFalse(result.active)

    def test_starts_from_current_position(self):
        """从 reset 的位置开始移动"""
        self.mp.reset([100.0] * 10)
        time.sleep(0.02)
        result = self.mp.advance([200.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertGreater(v, 100.0, "应向增大方向移动")

    def test_direction_decreasing(self):
        """向减小方向移动"""
        self.mp.reset([100.0] * 10)
        time.sleep(0.02)
        result = self.mp.advance([50.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertLess(v, 100.0, "应向减小方向移动")

    def test_active_flag_when_moving(self):
        """运动中 active=True"""
        time.sleep(0.02)
        result = self.mp.advance([255.0] * 10, max_speed=240.0)
        self.assertTrue(result.active)


class TestQuinticSplineProfile(unittest.TestCase):
    """五次样条轨迹特性"""

    def test_smooth_start(self):
        """首步位移远小于 max_speed × dt（零初速起步）"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        time.sleep(0.016)
        result = mp.advance([255.0] * 10, max_speed=240.0)
        max_expected = 240.0 * 0.016  # 线性极限
        for v in result.dof:
            self.assertLess(v, max_expected, "首步位移应远小于线性极限")
            self.assertGreaterEqual(v, 0.0)

    def test_no_overshoot(self):
        """五次样条无过调（单调递增到目标）"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        target = [100.0] * 10

        max_val = 0.0
        for _ in range(200):
            time.sleep(0.02)
            result = mp.advance(target, max_speed=240.0)
            max_val = max(max_val, max(result.dof))

        self.assertLessEqual(max_val, 100.5,
                             "五次样条不应过调超过 0.5 units")

    def test_velocity_bell_curve(self):
        """速度先增后减（钟形曲线）"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        target = [200.0] * 10

        positions = []
        for _ in range(80):
            time.sleep(0.02)
            result = mp.advance(target, max_speed=240.0)
            positions.append(result.dof[0])

        velocities = [positions[i + 1] - positions[i]
                      for i in range(len(positions) - 1)]
        # 早期速度递增
        self.assertLess(velocities[0], velocities[len(velocities) // 4],
                        "早期速度应递增")
        # 最终收敛
        self.assertAlmostEqual(positions[-1], 200.0, delta=5.0,
                               msg="应收敛到目标")


class TestExactArrival(unittest.TestCase):
    """五次样条有限时间精确到达"""

    def test_converges_to_target(self):
        """多步 advance 后精确到达目标"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)

        for _ in range(120):
            time.sleep(0.02)
            result = mp.advance([100.0] * 10, max_speed=240.0)

        for v in result.dof:
            self.assertAlmostEqual(v, 100.0, delta=1.0,
                                   msg="应精确到达目标")

    def test_active_flag_becomes_false(self):
        """到达目标后 active 变为 False"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)

        # 五次样条在有限时间 T 后精确到达
        # T = 1.875 * 10 / 240 ≈ 0.078s，约 4 ticks at 60Hz
        for _ in range(30):
            time.sleep(0.02)
            result = mp.advance([10.0] * 10, max_speed=240.0)
        self.assertFalse(result.active)


class TestSnapMechanism(unittest.TestCase):
    """微小运动立即到达"""

    def test_snap_for_tiny_movement(self):
        """Δ < SNAP_THRESHOLD 时立即到达（不规划样条）"""
        mp = MotionPlanner()
        mp.advance([100.0] * 10, max_speed=240.0)
        mp.reset([100.0] * 10)

        time.sleep(0.02)
        result = mp.advance([100.3] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertAlmostEqual(v, 100.3, delta=0.01)
        self.assertFalse(result.active)


class TestReplanning(unittest.TestCase):
    """中途改变目标"""

    def test_replan_mid_trajectory(self):
        """中途改目标，位置连续、不回退"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)

        # 开始向 255 移动
        time.sleep(0.03)
        r1 = mp.advance([255.0] * 10, max_speed=240.0)
        pos1 = r1.dof[0]
        self.assertGreater(pos1, 0.0)

        # 中途改目标到 128
        time.sleep(0.03)
        r2 = mp.advance([128.0] * 10, max_speed=240.0)
        # 位置应从 pos1 继续前进（样条从当前位置重规划）
        # 注意：改目标后方向可能反转，但位置应连续
        self.assertNotEqual(r2.dof[0], 0.0, "位置应已移动")

    def test_replan_eventually_converges(self):
        """多次重规划后最终到达最终目标"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)

        # 先向 200 走几步
        for _ in range(5):
            time.sleep(0.02)
            mp.advance([200.0] * 10, max_speed=240.0)

        # 改目标到 100
        for _ in range(80):
            time.sleep(0.02)
            result = mp.advance([100.0] * 10, max_speed=240.0)

        self.assertAlmostEqual(result.dof[0], 100.0, delta=2.0)


class TestBoundaryClamping(unittest.TestCase):
    """DOF 值边界钳制"""

    def test_output_never_below_zero(self):
        mp = MotionPlanner()
        mp.advance([5.0] * 10, max_speed=240.0)
        mp.reset([5.0] * 10)
        time.sleep(0.01)
        result = mp.advance([-100.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertGreaterEqual(v, 0.0)

    def test_output_never_above_255(self):
        mp = MotionPlanner()
        mp.advance([250.0] * 10, max_speed=240.0)
        mp.reset([250.0] * 10)
        time.sleep(0.01)
        result = mp.advance([500.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertLessEqual(v, 255.0)


class TestDtClamping(unittest.TestCase):
    """dt 上限钳制"""

    def test_long_pause_no_jump(self):
        """长时间暂停后不产生大幅跳变"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        # 模拟长时间暂停
        mp._last_time = time.monotonic() - 10.0
        result = mp.advance([255.0] * 10, max_speed=240.0)
        # MAX_DT=0.05，首步位移远小于 240*0.05=12
        for v in result.dof:
            self.assertLess(v, 15.0)


class TestReset(unittest.TestCase):
    """reset() 行为"""

    def test_reset_syncs_position(self):
        """reset 将内部位置同步到指定值"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        time.sleep(0.02)
        mp.advance([100.0] * 10, max_speed=240.0)

        mp.reset([128.0] * 10)
        time.sleep(0.02)
        result = mp.advance([130.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertGreater(v, 128.0)
            self.assertLessEqual(v, 130.5)

    def test_reset_clears_trajectory(self):
        """reset 清空所有轨迹"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        time.sleep(0.03)
        mp.advance([255.0] * 10, max_speed=240.0)  # 建立轨迹

        mp.reset([128.0] * 10)
        # reset 后所有轨迹清空，下一步从 128 开始
        time.sleep(0.02)
        result = mp.advance([128.0] * 10, max_speed=240.0)
        for v in result.dof:
            self.assertAlmostEqual(v, 128.0, delta=1.0)


class TestPerDofIndependence(unittest.TestCase):
    """各 DOF 独立运动"""

    def test_mixed_directions(self):
        """不同 DOF 可以独立向不同方向移动"""
        mp = MotionPlanner()
        mp.advance([128.0] * 10, max_speed=240.0)
        mp.reset([128.0] * 10)
        time.sleep(0.03)

        desired = [138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0, 118.0, 128.0, 138.0]
        result = mp.advance(desired, max_speed=240.0)
        for i in [0, 3, 6, 9]:
            self.assertGreater(result.dof[i], 128.0, f"DOF[{i}] 应增大")
        for i in [1, 4, 7]:
            self.assertLess(result.dof[i], 128.0, f"DOF[{i}] 应减小")
        for i in [2, 5, 8]:
            self.assertAlmostEqual(result.dof[i], 128.0, delta=0.5,
                                   msg=f"DOF[{i}] 应不变")

    def test_independent_convergence(self):
        """各 DOF 独立收敛到各自目标"""
        mp = MotionPlanner()
        mp.advance([0.0] * 10, max_speed=240.0)
        mp.reset([0.0] * 10)
        targets = [50.0, 100.0, 150.0, 200.0, 250.0, 50.0, 100.0, 150.0, 200.0, 250.0]

        for _ in range(120):
            time.sleep(0.02)
            result = mp.advance(targets, max_speed=240.0)

        for i, t in enumerate(targets):
            self.assertAlmostEqual(result.dof[i], t, delta=3.0,
                                   msg=f"DOF[{i}] 未收敛到 {t}")


class TestResultStructure(unittest.TestCase):
    """MotionPlanResult 结构正确性"""

    def test_has_correct_fields(self):
        mp = MotionPlanner()
        result = mp.advance([128.0] * 10, max_speed=240.0)
        self.assertTrue(hasattr(result, 'dof'))
        self.assertTrue(hasattr(result, 'active'))
        self.assertIsInstance(result.dof, list)
        self.assertIsInstance(result.active, bool)

    def test_dof_always_10_elements(self):
        mp = MotionPlanner()
        result = mp.advance([128.0] * 10, max_speed=240.0)
        self.assertEqual(len(result.dof), 10)

    def test_dof_always_in_range(self):
        """DOF 值始终在 [0, 255]"""
        mp = MotionPlanner()
        mp.advance([128.0] * 10, max_speed=240.0)
        mp.reset([128.0] * 10)
        for desired in [
            [0.0] * 10,
            [255.0] * 10,
            [-50.0] * 10,
            [300.0] * 10,
        ]:
            time.sleep(0.01)
            result = mp.advance(desired, max_speed=240.0)
            for i, v in enumerate(result.dof):
                self.assertGreaterEqual(v, 0.0, f"DOF[{i}] < 0: {v}")
                self.assertLessEqual(v, 255.0, f"DOF[{i}] > 255: {v}")


class TestInputValidation(unittest.TestCase):
    """输入校验"""

    def test_advance_too_short_raises(self):
        mp = MotionPlanner()
        with self.assertRaises(ValueError):
            mp.advance([128.0] * 5, max_speed=240.0)

    def test_advance_empty_raises(self):
        mp = MotionPlanner()
        with self.assertRaises(ValueError):
            mp.advance([], max_speed=240.0)

    def test_advance_exact_length_ok(self):
        mp = MotionPlanner()
        result = mp.advance([128.0] * 10, max_speed=240.0)
        self.assertEqual(len(result.dof), 10)


class TestConstantsExported(unittest.TestCase):
    """模块级常量可导入"""

    def test_snap_threshold(self):
        self.assertEqual(SNAP_THRESHOLD, 0.5)

    def test_peak_vel_factor(self):
        self.assertAlmostEqual(PEAK_VEL_FACTOR, 1.875)

    def test_t_floor(self):
        self.assertEqual(T_FLOOR, 0.05)

    def test_max_dt(self):
        self.assertEqual(MAX_DT, 0.05)

    def test_num_dof_and_full_range(self):
        self.assertEqual(NUM_DOF, 10)
        self.assertEqual(FULL_RANGE, 255.0)

    def test_max_physical_speed(self):
        self.assertEqual(MAX_PHYSICAL_SPEED, 240.0)


if __name__ == '__main__':
    unittest.main()
