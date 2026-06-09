"""
手势预设配置单元测试 — TDD 红灯阶段。

验证 linker_hand_description.gesture_presets 模块导出的所有常量满足：
- 结构正确（10 个 DOF）
- 值域合法（0-255）
- 类型不可变（tuple）
- 语义一致性（游戏姿态与通用预设的对应关系）
"""

import pytest


# ══════════════════════════════════════════════════════════════════════
# DOF_ORDER 测试
# ══════════════════════════════════════════════════════════════════════

class TestDOFOrder:
    """DOF_ORDER 规范顺序。"""

    def test_has_10_entries(self):
        from linker_hand_description.gesture_presets import DOF_ORDER
        assert len(DOF_ORDER) == 10

    def test_no_duplicates(self):
        from linker_hand_description.gesture_presets import DOF_ORDER
        assert len(set(DOF_ORDER)) == 10

    def test_is_tuple(self):
        from linker_hand_description.gesture_presets import DOF_ORDER
        assert isinstance(DOF_ORDER, tuple)

    def test_all_strings(self):
        from linker_hand_description.gesture_presets import DOF_ORDER
        for name in DOF_ORDER:
            assert isinstance(name, str)


# ══════════════════════════════════════════════════════════════════════
# GESTURE_PRESETS 测试
# ══════════════════════════════════════════════════════════════════════

REQUIRED_PRESETS = ("open", "fist", "ok", "pinch", "point", "peace", "thumbs_up")


class TestGesturePresets:
    """通用手势预设。"""

    def test_all_presets_have_10_dof(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        for name, pose in GESTURE_PRESETS.items():
            assert len(pose) == 10, f"{name} 应有 10 个 DOF，实际 {len(pose)}"

    def test_all_values_in_range(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        for name, pose in GESTURE_PRESETS.items():
            for i, v in enumerate(pose):
                assert 0 <= v <= 255, f"{name}[{i}]={v} 超出 [0, 255] 范围"

    def test_required_presets_exist(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        for name in REQUIRED_PRESETS:
            assert name in GESTURE_PRESETS, f"缺少预设: {name}"

    def test_presets_are_tuples(self):
        """配置值应为 tuple，防止误修改。"""
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        for name, pose in GESTURE_PRESETS.items():
            assert isinstance(pose, tuple), f"{name} 应为 tuple，实际 {type(pose)}"

    def test_all_elements_are_int(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        for name, pose in GESTURE_PRESETS.items():
            for i, v in enumerate(pose):
                assert isinstance(v, int), f"{name}[{i}]={v} 应为 int"


# ══════════════════════════════════════════════════════════════════════
# 游戏专用姿态测试
# ══════════════════════════════════════════════════════════════════════

class TestGamePoses:
    """RPS 游戏专用姿态。"""

    @pytest.fixture(params=["READY_POSE", "ROCK_POSE", "PAPER_POSE",
                            "SCISSORS_POSE", "SHAKE_POSE"])
    def pose(self, request):
        from linker_hand_description import gesture_presets
        return getattr(gesture_presets, request.param)

    def test_has_10_dof(self, pose):
        assert len(pose) == 10

    def test_values_in_range(self, pose):
        assert all(0 <= v <= 255 for v in pose)

    def test_is_tuple(self, pose):
        assert isinstance(pose, tuple)

    def test_paper_equals_open(self):
        from linker_hand_description.gesture_presets import (
            GESTURE_PRESETS, PAPER_POSE,
        )
        assert PAPER_POSE == GESTURE_PRESETS["open"]

    def test_rock_equals_fist(self):
        from linker_hand_description.gesture_presets import (
            GESTURE_PRESETS, ROCK_POSE,
        )
        assert ROCK_POSE == GESTURE_PRESETS["fist"]

    def test_scissors_equals_peace(self):
        from linker_hand_description.gesture_presets import (
            GESTURE_PRESETS, SCISSORS_POSE,
        )
        assert SCISSORS_POSE == GESTURE_PRESETS["peace"]

    def test_shake_equals_rock(self):
        from linker_hand_description.gesture_presets import ROCK_POSE, SHAKE_POSE
        assert SHAKE_POSE == ROCK_POSE
