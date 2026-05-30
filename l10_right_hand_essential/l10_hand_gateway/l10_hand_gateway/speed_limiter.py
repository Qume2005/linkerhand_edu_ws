"""
L10 灵巧手全局速度限制模块

限制所有 10 个 DOF 的最大变化速率（单位/秒），确保无论控制源
（GUI 面板、LLM、手部追踪、外部节点）发送多大的跳变命令，
手部运动速度都不会超过设定上限。

纯 Python，不依赖 ROS，可独立测试。
"""

import time
from dataclasses import dataclass


NUM_DOF = 10
FULL_RANGE = 255.0
# 单次 advance() 允许的最大 dt (秒)。
# 防止长时间暂停后单步跳变过大；值过大意味着暂停后恢复时移动过快，
# 值过小意味着低频调用时永远无法到达目标。0.2s 是 30Hz 下 6 个 tick 的窗口。
MAX_DT = 0.2

# 百分比 ↔ 速度映射参数
# 0% → MIN_SPEED, 100% → 不限制
# 线性映射: max_speed = MIN_SPEED + (pct / 100) * SPEED_RANGE
MIN_SPEED = 5.0    # units/s (0% 时，约 51 秒走完全程)
SPEED_RANGE = 500.0  # units/s (映射区间跨度)


@dataclass
class SpeedLimitResult:
    """速度限制过滤结果"""
    dof: list       # 10 元素速度限制后的 DOF
    active: bool    # True 表示仍有 DOF 在向目标前进


class SpeedLimiter:
    """全局速度限制器。

    参数:
        max_speed: 每个关节每秒最大变化量（DOF units/second）。
                   None 表示不限制（直接透传）。
    """

    def __init__(self, max_speed=None):
        self._max_speed = max_speed
        self._last_dof = None
        self._last_time = None

    @property
    def max_speed(self):
        return self._max_speed

    @max_speed.setter
    def max_speed(self, value):
        self._max_speed = value

    @property
    def is_limited(self):
        """是否启用了速度限制"""
        return self._max_speed is not None

    def set_from_percentage(self, pct):
        """从 0-100 百分比设置速度。

        100% = 不限制（透传）
        0%   = MIN_SPEED (极慢)
        中间线性映射
        """
        if pct >= 100.0:
            self._max_speed = None
        elif pct <= 0.0:
            self._max_speed = MIN_SPEED
        else:
            self._max_speed = MIN_SPEED + (pct / 100.0) * SPEED_RANGE

    def get_percentage(self):
        """将当前 max_speed 反映射为 0-100 百分比。

        100% 表示不限制。与 set_from_percentage 互逆。
        """
        if self._max_speed is None:
            return 100.0
        return max(0.0, min(100.0,
            (self._max_speed - MIN_SPEED) / SPEED_RANGE * 100.0))

    def advance(self, desired_dof):
        """将速度限制位置向 desired_dof 前进一步。

        基于距离上次调用的时间差 dt，每个 DOF 最多移动
        max_speed * dt 个单位。

        Args:
            desired_dof: 10 元素目标 DOF 列表

        Returns:
            SpeedLimitResult

        Raises:
            ValueError: 输入长度不足 NUM_DOF
        """
        if len(desired_dof) < NUM_DOF:
            raise ValueError(f"Expected {NUM_DOF} DOF values, got {len(desired_dof)}")

        now = time.monotonic()

        # 不限制 或 首次调用：直接透传
        if self._max_speed is None or self._last_dof is None:
            self._last_dof = list(desired_dof[:NUM_DOF])
            self._last_time = now
            return SpeedLimitResult(dof=list(desired_dof[:NUM_DOF]), active=False)

        dt = now - self._last_time
        self._last_time = now

        # 限制 dt 防止长时间暂停后跳变
        dt = min(dt, MAX_DT)

        max_delta = self._max_speed * dt
        result = [0.0] * NUM_DOF
        active = False

        for i in range(NUM_DOF):
            diff = desired_dof[i] - self._last_dof[i]
            if abs(diff) <= max_delta:
                result[i] = desired_dof[i]
            else:
                active = True
                if diff > 0:
                    result[i] = self._last_dof[i] + max_delta
                else:
                    result[i] = self._last_dof[i] - max_delta
                result[i] = max(0.0, min(FULL_RANGE, result[i]))

        self._last_dof = list(result)
        return SpeedLimitResult(dof=result, active=active)

    def reset(self, current_dof):
        """重置内部跟踪位置（启动时或需要同步时调用）。

        Args:
            current_dof: 10 元素当前 DOF 值列表
        """
        self._last_dof = list(current_dof)
        self._last_time = time.monotonic()
