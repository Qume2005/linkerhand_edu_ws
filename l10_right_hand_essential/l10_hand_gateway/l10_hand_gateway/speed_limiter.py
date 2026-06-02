"""
L10 灵巧手全局速度限制模块

限制所有 10 个 DOF 的最大变化速率（单位/秒），确保无论控制源
（GUI 面板、LLM、手部追踪、外部节点）发送多大的跳变命令，
手部运动速度都不会超过设定上限。

采用临界阻尼弹簧-阻尼器算法，实现平滑加减速过渡，
替代纯线性 rate-clamp 的瞬时加速/急停行为。

纯 Python，不依赖 ROS，可独立测试。
"""

import time
from dataclasses import dataclass


NUM_DOF = 10
FULL_RANGE = 255.0

# 实测物理最大运动速度 ≈ 旧仿真限速 47% 时的速度 (240 units/s)。
MAX_PHYSICAL_SPEED = 240.0

# 单次 advance() 允许的最大 dt (秒)。
# 60Hz 下约 3 tick，防止暂停后跳变。
MAX_DT = 0.05

# 临界阻尼弹簧参数
# 自然频率越高 → 响应越快；越低 → 运动越柔和
OMEGA_N_MIN = 1.5   # 最低速度档时的自然频率（缓慢柔和）
OMEGA_N_MAX = 10.0  # 99% 时的自然频率（快速响应）


@dataclass
class SpeedLimitResult:
    """速度限制过滤结果"""
    dof: list       # 10 元素速度限制后的 DOF
    active: bool    # True 表示仍有 DOF 在向目标前进


class SpeedLimiter:
    """全局速度限制器（临界阻尼弹簧-阻尼器算法）。

    参数:
        max_speed: 每个关节每秒最大变化量（DOF units/second）。
                   None 表示不限制（直接透传）。
    """

    def __init__(self, max_speed=None):
        self._max_speed = max_speed
        self._omega_n = self._omega_n_from_speed(max_speed)
        self._last_dof = None
        self._last_time = None
        self._velocity = [0.0] * NUM_DOF

    @property
    def max_speed(self):
        return self._max_speed

    @max_speed.setter
    def max_speed(self, value):
        self._max_speed = value
        self._omega_n = self._omega_n_from_speed(value)

    @property
    def is_limited(self):
        """是否启用了速度限制"""
        return self._max_speed is not None

    @staticmethod
    def _omega_n_from_speed(max_speed):
        """从 max_speed 推算自然频率（线性插值）。"""
        if max_speed is None:
            return None
        frac = min(max_speed / MAX_PHYSICAL_SPEED, 1.0)
        return OMEGA_N_MIN + frac * (OMEGA_N_MAX - OMEGA_N_MIN)

    def set_from_percentage(self, pct):
        """从 0-100 百分比设置速度。

        100% = 不限制（透传）
        0%   = 完全静止 (0 units/s)
        1-99% 线性映射到 [0, MAX_PHYSICAL_SPEED]
        """
        if pct >= 100.0:
            self._max_speed = None
            self._omega_n = None
        elif pct <= 0.0:
            self._max_speed = 0.0
            self._omega_n = OMEGA_N_MIN
        else:
            frac = pct / 100.0
            self._max_speed = frac * MAX_PHYSICAL_SPEED
            self._omega_n = OMEGA_N_MIN + frac * (OMEGA_N_MAX - OMEGA_N_MIN)

    def get_percentage(self):
        """将当前 max_speed 反映射为 0-100 百分比。

        100% 表示不限制。与 set_from_percentage 互逆。
        """
        if self._max_speed is None:
            return 100.0
        return (self._max_speed / MAX_PHYSICAL_SPEED) * 100.0

    def advance(self, desired_dof):
        """将速度限制位置向 desired_dof 前进一步。

        使用临界阻尼弹簧-阻尼器算法：
        accel = omega_n² × (target - position) - 2 × omega_n × velocity
        velocity += accel × dt   (半隐式 Euler)
        position += velocity × dt

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

        # 完全静止：不移动
        if self._max_speed <= 0.0:
            return SpeedLimitResult(dof=list(self._last_dof), active=False)

        omega_n = self._omega_n if self._omega_n is not None else OMEGA_N_MIN
        result = [0.0] * NUM_DOF
        active = False

        for i in range(NUM_DOF):
            error = desired_dof[i] - self._last_dof[i]

            # snap 判定：误差和速度都极小时直接到达
            if abs(error) < 0.5 and abs(self._velocity[i]) < 0.5:
                result[i] = desired_dof[i]
                self._velocity[i] = 0.0
                continue

            active = True

            # 临界阻尼弹簧-阻尼器加速度
            accel = omega_n * omega_n * error - 2.0 * omega_n * self._velocity[i]

            # 半隐式 Euler + 速度变化率限制
            # 防止大误差时加速度过大导致首步速度跳到极限值，
            # 确保平滑启动（速度渐增而非瞬时达到 max_speed）
            dv = accel * dt
            max_dv = omega_n * self._max_speed * dt
            dv = max(-max_dv, min(max_dv, dv))
            self._velocity[i] += dv

            # 速度钳位：不超过物理极限
            max_v = self._max_speed
            self._velocity[i] = max(-max_v, min(max_v, self._velocity[i]))

            result[i] = self._last_dof[i] + self._velocity[i] * dt
            result[i] = max(0.0, min(FULL_RANGE, result[i]))

        self._last_dof = list(result)
        return SpeedLimitResult(dof=result, active=active)

    def reset(self, current_dof):
        """重置内部跟踪位置和速度（启动时或需要同步时调用）。

        Args:
            current_dof: 10 元素当前 DOF 值列表
        """
        self._last_dof = list(current_dof)
        self._last_time = time.monotonic()
        self._velocity = [0.0] * NUM_DOF
