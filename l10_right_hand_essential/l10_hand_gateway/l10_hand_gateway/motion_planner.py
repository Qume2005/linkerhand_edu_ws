"""
L10 灵巧手运动规划模块

五次样条（min-jerk）轨迹生成器，为 10 个 DOF 提供平滑的点到点运动规划。
包含拇指碰撞避让分阶段路径规划。

特性：
- 零初速/零终速五次多项式插值，无抖动、无过调
- 中途目标变化时从当前 (position, velocity) 平滑重规划
- 拇指 DOF 支持分阶段避碰路径（需 ThumbRule）
  Phase 1: DOF1 → 0（向掌心收拢），DOF0 保持
  Phase 2: DOF0 → 目标值，DOF1 恢复到原始目标

纯 Python，不依赖 ROS，可独立测试。
"""

import time
from dataclasses import dataclass

NUM_DOF = 10
FULL_RANGE = 255.0
MAX_PHYSICAL_SPEED = 240.0

SNAP_THRESHOLD = 0.5
T_FLOOR = 0.05
PEAK_VEL_FACTOR = 1.875
MAX_DT = 0.05


@dataclass
class _SplineCoeffs:
    """单 DOF 五次多项式系数"""
    a0: float
    a1: float
    a2: float
    a3: float
    a4: float
    a5: float
    T: float
    t_start: float
    target: float


@dataclass
class MotionPlanResult:
    """运动规划结果"""
    dof: list       # 10 元素插值后的 DOF
    active: bool    # True 表示仍有 DOF 在运动


def _plan_spline(p0, v0, p1, max_speed, t_start):
    """计算从 (p0, v0) 到 (p1, vel=0) 的五次样条系数。

    边界条件：pos(0)=p0, vel(0)=v0, acc(0)=0
              pos(1)=p1, vel(1)=0,  acc(1)=0

    Returns: _SplineCoeffs 或 None（Δ < SNAP_THRESHOLD 时）
    """
    delta = abs(p1 - p0)
    if delta < SNAP_THRESHOLD and abs(v0) < SNAP_THRESHOLD:
        return None

    T = max(PEAK_VEL_FACTOR * delta / max(max_speed, 1e-6), T_FLOOR)

    a0 = p0
    a1 = v0 * T
    a2 = 0.0
    a3 = 10.0 * (p1 - p0) - 6.0 * v0 * T
    a4 = -15.0 * (p1 - p0) + 8.0 * v0 * T
    a5 = 6.0 * (p1 - p0) - 3.0 * v0 * T

    return _SplineCoeffs(a0, a1, a2, a3, a4, a5, T, t_start, p1)


def _evaluate_spline(coeffs, now):
    """求值五次样条，返回 (position, velocity)。"""
    elapsed = now - coeffs.t_start
    tau = min(elapsed / coeffs.T, 1.0)

    t2 = tau * tau
    t3 = t2 * tau
    t4 = t3 * tau
    t5 = t4 * tau

    pos = (coeffs.a0
           + coeffs.a1 * tau
           + coeffs.a2 * t2
           + coeffs.a3 * t3
           + coeffs.a4 * t4
           + coeffs.a5 * t5)

    vel = (coeffs.a1
           + 2.0 * coeffs.a2 * tau
           + 3.0 * coeffs.a3 * t2
           + 4.0 * coeffs.a4 * t3
           + 5.0 * coeffs.a5 * t4) / coeffs.T

    return pos, vel


class MotionPlanner:
    """10-DOF 五次样条运动规划器。

    参数:
        collision_guard: 可选的 ThumbRule 实例，用于拇指避碰路径规划。
    """

    def __init__(self, collision_guard=None):
        self._splines: list[_SplineCoeffs | None] = [None] * NUM_DOF
        self._last_dof = None
        self._last_time = None
        self._thumb_planner = (
            _ThumbPathPlanner(collision_guard) if collision_guard else None
        )

    def advance(self, desired_dof, max_speed):
        """从当前位置向 desired_dof 前进一步。

        Args:
            desired_dof: 10 元素目标 DOF 列表
            max_speed: 最大速度 (units/s)，None 表示不限速

        Returns:
            MotionPlanResult

        Raises:
            ValueError: 输入长度不足 NUM_DOF
        """
        if len(desired_dof) < NUM_DOF:
            raise ValueError(
                f"Expected {NUM_DOF} DOF values, got {len(desired_dof)}")

        now = time.monotonic()

        # 不限速 或 首次调用：直接透传
        if max_speed is None or self._last_dof is None:
            self._last_dof = list(desired_dof[:NUM_DOF])
            self._last_time = now
            # 清空所有样条
            self._splines = [None] * NUM_DOF
            if self._thumb_planner:
                self._thumb_planner.reset()
            return MotionPlanResult(
                dof=list(desired_dof[:NUM_DOF]), active=False)

        dt = now - self._last_time
        self._last_time = now

        # 限制 dt
        dt = min(dt, MAX_DT)

        # 完全静止
        if max_speed <= 0.0:
            return MotionPlanResult(
                dof=list(self._last_dof), active=False)

        # 样条起始时刻：轨迹在上一 tick 到当前 tick 之间开始，
        # 因此首次求值时 elapsed = dt，已有一步位移。
        spline_t_start = now - dt

        # 拇指碰撞避让：获取 DOF 0/1/9 的有效目标
        thumb_overrides = None
        if self._thumb_planner:
            thumb_overrides = self._thumb_planner.get_targets(
                desired_dof, self._last_dof, max_speed, now, dt)

        result = [0.0] * NUM_DOF
        active = False

        for i in range(NUM_DOF):
            target = desired_dof[i]

            # 拇指碰撞避让：使用覆盖目标
            if thumb_overrides and i in thumb_overrides:
                target = thumb_overrides[i]

            # 检查目标是否变化 → 需要重规划
            current_spline = self._splines[i]
            need_replan = (
                current_spline is None
                or abs(target - current_spline.target) > SNAP_THRESHOLD)

            if need_replan:
                # 获取当前速度
                if current_spline is not None:
                    _, v0 = _evaluate_spline(current_spline, now)
                else:
                    v0 = 0.0

                self._splines[i] = _plan_spline(
                    self._last_dof[i], v0, target, max_speed, spline_t_start)

            # 求值样条
            spline = self._splines[i]
            if spline is not None:
                elapsed = now - spline.t_start
                tau = min(elapsed / spline.T, 1.0)

                if tau >= 1.0:
                    # 精确到达
                    result[i] = target
                    self._splines[i] = None
                else:
                    pos, _ = _evaluate_spline(spline, now)
                    result[i] = max(0.0, min(FULL_RANGE, pos))
                    active = True
            else:
                result[i] = target

        self._last_dof = list(result)
        return MotionPlanResult(dof=result, active=active)

    def reset(self, current_dof):
        """重置内部状态（清空所有轨迹和位置跟踪）。

        Args:
            current_dof: 10 元素当前 DOF 值列表
        """
        self._last_dof = list(current_dof)
        self._last_time = time.monotonic()
        self._splines = [None] * NUM_DOF
        if self._thumb_planner:
            self._thumb_planner.reset()


# ============================================================================
# _ThumbPathPlanner — 拇指碰撞避让分阶段路径规划
# ============================================================================


class _ThumbPathPlanner:
    """拇指碰撞避让分阶段路径规划器。

    当 DOF0（拇指弯曲）目标值低于碰撞安全下限时：
    Phase 1: DOF1 → 0（向掌心收拢），DOF0 保持不变
    Phase 2: DOF0 → 目标值，DOF1 → 原始目标值

    简单直接：不搜索安全配置，DOF1 直接降到 0（最安全位置）。
    """

    def __init__(self, thumb_rule):
        self._thumb_rule = thumb_rule
        self._phase = 0       # 0=空闲, 1=避让, 2=弯曲

    def reset(self):
        """重置所有状态。"""
        self._phase = 0

    def get_targets(self, desired_dof, current_dof, max_speed, now, dt):
        """计算拇指 DOF 的有效目标。

        Returns:
            dict 或 None:
            - None: 无碰撞风险，使用原始目标
            - {0: dof0_target, 1: dof1_target, 9: dof9_target}: 覆盖目标
        """
        target_dof0 = desired_dof[0]
        current_dof1 = current_dof[1]
        current_dof9 = current_dof[9]
        finger_flexions = [desired_dof[2], desired_dof[3],
                           desired_dof[4], desired_dof[5]]

        # Phase 2 进行中：DOF0 向目标移动，DOF1 向原始目标恢复
        if self._phase == 2:
            # 目标大幅变化时重新评估
            if abs(target_dof0 - desired_dof[0]) > SNAP_THRESHOLD:
                limit = self._thumb_rule.query_dof0_limit(
                    current_dof1, current_dof9, finger_flexions)
                if target_dof0 >= limit:
                    self._phase = 0
                    return None
            return {
                0: target_dof0,
                1: desired_dof[1],
                9: desired_dof[9],
            }

        # 检查当前配置是否允许目标 DOF0
        limit = self._thumb_rule.query_dof0_limit(
            current_dof1, current_dof9, finger_flexions)

        if target_dof0 >= limit:
            # 安全
            if self._phase == 1:
                # Phase 1 完成 → 进入 Phase 2
                self._phase = 2
                return {
                    0: target_dof0,
                    1: desired_dof[1],
                    9: desired_dof[9],
                }
            self._phase = 0
            return None

        # 碰撞风险 → Phase 1: DOF1 → 0, DOF0 保持
        self._phase = 1
        return {
            0: current_dof[0],
            1: 0.0,
            9: desired_dof[9],
        }
