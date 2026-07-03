"""
Gesture Detector 单元测试 — _classify() 静态方法 + 模型下载路径回归测试。
"""

import os
import sys
import unittest.mock as mock
from pathlib import Path

import pytest

from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector
import l10_right_hand_rock_paper_scissors.gesture_detector as _gd_module


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


class TestModelDownloadPath:
    """回归测试：模型下载目标路径必须是用户可写目录，而非系统目录。"""

    # 用户可写路径（gesture_detector.py 第 73-75 行构建）
    EXPECTED_USER_PATH = str(
        Path.home() / ".local" / "share" / "mediapipe" / "tasks" / "hand_landmarker.task"
    )

    # 旧版系统路径（不应被使用）
    SYSTEM_PATH = (
        "/usr/local/lib/python3.12/dist-packages/"
        "l10_right_hand_rock_paper_scissors/"
        "l10_right_hand_rock_paper_scissors/hand_landmarker.task"
    )

    @mock.patch.object(_gd_module, "_USE_LEGACY_API", False)
    @mock.patch("l10_right_hand_rock_paper_scissors.gesture_detector."
                "HandLandmarker.create_from_options")
    @mock.patch("urllib.request.urlretrieve")
    @mock.patch("os.path.isfile")
    @mock.patch("os.path.exists")
    @mock.patch("zipfile.ZipFile")
    def test_download_target_is_user_writable_path(self, mock_zipfile,
                                                   mock_exists,
                                                   mock_isfile,
                                                   mock_urlretrieve,
                                                   mock_create_options):
        """当模型文件不存在时，下载目标必须是用户可写目录。"""
        captured_target = {}
        download_called = []

        def fake_isfile(path):
            # 下载前返回 False；下载后对主路径返回 True
            if download_called and path == self.EXPECTED_USER_PATH:
                return True
            return False

        def fake_exists(path):
            return False

        def fake_urlretrieve(url, filename):
            captured_target["filename"] = filename
            download_called.append(True)
            return filename, {}

        # zipfile.ZipFile 用作 context manager 时需要支持 __enter__/__exit__
        mock_zipfile.return_value.__enter__ = mock.Mock(
            return_value=mock_zipfile.return_value)
        mock_zipfile.return_value.__exit__ = mock.Mock(return_value=False)

        mock_isfile.side_effect = fake_isfile
        mock_exists.side_effect = fake_exists
        mock_urlretrieve.side_effect = fake_urlretrieve
        mock_create_options.return_value = mock.MagicMock()

        GestureDetector(camera_id=0)

        # 断言：下载目标是用户可写路径
        assert "filename" in captured_target, (
            "urllib.request.urlretrieve 未被调用，"
            "无法验证下载目标路径"
        )
        assert captured_target["filename"] == self.EXPECTED_USER_PATH, (
            f"下载目标路径错误: 得到 {captured_target['filename']},"
            f"期望 {self.EXPECTED_USER_PATH}"
        )
        # 确保不是系统路径
        assert captured_target["filename"] != self.SYSTEM_PATH, (
            "下载目标不应是系统目录: " + self.SYSTEM_PATH
        )

    @mock.patch.object(_gd_module, "_USE_LEGACY_API", False)
    @mock.patch("l10_right_hand_rock_paper_scissors.gesture_detector."
                "HandLandmarker.create_from_options")
    @mock.patch("urllib.request.urlretrieve")
    @mock.patch("os.path.isfile")
    @mock.patch("os.path.exists")
    @mock.patch("zipfile.ZipFile")
    def test_fallback_to_alternate_path_when_primary_invalid(
            self, mock_zipfile, mock_exists, mock_isfile,
            mock_urlretrieve, mock_create_options):
        """主路径模型无效且备用路径有效时，应使用备用路径。"""
        captured_target = {}
        # 备用路径是 mediapipe 包内的路径（与主路径不同）
        alternate_path = os.path.join(
            _gd_module.mp.__path__[0], "tasks", "hand_landmarker.task"
        )

        def fake_isfile(path):
            # 主路径 isfile=False（无效）；备用路径 isfile=True
            if path == alternate_path:
                return True
            return False

        def fake_exists(path):
            # 备用路径存在
            if path == alternate_path:
                return True
            return False

        def fake_urlretrieve(url, filename):
            captured_target["filename"] = filename
            return filename, {}

        def fake_zipfile_init(path, mode):
            # 备用路径视为有效 zip；主路径视为无效 zip
            if path == alternate_path:
                return mock.MagicMock()
            raise zipfile.BadZipFile

        mock_zipfile.side_effect = fake_zipfile_init
        mock_zipfile.return_value.__enter__ = mock.Mock(
            return_value=mock_zipfile.return_value)
        mock_zipfile.return_value.__exit__ = mock.Mock(return_value=False)

        mock_isfile.side_effect = fake_isfile
        mock_exists.side_effect = fake_exists
        mock_urlretrieve.side_effect = fake_urlretrieve
        mock_create_options.return_value = mock.MagicMock()

        GestureDetector(camera_id=0)

        # 应该触发一次下载（到主路径）
        assert captured_target["filename"] == self.EXPECTED_USER_PATH
        # create_from_options 应该被调用（备用路径被使用）
        args, kwargs = mock_create_options.call_args
        used_options = args[0] if args else kwargs.get("options", None)
        assert used_options is not None
        assert used_options.base_options.model_asset_path == alternate_path

    @mock.patch.object(_gd_module, "_USE_LEGACY_API", False)
    @mock.patch("l10_right_hand_rock_paper_scissors.gesture_detector."
                "HandLandmarker.create_from_options")
    @mock.patch("urllib.request.urlretrieve")
    @mock.patch("os.path.isfile")
    @mock.patch("os.path.exists")
    @mock.patch("zipfile.ZipFile")
    def test_raises_when_both_paths_invalid(
            self, mock_zipfile, mock_exists, mock_isfile,
            mock_urlretrieve, mock_create_options):
        """主路径和备用路径均无效时，应抛出 RuntimeError。"""
        def fake_isfile(path):
            return False

        def fake_exists(path):
            return False

        def fake_zipfile_init(path, mode):
            raise zipfile.BadZipFile

        mock_zipfile.side_effect = fake_zipfile_init
        mock_zipfile.return_value.__enter__ = mock.Mock(
            return_value=mock_zipfile.return_value)
        mock_zipfile.return_value.__exit__ = mock.Mock(return_value=False)

        mock_isfile.side_effect = fake_isfile
        mock_exists.side_effect = fake_exists
        mock_urlretrieve.side_effect = lambda url, filename: (filename, {})
        mock_create_options.return_value = mock.MagicMock()

        with pytest.raises(RuntimeError, match="模型无效"):
            GestureDetector(camera_id=0)
