#!/usr/bin/env python3
"""测试共享 mock 数据 — 所有测试文件必须通过本文件设置 mock。"""

import sys
from unittest.mock import MagicMock

# 内置手势数据（mock GESTURE_PRESETS）
_GESTURE_PRESETS_REAL = {
    "open":      (255, 255, 255, 255, 255, 255, 255, 255, 255, 255),
    "fist":      (122, 145,   0,   0,   0,   0,   0,   0,   0,  92),
    "ok":        (108,  56, 118, 255, 255, 255, 255, 255, 255, 234),
    "pinch":     (108,  56, 118,   0,   0,   0, 132,   0,   0, 234),
    "point":     (116, 142, 255,   0,   0,   0,  49,  36,  81,  50),
    "peace":     ( 96,  48, 255, 255,   0,   0, 255, 255, 255,  89),
    "thumbs_up": (255, 255,   0,   0,   0,   0,   0,   0,   0, 255),
}

# linker_hand_description mock
_mock_lhd = MagicMock()
_mock_lhd.gesture_presets = MagicMock()
_mock_lhd.gesture_presets.GESTURE_PRESETS = _GESTURE_PRESETS_REAL
_mock_lhd.get_urdf_path = MagicMock(return_value="/fake/path/model.xml")
_mock_lhd.get_urdf_dir = MagicMock(return_value="/fake/path")
_mock_lhd.get_model_path = MagicMock(return_value="/fake/path/model.urdf")
_mock_lhd.get_model_dir = MagicMock(return_value="/fake/path")

# 注册到 sys.modules（每个测试文件 import 本模块一次即可）
sys.modules.setdefault('linker_hand_description', _mock_lhd)
sys.modules.setdefault('linker_hand_description.gesture_presets', _mock_lhd.gesture_presets)
