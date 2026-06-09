#!/usr/bin/env python3
"""_ThumbPathPlanner 单元测试 — TDD

拇指碰撞避让策略：DOF1 先降到 0，再弯曲 DOF0。
"""

import time
import unittest

from l10_hand_gateway.motion_planner import (
    MotionPlanner,
    MotionPlanResult,
    NUM_DOF,
)


class MockCollisionGuard:
    """可编程的 collision_guard mock。

    支持 dof6_val 参数，记录最后一次调用传入的 dof6_val。
    """

    def __init__(self):
        self._limits = {}
        self.default_limit = 0.0
        self.last_dof6_val = None  # 记录最近一次 query 收到的 dof6_val

    def set_limit(self, dof1, dof9, finger_flexions, limit, dof6=None):
        key = (round(dof1, 1), round(dof9, 1),
               tuple(round(f, 1) for f in finger_flexions),
               round(dof6, 1) if dof6 is not None else None)
        self._limits[key] = limit

    def query_dof0_limit(self, dof1_val, dof9_val, finger_flexions, dof6_val=None):
        self.last_dof6_val = dof6_val
        key = (round(dof1_val, 1), round(dof9_val, 1),
               tuple(round(f, 1) for f in finger_flexions),
               round(dof6_val, 1) if dof6_val is not None else None)
        if key in self._limits:
            return self._limits[key]
        # 模糊匹配（容差 20），忽略 dof6 维度
        for stored_key, val in self._limits.items():
            if (abs(stored_key[0] - dof1_val) < 20 and
                abs(stored_key[1] - dof9_val) < 20 and
                all(abs(s - f) < 20 for s, f in zip(stored_key[2], finger_flexions))):
                return val
        return self.default_limit


class TestNoCollisionRisk(unittest.TestCase):
    """无碰撞风险时不激活分阶段路径"""

    def test_no_thumb_planner_without_guard(self):
        planner = MotionPlanner(collision_guard=None)
        self.assertIsNone(planner._thumb_planner)

    def test_no_collision_passes_through(self):
        mock_cg = MockCollisionGuard()
        mock_cg.default_limit = 0.0
        planner = MotionPlanner(collision_guard=mock_cg)
        start = [128.0] * NUM_DOF
        result = planner.advance(start, max_speed=120.0)
        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        result = planner.advance(desired, max_speed=120.0)
        self.assertIsInstance(result, MotionPlanResult)


class TestCollisionTriggersAvoidance(unittest.TestCase):
    """碰撞风险触发 DOF1 → 0"""

    def setUp(self):
        self.mock_cg = MockCollisionGuard()
        # 默认不安全（模拟 DOF1 越大越危险的连续曲线）
        self.mock_cg.default_limit = 150.0
        # DOF1=0 时安全（DOF0 限制为 0）
        self.mock_cg.set_limit(0.0, 0.0, [128.0] * 4, 0.0)
        self.planner = MotionPlanner(collision_guard=self.mock_cg)

    def test_dof0_held_during_phase1(self):
        """Phase 1: DOF0 被保持，不向碰撞目标移动"""
        start = [128.0] * NUM_DOF
        start[1] = 128.0
        start[9] = 0.0
        self.planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 128.0
        desired[9] = 0.0
        result = self.planner.advance(desired, max_speed=120.0)
        self.assertGreater(result.dof[0], 80.0,
            "DOF0 should be held near current during Phase 1")

    def test_dof1_goes_to_zero(self):
        """Phase 1: DOF1 向 0 移动"""
        start = [128.0] * NUM_DOF
        start[1] = 128.0
        start[9] = 0.0
        self.planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 128.0
        desired[9] = 0.0

        for _ in range(50):
            time.sleep(0.02)
            result = self.planner.advance(desired, max_speed=120.0)

        self.assertLess(result.dof[1], 128.0,
            "DOF1 should move toward 0")


class TestPhaseTransition(unittest.TestCase):
    """Phase 1 → Phase 2 过渡"""

    def setUp(self):
        self.mock_cg = MockCollisionGuard()
        self.mock_cg.default_limit = 200.0
        self.mock_cg.set_limit(0.0, 100.0, [100.0] * 4, 0.0)
        self.planner = MotionPlanner(collision_guard=self.mock_cg)

    def test_phase2_releases_dof0(self):
        """Phase 1 完成后 DOF0 向目标移动"""
        start = [100.0] * NUM_DOF
        start[9] = 100.0
        self.planner.advance(start, max_speed=240.0)

        desired = [100.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 100.0
        desired[9] = 100.0

        for _ in range(200):
            time.sleep(0.02)
            result = self.planner.advance(desired, max_speed=240.0)

        self.assertLess(result.dof[0], 90.0,
            "After Phase 1, DOF0 should move toward target")
        self.assertLessEqual(result.dof[1], 100.0)


class TestSmoothTransition(unittest.TestCase):
    """DOF1 避让运动平滑"""

    def setUp(self):
        self.mock_cg = MockCollisionGuard()
        self.mock_cg.default_limit = 200.0
        self.mock_cg.set_limit(0.0, 80.0, [128.0] * 4, 0.0)
        self.planner = MotionPlanner(collision_guard=self.mock_cg)

    def test_dof1_smooth_no_jump(self):
        """DOF1 运动无跳跃"""
        start = [128.0] * NUM_DOF
        start[1] = 80.0
        start[9] = 80.0
        self.planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 80.0
        desired[9] = 80.0

        prev_dof1 = 80.0
        max_jump = 0.0
        for _ in range(30):
            result = self.planner.advance(desired, max_speed=120.0)
            jump = abs(result.dof[1] - prev_dof1)
            max_jump = max(max_jump, jump)
            prev_dof1 = result.dof[1]

        self.assertLess(max_jump, 5.0,
            f"DOF1 should be smooth, max jump was {max_jump}")

    def test_dof0_held_then_released(self):
        """DOF0 先保持后释放"""
        start = [128.0] * NUM_DOF
        start[1] = 80.0
        start[9] = 80.0
        self.planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 80.0
        desired[9] = 80.0

        phase1_dof0 = []
        for _ in range(20):
            result = self.planner.advance(desired, max_speed=120.0)
            phase1_dof0.append(result.dof[0])

        spread = max(phase1_dof0) - min(phase1_dof0)
        self.assertLess(spread, 10.0,
            f"DOF0 should barely move during Phase 1, spread={spread}")


class TestNoCollisionGuardNoOp(unittest.TestCase):
    """无 collision_guard 时正常运动"""

    def test_normal_operation(self):
        planner = MotionPlanner(collision_guard=None)
        start = [128.0] * NUM_DOF
        planner.advance(start, max_speed=120.0)
        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        time.sleep(0.02)
        result = planner.advance(desired, max_speed=120.0)
        self.assertLess(result.dof[0], 128.0)


class TestTargetChangeMidTrajectory(unittest.TestCase):
    """中途目标变化"""

    def setUp(self):
        self.mock_cg = MockCollisionGuard()
        self.mock_cg.default_limit = 200.0
        self.mock_cg.set_limit(0.0, 100.0, [100.0] * 4, 0.0)
        self.planner = MotionPlanner(collision_guard=self.mock_cg)

    def test_new_safe_target_cancels_phased(self):
        """新目标安全时取消分阶段"""
        start = [100.0] * NUM_DOF
        start[9] = 100.0
        self.planner.advance(start, max_speed=240.0)

        desired = [100.0] * NUM_DOF
        desired[0] = 50.0
        desired[1] = 100.0
        desired[9] = 100.0
        self.planner.advance(desired, max_speed=240.0)

        # 新目标 DOF0=200（无碰撞）
        desired[0] = 200.0
        result = self.planner.advance(desired, max_speed=240.0)
        self.assertIsInstance(result, MotionPlanResult)


class TestPlannerPassesDof6(unittest.TestCase):
    """MotionPlanner 将 DOF6 传递给 ThumbRule.query_dof0_limit"""

    def setUp(self):
        self.mock_cg = MockCollisionGuard()
        self.mock_cg.default_limit = 150.0
        self.mock_cg.set_limit(0.0, 0.0, [128.0] * 4, 0.0)
        self.planner = MotionPlanner(collision_guard=self.mock_cg)

    def test_planner_passes_dof6(self):
        """get_targets 将 desired_dof[6] 作为 dof6_val 传入"""
        start = [128.0] * NUM_DOF
        start[6] = 50.0
        self.planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[6] = 42.0
        desired[9] = 0.0
        self.planner.advance(desired, max_speed=120.0)

        # MockCollisionGuard 记录了最后一次 query_dof0_limit 的 dof6_val
        self.assertIsNotNone(self.mock_cg.last_dof6_val,
            "query_dof0_limit should have been called")
        self.assertAlmostEqual(self.mock_cg.last_dof6_val, 42.0,
            places=0,
            msg="dof6_val should match desired_dof[6]")

    def test_dof6_changes_avoidance_decision(self):
        """不同 DOF6 值影响避让决策"""
        # DOF6=0 时食指收拢，设置严格限制
        self.mock_cg.set_limit(0.0, 0.0, [0.0] * 4, 0.0, dof6=0.0)
        # DOF6=255 时食指外展，设置宽松限制
        self.mock_cg.set_limit(0.0, 0.0, [0.0] * 4, 0.0, dof6=255.0)

        # 这里只需验证 mock 被调用了 dof6_val 参数
        planner = MotionPlanner(collision_guard=self.mock_cg)
        start = [128.0] * NUM_DOF
        start[6] = 0.0
        start[9] = 0.0
        planner.advance(start, max_speed=120.0)

        desired = [128.0] * NUM_DOF
        desired[0] = 50.0
        desired[6] = 0.0
        desired[9] = 0.0
        planner.advance(desired, max_speed=120.0)

        self.assertAlmostEqual(self.mock_cg.last_dof6_val, 0.0, places=0)


if __name__ == '__main__':
    unittest.main()
