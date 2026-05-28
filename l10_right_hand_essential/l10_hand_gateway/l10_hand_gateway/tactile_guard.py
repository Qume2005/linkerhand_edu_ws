"""
L10 灵巧手触觉紧急停止模块

当手指触觉传感器检测到异常压力时，冻结或回退对应手指的弯曲 DOF，
防止夹伤或损坏硬件。

纯 Python，不依赖 ROS，可独立测试。
"""

import time
from dataclasses import dataclass, field


# ============================================================================
# 手指 → DOF 映射
# ============================================================================

# 每根手指的弯曲 DOF 索引
# 弯曲 DOF 是 reversed: 0=全弯, 255=伸直
FINGER_FLEX_DOFS = {
    0: [0],       # 拇指: DOF0
    1: [2],       # 食指: DOF2
    2: [3],       # 中指: DOF3
    3: [4],       # 无名指: DOF4
    4: [5],       # 小指: DOF5
}

# 每根手指的触觉传感器读数个数
FINGER_COUNT = 5


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class TactileResult:
    """触觉防护过滤结果"""
    safe_dof: list
    frozen_fingers: set = field(default_factory=set)


@dataclass
class _FingerState:
    """单根手指的冻结状态"""
    frozen: bool = False
    frozen_dof: dict = field(default_factory=dict)  # dof_index → frozen_value
    freeze_time: float = 0.0
    cooldown_until: float = 0.0  # 冷却期截止时间，期间不重新冻结


# ============================================================================
# TactileGuard
# ============================================================================

class TactileGuard:
    """触觉紧急停止防护。

    参数:
        threshold: 压力触发阈值 (0-255 范围，基于力矩阵总压力)
        retreat_units: 回退步数 (0=只冻结, >0=回退 N 个单位)
        freeze_duration: 冻结持续时间 (秒)，超时后自动解除
    """

    def __init__(self, threshold=0.1, retreat_units=0.0, freeze_duration=5.0):
        self._threshold = threshold
        self._retreat_units = retreat_units
        self._freeze_duration = freeze_duration

        # 当前力数据
        self._forces = [0.0] * FINGER_COUNT

        # 每根手指的状态
        self._states = {i: _FingerState() for i in range(FINGER_COUNT)}

    @property
    def frozen_fingers(self):
        """当前冻结的手指集合"""
        return {i for i, s in self._states.items() if s.frozen}

    def update_forces(self, finger_pressures):
        """更新各手指压力数据。

        Args:
            finger_pressures: 5 元素列表 (每指总压力) 或更短
        """
        for i in range(min(FINGER_COUNT, len(finger_pressures))):
            self._forces[i] = float(finger_pressures[i])

    def filter(self, target_dof):
        """过滤目标 DOF，冻结或回退危险手指。

        Args:
            target_dof: 10 个 DOF 值列表 (0-255)

        Returns:
            TactileResult
        """
        safe = list(target_dof)
        frozen_fingers = set()
        now = time.monotonic()

        for finger_idx in range(FINGER_COUNT):
            state = self._states[finger_idx]
            force = self._forces[finger_idx]

            # ---- 先检查是否需要解除冻结（超时 or 力下降）----
            if state.frozen:
                timed_out = (now - state.freeze_time) > self._freeze_duration
                force_dropped = force < self._threshold * 0.8
                if timed_out or force_dropped:
                    state.frozen = False
                    state.frozen_dof = {}
                    # 超时解除后设冷却期，防止立即重新冻结
                    if timed_out:
                        state.cooldown_until = 0

            # ---- 检查是否需要冻结 ----
            if not state.frozen and force >= self._threshold:
                if now < state.cooldown_until:
                    continue  # 冷却期内，不重新冻结
                # 新触发冻结
                state.frozen = True
                state.freeze_time = now
                flex_dofs = FINGER_FLEX_DOFS[finger_idx]
                state.frozen_dof = {}
                for di in flex_dofs:
                    val = safe[di]
                    # 回退：向伸直方向移动
                    if self._retreat_units > 0:
                        val = min(255.0, val + self._retreat_units)
                    state.frozen_dof[di] = val

            # ---- 应用冻结限制 ----
            if state.frozen:
                frozen_fingers.add(finger_idx)
                for di, frozen_val in state.frozen_dof.items():
                    # 不允许更弯 (DOF 值不允许小于冻结值)
                    # 允许伸直 (DOF 值可以更大)
                    if safe[di] < frozen_val:
                        safe[di] = frozen_val

        return TactileResult(safe_dof=safe, frozen_fingers=frozen_fingers)

    def reset(self):
        """手动解除所有冻结"""
        for state in self._states.values():
            state.frozen = False
            state.frozen_dof = {}
            state.freeze_time = 0.0
            state.cooldown_until = 0.0
