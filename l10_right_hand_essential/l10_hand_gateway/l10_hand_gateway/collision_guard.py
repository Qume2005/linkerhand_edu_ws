"""
L10 灵巧手碰撞防护模块（基于 FK 查找表）

两条规则：
- ThumbRule: 限制拇指三自由度 (DOF0/DOF1/DOF9)，基于预计算的碰撞边界查找表
  thumb_vs_index 查找表为 4D 格式（含 DOF6 食指侧摆维度），
  其余手指（middle/ring/pinky）为 3D 格式。
- LateralRule: 限制无名指/小指侧摆 (DOF7/DOF8)，基于预计算的碰撞边界

查找表由 scripts/fk_collision_analysis.py 生成。

所有类为纯 Python，不依赖 ROS，可独立测试。
"""

import json
import os
from dataclasses import dataclass, field


# ============================================================================
# 数据结构
# ============================================================================

@dataclass
class RuleResult:
    """单条规则的检查结果"""
    rule_name: str
    blocked: bool
    dof_index: int
    original: float
    clamped: float


@dataclass
class GuardResult:
    """整体检查结果"""
    safe_dof: list
    violations: list = field(default_factory=list)
    frozen_dofs: set = field(default_factory=set)


# ============================================================================
# 查找表加载与查询
# ============================================================================

_TABLE_PATH = os.path.join(
    os.path.dirname(__file__), 'collision_tables.json'
)


def _load_tables(path=None):
    """加载碰撞查找表 JSON。"""
    p = path or _TABLE_PATH
    with open(p) as f:
        return json.load(f)


def _find_nearest_index(samples, value):
    """在采样点数组中找到最接近 value 的索引。"""
    best_idx = 0
    best_dist = abs(samples[0] - value)
    for i in range(1, len(samples)):
        d = abs(samples[i] - value)
        if d < best_dist:
            best_dist = d
            best_idx = i
    return best_idx


# ============================================================================
# ThumbRule — 拇指三自由度限制
# ============================================================================

class ThumbRule:
    """拇指 vs 四指碰撞防护。

    查找表结构:
    - thumb_vs_index: 4D 格式 (DOF1_bucket, DOF9_bucket, DOF6_bucket, finger_flex_bucket) → DOF0_min_safe
    - 其余手指: 3D 格式 (DOF1_bucket, DOF9_bucket, finger_flex_bucket) → DOF0_min_safe
    DOF0_min_safe 表示 DOF0 必须 >= 此值才能避免碰撞（DOF0 越大越伸直）。

    执行逻辑:
    1. 对每根手指查表得到 DOF0 安全下限
    2. 取最严格的限制
    3. 如果 DOF0 限制 >= 252（几乎全伸直也不够），额外限制 DOF9
    """

    FINGER_KEYS = ["thumb_vs_index", "thumb_vs_middle", "thumb_vs_ring", "thumb_vs_pinky"]
    FINGER_FLEX_DOFS = [2, 3, 4, 5]  # 对应 index/middle/ring/pinky

    def __init__(self, tables=None):
        self._tables = tables or _load_tables()
        self._finger_data = []
        for key, flex_dof in zip(self.FINGER_KEYS, self.FINGER_FLEX_DOFS):
            self._finger_data.append({
                "key": key,
                "flex_dof": flex_dof,
                "data": self._tables[key],
            })

    def query_dof0_limit(self, dof1_val, dof9_val, finger_flexions, dof6_val=None):
        """查询给定 (DOF1, DOF9, 四指弯曲, DOF6) 下的 DOF0 安全下限。

        纯查询，不修改任何值。供运动规划器在轨迹生成前调用。

        Args:
            dof1_val: DOF1 值 (拇指侧摆)
            dof9_val: DOF9 值 (拇指旋转/对指)
            finger_flexions: 4 元素序列 [index, middle, ring, pinky] 弯曲值
            dof6_val: DOF6 值 (食指侧摆)，用于 thumb_vs_index 的 4D 查询

        Returns:
            float: DOF0_min_safe — DOF0 必须 >= 此值才能避免碰撞。
                   0.0 表示无碰撞风险。
        """
        dof0_limits = []
        for fd, flex in zip(self._finger_data, finger_flexions):
            # thumb_vs_index 使用 4D 查询（含 DOF6），其余使用 3D 查询
            has_dof6 = "dof6_samples" in fd["data"]
            d6 = dof6_val if has_dof6 else None
            best_limit = self._query_finger_limit(
                fd["data"], dof1_val, dof9_val, flex, dof6_val=d6)
            if best_limit is not None:
                dof0_limits.append(best_limit)

        if not dof0_limits:
            return 0.0
        return max(dof0_limits)

    def _query_finger_limit(self, data, dof1_val, dof9_val, finger_flex, dof6_val=None):
        """查询单根手指的 DOF0 安全下限。

        4D 表（含 dof6_samples）使用 3×3×3×3 邻域搜索。
        3D 表使用 3×3×3 邻域搜索。
        """
        n = data["resolution"]
        d1i = _find_nearest_index(data["dof1_samples"], dof1_val)
        d9i = _find_nearest_index(data["dof9_samples"], dof9_val)
        fi = _find_nearest_index(data["flex_samples"], finger_flex)

        has_dof6 = "dof6_samples" in data
        if has_dof6:
            d6i = _find_nearest_index(data["dof6_samples"], dof6_val if dof6_val is not None else 0.0)
            d6_range = range(max(0, d6i - 2), min(n, d6i + 3))
        else:
            d6_range = [None]

        best_limit = None
        for dd6 in d6_range:
            for dd1 in range(max(0, d1i - 2), min(n, d1i + 3)):
                for dd9 in range(max(0, d9i - 2), min(n, d9i + 3)):
                    for df in range(max(0, fi - 2), min(n, fi + 3)):
                        if has_dof6:
                            key = f"{dd1},{dd9},{dd6},{df}"
                        else:
                            key = f"{dd1},{dd9},{df}"
                        if key in data["lookup"]:
                            val = data["lookup"][key]
                            if best_limit is None or val > best_limit:
                                best_limit = val
        return best_limit

    def check(self, target_dof):
        """检查并修正拇指 DOF。

        Returns:
            (safe_dof, violations) — 修正后的 DOF 列表和违规记录
        """
        safe = list(target_dof)
        violations = []

        dof0_original = safe[0]
        dof1_val = safe[1]
        dof9_val = safe[9]
        dof6_val = safe[6]

        # 对每根手指查表，收集 DOF0 安全下限
        finger_flexions = [safe[fd["flex_dof"]] for fd in self._finger_data]
        dof0_limit = self.query_dof0_limit(
            dof1_val, dof9_val, finger_flexions, dof6_val=dof6_val)

        if dof0_limit <= 0.0:
            return safe, violations

        # 限制 DOF0
        if safe[0] < dof0_limit:
            safe[0] = min(dof0_limit, 255.0)
            violations.append(RuleResult(
                rule_name="thumb_flex", blocked=True,
                dof_index=0, original=dof0_original, clamped=safe[0],
            ))

        # DOF0 限制较高（>= 200）时，仅靠伸直拇指不够，
        # 需要同时减少对指（DOF9↑）和收拢侧摆（DOF1↓）
        if dof0_limit >= 200:
            # DOF9: 推向 255（减少对指），力度随限制值增大
            dof9_original = safe[9]
            push9 = max(30, (dof0_limit - 240) * 3)
            safe[9] = min(255.0, dof9_val + push9)
            if safe[9] != dof9_original:
                violations.append(RuleResult(
                    rule_name="thumb_opposition", blocked=True,
                    dof_index=9, original=dof9_original, clamped=safe[9],
                ))

            # DOF1: 拉向 0（收拢到掌心），减少拇指与手指的侧向重叠
            dof1_original = safe[1]
            pull1 = max(50, (dof0_limit - 240) * 2)
            safe[1] = max(0.0, dof1_val - pull1)
            if safe[1] != dof1_original:
                violations.append(RuleResult(
                    rule_name="thumb_lateral_pull", blocked=True,
                    dof_index=1, original=dof1_original, clamped=safe[1],
                ))

        return safe, violations


# ============================================================================
# LateralRule — 小指-无名指侧摆限制
# ============================================================================

class LateralRule:
    """小指 vs 无名指侧摆碰撞防护。

    碰撞发生在 DOF7 高（无名指向外展开）+ DOF8 低（小指未展开）时。
    查找表: (DOF7_bucket, DOF8_bucket) → collision (bool)

    执行逻辑:
    1. 查表判断当前 DOF7/DOF8 组合是否碰撞
    2. 如果碰撞，将 DOF7 和 DOF8 向安全方向拉近
    """

    def __init__(self, tables=None):
        self._tables = tables or _load_tables()
        self._data = self._tables["pinky_ring_lateral"]

    def check(self, target_dof):
        """检查并修正 DOF7/DOF8。

        Returns:
            (safe_dof, violations) — 修正后的 DOF 列表和违规记录
        """
        safe = list(target_dof)
        violations = []

        d7_val = safe[7]
        d8_val = safe[8]
        data = self._data
        n7 = len(data["dof7_samples"])
        n8 = len(data["dof8_samples"])

        d7i = _find_nearest_index(data["dof7_samples"], d7_val)
        d8i = _find_nearest_index(data["dof8_samples"], d8_val)

        # 邻域检查：检查 ±2 范围内是否有碰撞点，避免采样间隙漏检
        is_collision = False
        for dd7 in range(max(0, d7i - 2), min(n7, d7i + 3)):
            for dd8 in range(max(0, d8i - 2), min(n8, d8i + 3)):
                if f"{dd7},{dd8}" in data["collision_map"]:
                    is_collision = True
                    break
            if is_collision:
                break

        if not is_collision:
            return safe, violations

        # 碰撞: 将 DOF7 降低（减少无名指外展）和 DOF8 升高（增加小指展开）
        # 策略: 找到最近的非碰撞点，线性插值
        d7_original = safe[7]
        d8_original = safe[8]

        # 找非碰撞的邻居
        safe_d7 = d7_val
        safe_d8 = d8_val

        # 尝试降低 DOF7
        for step in range(1, len(data["dof7_samples"])):
            new_d7i = max(0, d7i - step)
            if f"{new_d7i},{d8i}" not in data["collision_map"]:
                safe_d7 = data["dof7_samples"][new_d7i]
                break

        # 尝试升高 DOF8
        for step in range(1, len(data["dof8_samples"])):
            new_d8i = min(len(data["dof8_samples"]) - 1, d8i + step)
            if f"{d7i},{new_d8i}" not in data["collision_map"]:
                safe_d8 = data["dof8_samples"][new_d8i]
                break

        # 取距离最近的修正方案
        d7_shift = abs(safe_d7 - d7_val)
        d8_shift = abs(safe_d8 - d8_val)

        if d7_shift <= d8_shift and safe_d7 != d7_val:
            # 降低 DOF7 更近
            safe[7] = safe_d7
            violations.append(RuleResult(
                rule_name="pinky_ring_d7", blocked=True,
                dof_index=7, original=d7_original, clamped=safe[7],
            ))
        elif safe_d8 != d8_val:
            safe[8] = safe_d8
            violations.append(RuleResult(
                rule_name="pinky_ring_d8", blocked=True,
                dof_index=8, original=d8_original, clamped=safe[8],
            ))
        else:
            # 两者都需要修改，取改动小的那个
            safe[7] = safe_d7
            violations.append(RuleResult(
                rule_name="pinky_ring_d7", blocked=True,
                dof_index=7, original=d7_original, clamped=safe[7],
            ))

        return safe, violations


# ============================================================================
# JointRuleGuard — 组合门面
# ============================================================================

class JointRuleGuard:
    """组合拇指规则和侧摆规则的碰撞防护。"""

    def __init__(self, tables=None):
        self._thumb_rule = ThumbRule(tables)
        self._lateral_rule = LateralRule(tables)

    @property
    def thumb_rule(self):
        """内部 ThumbRule 实例（供 MotionPlanner 拇指路径规划使用）。"""
        return self._thumb_rule

    def check(self, target_dof):
        """检查并修正目标 DOF。

        Args:
            target_dof: 10 个 DOF 值列表 (0-255)

        Returns:
            GuardResult

        Raises:
            ValueError: 输入长度不足 10
        """
        if len(target_dof) < 10:
            raise ValueError(f"Expected 10 DOF values, got {len(target_dof)}")

        safe = list(target_dof)
        violations = []

        # 先执行拇指规则
        safe, thumb_violations = self._thumb_rule.check(safe)
        violations.extend(thumb_violations)

        # 再执行侧摆规则
        safe, lateral_violations = self._lateral_rule.check(safe)
        violations.extend(lateral_violations)

        return GuardResult(safe_dof=safe, violations=violations)
