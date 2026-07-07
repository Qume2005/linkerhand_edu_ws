#!/usr/bin/env python3
"""skeleton_widget.py 核心逻辑专项测试。

覆盖本次修复的两个根因:
- _get_image_rect() 的 letterboxing 计算 (与 paintEvent KeepAspectRatio 一致)
- CONTROL_POINTS geom_id 指向指尖 (distal phalanx)，而非中节指骨
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# ── Mock 依赖 (必须在 import 之前) ──────────────────────────────────
for mod_name in [
    'rclpy', 'rclpy.node',
    'sensor_msgs', 'sensor_msgs.msg',
    'std_msgs', 'std_msgs.msg',
    'mujoco',
    'hand_forward_kinematics', 'hand_forward_kinematics.kinematics',
]:
    sys.modules.setdefault(mod_name, MagicMock())

_mock_lhd = MagicMock()
_mock_lhd.get_urdf_path = MagicMock(return_value="/fake/path/model.xml")
sys.modules.setdefault('linker_hand_description', _mock_lhd)

from PySide2.QtWidgets import QApplication, QWidget
from PySide2.QtCore import QRectF, QPointF

from l10_hand_control_panel.skeleton_widget import HandModelWidget, CONTROL_POINTS

_app = QApplication.instance() or QApplication(sys.argv)


def _make_widget(width=640, height=480):
    """创建轻量 HandModelWidget，设置指定尺寸以便测试投影计算。"""
    with patch.object(HandModelWidget, '__init__', _patched_init):
        w = HandModelWidget()
    w.resize(width, height)
    return w


def _patched_init(self, parent=None):
    QWidget.__init__(self, parent)
    self.dof_values = [255] * 10
    self.on_dof_changed = None
    self.on_camera_changed = None
    self._suppress_sync = False
    self._dirty = False
    self._camera_echo_guard = None
    self._cp_screen = [QPointF() for _ in range(5)]
    self._render_w, self._render_h = 640, 480
    self.setMinimumSize(300, 400)


# ══════════════════════════════════════════════════════════════════════
# 1. _get_image_rect() — letterboxing 计算
# ══════════════════════════════════════════════════════════════════════

class TestGetImageRect(unittest.TestCase):
    """_get_image_rect() 的缩放+居中计算，必须与 paintEvent 的
    Qt.KeepAspectRatio 逻辑完全一致。"""

    def _rect(self, w, h):
        widget = _make_widget()
        widget.resize(w, h)
        return widget._get_image_rect()

    # ── 基准情况：widget 比例 = 渲染比例 (4:3 = 640:480) ──

    def test_exact_aspect_ratio_no_letterbox(self):
        """4:3 widget → 渲染图填满，无偏移。"""
        r = self._rect(640, 480)
        self.assertEqual(r.width(), 640)
        self.assertEqual(r.height(), 480)
        self.assertEqual(r.x(), 0)
        self.assertEqual(r.y(), 0)

    def test_double_size_still_fills(self):
        """1280×960 (仍为 4:3) → 同样填满。"""
        r = self._rect(1280, 960)
        self.assertEqual(r.width(), 1280)
        self.assertEqual(r.height(), 960)
        self.assertEqual(r.x(), 0)
        self.assertEqual(r.y(), 0)

    # ── widget 更宽 (宽高比 > 4:3) → 上下填满，左右留黑边 ──

    def test_wider_widget_letterbox_sides(self):
        """800×480 (比 4:3 宽) → 高度填满，水平居中，两侧黑边。"""
        r = self._rect(800, 480)
        # height 填满 → scaled_h = 480, scaled_w = 480 * 4/3 = 640
        self.assertEqual(r.height(), 480)
        self.assertAlmostEqual(r.width(), 640)
        self.assertAlmostEqual(r.x(), (800 - 640) / 2)  # 80
        self.assertEqual(r.y(), 0)

    def test_very_wide_widget(self):
        """1200×400 (很宽) → 高度填满，两侧大黑边。

        注意: scaled_w 使用 int() 截断 (与 Qt scaled() 行为一致)，
        所以实际值为 533 而非 533.33。
        """
        r = self._rect(1200, 400)
        self.assertEqual(r.height(), 400)
        self.assertEqual(r.width(), int(400 * 640 / 480))  # int 截断 = 533
        self.assertAlmostEqual(r.x(), (1200 - r.width()) / 2, places=1)
        self.assertEqual(r.y(), 0)

    # ── widget 更高 (宽高比 < 4:3) → 左右填满，上下留黑边 ──

    def test_taller_widget_letterbox_top_bottom(self):
        """640×800 (比 4:3 高) → 宽度填满，垂直居中，上下黑边。"""
        r = self._rect(640, 800)
        # width 填满 → scaled_w = 640, scaled_h = 640 * 3/4 = 480
        self.assertEqual(r.width(), 640)
        self.assertAlmostEqual(r.height(), 480)
        self.assertEqual(r.x(), 0)
        self.assertAlmostEqual(r.y(), (800 - 480) / 2)  # 160

    def test_very_tall_widget(self):
        """400×1200 (很高) → 宽度填满，上下大黑边。"""
        r = self._rect(400, 1200)
        self.assertEqual(r.width(), 400)
        self.assertAlmostEqual(r.height(), 400 * 480 / 640)
        self.assertAlmostEqual(r.y(), (1200 - r.height()) / 2)
        self.assertEqual(r.x(), 0)

    # ── 关键属性验证 ──

    def test_rect_always_inside_widget(self):
        """渲染图区域始终完全包含在 widget 内。"""
        for w, h in [(640, 480), (800, 480), (640, 800), (400, 400), (1200, 600)]:
            r = self._rect(w, h)
            self.assertGreaterEqual(r.x(), 0, f"left overflow for {w}x{h}")
            self.assertGreaterEqual(r.y(), 0, f"top overflow for {w}x{h}")
            self.assertLessEqual(r.right(), w, f"right overflow for {w}x{h}")
            self.assertLessEqual(r.bottom(), h, f"bottom overflow for {w}x{h}")

    def test_rect_preserves_render_aspect_ratio(self):
        """渲染图保持原始 4:3 宽高比 (int 截断引入 ≤0.5px 误差)。"""
        for w, h in [(800, 480), (640, 800), (1000, 500), (300, 400)]:
            r = self._rect(w, h)
            actual_ratio = r.width() / r.height()
            # int() 截断最多引入 1px 误差 → 比率误差约 1/h < 0.003
            self.assertAlmostEqual(actual_ratio, 640 / 480, places=2,
                                   msg=f"aspect ratio wrong for {w}x{h}: got {actual_ratio}")

    def test_rect_centered(self):
        """渲染图始终居中。"""
        for w, h in [(800, 480), (640, 800), (1000, 600)]:
            r = self._rect(w, h)
            # 左右/上下留白应相等
            self.assertAlmostEqual(r.x(), (w - r.width()) / 2, places=1)
            self.assertAlmostEqual(r.y(), (h - r.height()) / 2, places=1)


# ══════════════════════════════════════════════════════════════════════
# 2. CONTROL_POINTS — geom_id 指向指尖
# ══════════════════════════════════════════════════════════════════════

class TestControlPointsGeomIds(unittest.TestCase):
    """CONTROL_POINTS 的 geom_id 必须指向远节指骨 (distal phalanx)。

    根据 L10 右手模型 XML 的 geom 排列顺序 (含 floor mesh):
      geom[0]  floor
      geom[1]  palm
      geom[2-6]  thumb (base1, base2, metacarpals, proximal, distal)
      geom[7-10] index (metacarpals, proximal, middle, distal)
      geom[11-13] middle (proximal, middle, distal)
      geom[14-17] ring (metacarpals, proximal, middle, distal)
      geom[18-21] pinky (metacarpals, proximal, middle, distal)

    指尖 (distal) geom_id: thumb=6, index=10, middle=13, ring=17, pinky=21
    """

    def test_all_geom_ids_are_distal(self):
        """所有 geom_id 应指向远节指骨 (distal phalanx)。"""
        # 根据模型 XML 确认的指尖 geom_id
        expected = {
            "thumb_tip": 6,
            "index_tip": 10,
            "middle_tip": 13,
            "ring_tip": 17,
            "little_tip": 21,
        }
        actual = {cp["name"]: cp["geom_id"] for cp in CONTROL_POINTS}
        self.assertEqual(actual, expected)

    def test_geom_ids_are_unique(self):
        """5 个控制点的 geom_id 互不重复。"""
        ids = [cp["geom_id"] for cp in CONTROL_POINTS]
        self.assertEqual(len(ids), len(set(ids)), "geom_ids 有重复")

    def test_geom_ids_above_palm(self):
        """所有指尖 geom_id 都大于 palm (geom[1]) 和 floor (geom[0])。"""
        ids = [cp["geom_id"] for cp in CONTROL_POINTS]
        for gid in ids:
            self.assertGreater(gid, 1, f"geom_id {gid} 指向 palm 或 floor")

    def test_geom_ids_not_pointing_to_middle_phalanx(self):
        """geom_id 不应指向中节指骨 (middle phalanx)。

        旧值 (bug) 指到了 middle phalanx:
          thumb=5, index=9, middle=12, ring=16, pinky=20
        新值 (修复后) 指向 distal phalanx:
          thumb=6, index=10, middle=13, ring=17, pinky=21
        """
        # 旧的有 bug 的 geom_id 列表
        old_buggy_ids = {5, 9, 12, 16, 20}
        current_ids = {cp["geom_id"] for cp in CONTROL_POINTS}
        self.assertEqual(
            current_ids & old_buggy_ids, set(),
            f"仍有 geom_id 指向中节指骨 (旧值): {current_ids & old_buggy_ids}"
        )

    def test_each_control_point_has_required_fields(self):
        """每个控制点包含 name, geom_id, dofs, color。"""
        required_keys = {"name", "geom_id", "dofs", "color"}
        for cp in CONTROL_POINTS:
            self.assertEqual(set(cp.keys()), required_keys)

    def test_control_point_count(self):
        """恰好 5 个控制点 (5 指)。"""
        self.assertEqual(len(CONTROL_POINTS), 5)

    def test_dof_lists_non_empty(self):
        """每个控制点的 dofs 列表非空。"""
        for cp in CONTROL_POINTS:
            self.assertTrue(len(cp["dofs"]) > 0, f"{cp['name']} 没有关联 DOF")


class TestSkeletonWidgetResize(unittest.TestCase):
    """resizeEvent 行为测试 — 确保 resize 后控制点缓存立即刷新。"""

    def _widget(self):
        return _make_widget(640, 480)

    def test_resize_updates_control_point_positions(self):
        """resize 后 _cp_screen 基于新尺寸重新计算。"""
        w = self._widget()
        # mock _project_geom 使其返回可追踪的位置
        positions_640 = [QPointF(100 + i * 50, 200) for i in range(5)]
        positions_800 = [QPointF(150 + i * 50, 200) for i in range(5)]
        call_count = [0]

        def fake_project_geom(geom_id):
            call_count[0] += 1
            return positions_640[0] if w.width() == 640 else positions_800[0]

        w._project_geom = fake_project_geom

        w.resize(640, 480)
        w._update_cp_positions()
        self.assertEqual(w._cp_screen[0], positions_640[0])

        # resize 到不同比例 → _project_geom 应被重新调用
        w.resize(800, 480)
        from PySide2.QtGui import QResizeEvent
        event = QResizeEvent(w.size(), w.size())
        w.resizeEvent(event)

        self.assertEqual(w._cp_screen[0], positions_800[0],
                         "resizeEvent 后 _cp_screen 应基于新尺寸重新计算")

    def test_resize_does_not_crash(self):
        """resize 不会导致异常。"""
        w = self._widget()
        # mock _project_geom 避免依赖 MuJoCo 数据
        w._project_geom = lambda geom_id: QPointF(100, 200)
        w.resize(300, 400)
        from PySide2.QtGui import QResizeEvent
        event = QResizeEvent(w.size(), w.size())
        w.resizeEvent(event)  # 不应抛异常


if __name__ == '__main__':
    unittest.main()
