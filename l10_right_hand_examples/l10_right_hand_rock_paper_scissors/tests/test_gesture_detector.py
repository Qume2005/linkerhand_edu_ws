"""
Gesture Detector 单元测试 — _classify() 静态方法。
"""

import pytest

from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector


class _FakeLandmark:
    """模拟 mediapipe 的 landmark 对象。"""
    def __init__(self, x, y, z=0.0):
        self.x = x
        self.y = y
        self.z = z


class _FakeLandmarks:
    """模拟 mediapipe 的 landmarks 列表。"""
    def __init__(self, positions):
        self.landmark = [_FakeLandmark(*p) for p in positions]


def _make_landmarks(fingers_extended):
    """构造假 landmarks，控制各手指的弯曲/伸直状态。

    fingers_extended: dict, keys are finger names, values are bool
    返回的 landmarks 满足:
    - wrist at (0, 0)
    - 每个 finger 的 tip 和 pip 坐标根据 extended 状态设定
    """
    # 21 landmarks, 每个是 (x, y, z)
    # 简化模型：wrist=(0,0), pip y=0.3, tip 根据是否伸直设 y
    positions = [[0.0, 0.0, 0.0]] * 21  # 默认全部在原点

    wrist = (0.0, 0.0, 0.0)

    # 手指关节索引: [mcp, pip, dip, tip]
    finger_joints = {
        "thumb":    [1, 2, 3, 4],
        "index":    [5, 6, 7, 8],
        "middle":   [9, 10, 11, 12],
        "ring":     [13, 14, 15, 16],
        "little":   [17, 18, 19, 20],
    }

    # 设定各关节位置
    for finger, joints in finger_joints.items():
        mcp_idx, pip_idx, dip_idx, tip_idx = joints

        # MCP 位置（固定）
        x_offset = {"thumb": -0.05, "index": 0.0, "middle": 0.03,
                     "ring": 0.06, "little": 0.09}
        positions[mcp_idx] = [x_offset[finger], 0.1, 0.0]

        # PIP 位置（固定）
        positions[pip_idx] = [x_offset[finger], 0.2, 0.0]

        # DIP 位置
        positions[dip_idx] = [x_offset[finger], 0.25, 0.0]

        # TIP 位置：伸直时 y 更大（更远离 wrist），弯曲时 y 更小
        if fingers_extended.get(finger, False):
            positions[tip_idx] = [x_offset[finger], 0.4, 0.0]
        else:
            positions[tip_idx] = [x_offset[finger], 0.15, 0.0]

    return _FakeLandmarks(positions)


class TestClassify:
    """测试 GestureDetector._classify()。"""

    def test_all_bent_is_rock(self):
        """全部手指弯曲 → rock。"""
        lm = _make_landmarks({
            "thumb": False, "index": False, "middle": False,
            "ring": False, "little": False,
        })
        assert GestureDetector._classify(lm) == "rock"

    def test_all_extended_is_paper(self):
        """全部手指伸直 → paper。"""
        lm = _make_landmarks({
            "thumb": True, "index": True, "middle": True,
            "ring": True, "little": True,
        })
        assert GestureDetector._classify(lm) == "paper"

    def test_index_middle_extended_is_scissors(self):
        """食指+中指伸直，无名指+小指弯曲 → scissors。

        需要额外设置 index-middle spread > 0.06。
        """
        positions = [[0.0, 0.0, 0.0]] * 21

        # index 伸直, tip 远离 wrist
        positions[5] = [0.0, 0.1, 0.0]   # index MCP
        positions[6] = [0.0, 0.2, 0.0]   # index PIP
        positions[7] = [0.0, 0.25, 0.0]  # index DIP
        positions[8] = [0.0, 0.4, 0.0]   # index TIP (extended)

        # middle 伸直, 但 x 偏移以确保 spread > 0.06
        positions[9]  = [0.1, 0.1, 0.0]  # middle MCP
        positions[10] = [0.1, 0.2, 0.0]  # middle PIP
        positions[11] = [0.1, 0.25, 0.0] # middle DIP
        positions[12] = [0.1, 0.4, 0.0]  # middle TIP (extended)

        # ring 弯曲
        positions[13] = [0.06, 0.1, 0.0]
        positions[14] = [0.06, 0.2, 0.0]
        positions[15] = [0.06, 0.25, 0.0]
        positions[16] = [0.06, 0.15, 0.0]  # ring TIP (bent)

        # little 弯曲
        positions[17] = [0.09, 0.1, 0.0]
        positions[18] = [0.09, 0.2, 0.0]
        positions[19] = [0.09, 0.25, 0.0]
        positions[20] = [0.09, 0.15, 0.0]  # little TIP (bent)

        # thumb 不重要
        positions[1] = [-0.05, 0.1, 0.0]
        positions[2] = [-0.05, 0.2, 0.0]
        positions[3] = [-0.05, 0.25, 0.0]
        positions[4] = [-0.05, 0.15, 0.0]

        lm = _FakeLandmarks(positions)
        assert GestureDetector._classify(lm) == "scissors"

    def test_ambiguous_returns_none(self):
        """不明确的手势 → none。"""
        # 只有 index 伸直，其余弯曲 → 不是任何标准手势
        lm = _make_landmarks({
            "thumb": False, "index": True, "middle": False,
            "ring": False, "little": False,
        })
        result = GestureDetector._classify(lm)
        assert result == "none"
