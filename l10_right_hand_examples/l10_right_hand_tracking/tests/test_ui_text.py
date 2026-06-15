"""中文占位文本渲染测试。

锁定「等待摄像头...」在 OpenCV 窗口的渲染：cv2.putText 不支持中文，故用
PIL + CJK 字体绘制。本测试确保字体可解析、渲染不崩溃且实际写入像素（而非全黑）。
"""

import numpy as np

from l10_right_hand_tracking.hand_tracking_node import (
    _draw_centered_cn_text,
    _resolve_cn_font_path,
)


def test_cjk_font_resolved():
    """应能定位到系统 CJK 字体（否则中文会降级为英文）。"""
    assert _resolve_cn_font_path() is not None, "未找到 CJK 字体"


def test_draw_centered_cn_text_preserves_shape():
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    out = _draw_centered_cn_text(img, "等待摄像头...", font_size=42)
    assert out.shape == (480, 640, 3)


def test_draw_centered_cn_text_draws_pixels():
    """渲染结果应含非零像素，证明文字被实际绘制到画面上。"""
    img = np.zeros((480, 640, 3), dtype=np.uint8)
    out = _draw_centered_cn_text(img, "等待摄像头...", font_size=42)
    assert out.any(), "渲染结果全黑 —— 文字未被绘制"
