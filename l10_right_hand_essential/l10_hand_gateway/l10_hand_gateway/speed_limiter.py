"""
L10 灵巧手全局速度映射模块

将 0-100% 滑块范围映射到物理可达速度区间。
轨迹规划由 motion_planner.py 负责，本模块仅做百分比 ↔ 速度映射。

纯 Python，不依赖 ROS，可独立测试。
"""

NUM_DOF = 10
FULL_RANGE = 255.0

# 实测物理最大运动速度 ≈ 旧仿真限速 47% 时的速度 (240 units/s)。
MAX_PHYSICAL_SPEED = 240.0


class SpeedLimiter:
    """纯速度映射器：百分比 ↔ max_speed。不做轨迹规划。

    参数:
        max_speed: 每个关节每秒最大变化量（DOF units/second）。
                   None 表示不限制（直接透传）。
    """

    def __init__(self, max_speed=None):
        self._max_speed = max_speed

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
        0%   = 完全静止 (0 units/s)
        1-99% 线性映射到 [0, MAX_PHYSICAL_SPEED]
        """
        if pct >= 100.0:
            self._max_speed = None
        elif pct <= 0.0:
            self._max_speed = 0.0
        else:
            self._max_speed = (pct / 100.0) * MAX_PHYSICAL_SPEED

    def get_percentage(self):
        """将当前 max_speed 反映射为 0-100 百分比。

        100% 表示不限制。与 set_from_percentage 互逆。
        """
        if self._max_speed is None:
            return 100.0
        return (self._max_speed / MAX_PHYSICAL_SPEED) * 100.0
