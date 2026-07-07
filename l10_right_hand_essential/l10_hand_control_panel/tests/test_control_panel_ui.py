#!/usr/bin/env python3
"""control_panel.py UI 组件自动化测试。

使用真实 QApplication (offscreen) 测试 UI 组件的行为：
- DualSlider / SpeedSlider 值映射与交互
- HeatmapWidget 颜色映射
- TactileStripWidget 数据分发
- ControlPanelWindow 初始化状态、按钮点击完整功能链路
- _syncing 防循环机制

Mock 策略: mock ROS (rclpy) + MuJoCo + FK 依赖, 保留真实 PySide2。
HandModelWidget.__init__ 被 patch 为轻量版，避免 MuJoCo 渲染 segfault。
"""

import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch

# offscreen 模式，无需显示器
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

# ── Mock ROS + MuJoCo + FK 依赖 (必须在 import control_panel 之前) ──
for mod_name in [
    'rclpy', 'rclpy.node',
    'sensor_msgs', 'sensor_msgs.msg',
    'std_msgs', 'std_msgs.msg',
    'mujoco',
    'hand_forward_kinematics', 'hand_forward_kinematics.kinematics',
]:
    sys.modules.setdefault(mod_name, MagicMock())

# linker_hand_description 提供 gesture_presets（共享手势配置）。
# 由于该包可能未安装，用 MagicMock 替代并注入真实手势预设数据。
from tests._shared_mocks import _GESTURE_PRESETS_REAL

from PySide2.QtWidgets import QApplication, QWidget
from PySide2.QtCore import Qt, QTimer

from l10_hand_control_panel.control_panel import (
    DualSlider, SpeedSlider, HeatmapWidget, TactileStripWidget,
    ControlPanelWindow, DOF_DEFINITIONS,
)
from l10_hand_control_panel.skeleton_widget import HandModelWidget

# 确保 QApplication 单例
_app = QApplication.instance() or QApplication(sys.argv)


def _patched_hand_model_init(self, parent=None):
    """轻量版 HandModelWidget.__init__，跳过 MuJoCo 初始化。

    保留 QWidget 初始化和必要属性，使 ControlPanelWindow 能正常构建布局。
    """
    QWidget.__init__(self, parent)
    self.dof_values = [255] * 10
    self.on_dof_changed = None
    self.on_camera_changed = None
    self._suppress_sync = False
    self._dirty = False
    self._camera_echo_guard = None
    self.setMinimumSize(300, 400)


def _create_window():
    """创建 ControlPanelWindow，patch HandModelWidget 避免 MuJoCo segfault。"""
    with patch.object(HandModelWidget, '__init__', _patched_hand_model_init):
        # 不启动 QTimer，避免 _tick 在测试中触发渲染
        with patch.object(QTimer, 'start'):
            window = ControlPanelWindow()
    return window


# ══════════════════════════════════════════════════════════════════════
# 1. DualSlider
# ══════════════════════════════════════════════════════════════════════


class TestDualSlider(unittest.TestCase):
    """DualSlider 控件行为测试。"""

    def setUp(self):
        self.slider = DualSlider(val_range=(0, 255))
        self.slider.resize(200, 22)

    def test_initial_target_is_zero(self):
        self.assertAlmostEqual(self.slider._target, 0.0)

    def test_set_target_updates_state(self):
        self.slider.set_target(128)
        self.assertAlmostEqual(self.slider._target, 128.0)
        self.assertEqual(self.slider.get_target_int(), 128)

    def test_set_target_clamps_high(self):
        self.slider.set_target(300)
        self.assertAlmostEqual(self.slider._target, 255.0)
        self.assertEqual(self.slider.get_target_int(), 255)

    def test_set_target_clamps_low(self):
        self.slider.set_target(-10)
        self.assertAlmostEqual(self.slider._target, 0.0)
        self.assertEqual(self.slider.get_target_int(), 0)

    def test_set_current_clamps(self):
        self.slider.set_current(500)
        self.assertAlmostEqual(self.slider._current, 255.0)
        self.slider.set_current(-100)
        self.assertAlmostEqual(self.slider._current, 0.0)

    def test_get_target_int_rounds(self):
        self.slider.set_target(127.6)
        self.assertEqual(self.slider.get_target_int(), 128)
        self.slider.set_target(127.4)
        self.assertEqual(self.slider.get_target_int(), 127)

    def test_val_to_x_x_to_val_roundtrip(self):
        """几何映射可逆性: val → x → val 近似相等。"""
        for v in [0, 64, 128, 192, 255]:
            x = self.slider._val_to_x(v)
            val_back = self.slider._x_to_val(x)
            self.assertAlmostEqual(val_back, v, delta=0.5,
                                   msg=f"roundtrip failed for val={v}")

    def test_x_to_val_clamps_out_of_bounds(self):
        """超出滑槽范围的 x 钳制到 [0, 255]。"""
        self.assertAlmostEqual(self.slider._x_to_val(-100), 0.0)
        self.assertAlmostEqual(self.slider._x_to_val(9999), 255.0)

    def test_mouse_drag_updates_target(self):
        """模拟拖动: _apply_mouse 更新 _target 并发射 valueChanged。"""
        self.slider.show()
        emitted = []
        self.slider.valueChanged.connect(lambda: emitted.append(True))
        mid_x = self.slider.width() / 2
        self.slider._apply_mouse(mid_x)
        val = self.slider.get_target_int()
        self.assertTrue(120 <= val <= 135, f"Expected ~127, got {val}")
        self.assertEqual(len(emitted), 1)

    def test_set_target_does_not_emit_signal(self):
        """set_target 不应该发射 valueChanged 信号（仅拖动时发射）。"""
        emitted = []
        self.slider.valueChanged.connect(lambda: emitted.append(True))
        self.slider.set_target(128)
        self.assertEqual(len(emitted), 0)


# ══════════════════════════════════════════════════════════════════════
# 2. SpeedSlider
# ══════════════════════════════════════════════════════════════════════


class TestSpeedSlider(unittest.TestCase):
    """SpeedSlider 控件行为测试。"""

    def setUp(self):
        self.slider = SpeedSlider(val_range=(0, 100))
        self.slider.resize(200, 22)

    def test_default_target_100(self):
        self.assertAlmostEqual(self.slider._target, 100.0)
        self.assertEqual(self.slider.get_target_int(), 100)

    def test_set_target_clamps_to_range(self):
        self.slider.set_target(150)
        self.assertAlmostEqual(self.slider._target, 100.0)
        self.slider.set_target(-10)
        self.assertAlmostEqual(self.slider._target, 0.0)

    def test_get_target_int_rounds(self):
        self.slider.set_target(75.6)
        self.assertEqual(self.slider.get_target_int(), 76)

    def test_mouse_drag_emits_signal(self):
        emitted = []
        self.slider.valueChanged.connect(lambda: emitted.append(True))
        self.slider._apply_mouse(self.slider.width() / 2)
        self.assertEqual(len(emitted), 1)


# ══════════════════════════════════════════════════════════════════════
# 3. HeatmapWidget 颜色映射
# ══════════════════════════════════════════════════════════════════════


class TestHeatmapWidget(unittest.TestCase):
    """HeatmapWidget 颜色映射（核心逻辑）。"""

    def test_value_to_color_min(self):
        color = HeatmapWidget._value_to_color(0)
        self.assertEqual(color.red(), 13)
        self.assertEqual(color.green(), 8)
        self.assertEqual(color.blue(), 135)

    def test_value_to_color_max(self):
        color = HeatmapWidget._value_to_color(255)
        self.assertEqual(color.red(), 240)
        self.assertEqual(color.green(), 249)
        self.assertEqual(color.blue(), 33)

    def test_value_to_color_midpoint_first_segment(self):
        """val≈84 (t≈0.33) → 接近第二个 stop (126, 3, 168)。"""
        color = HeatmapWidget._value_to_color(84)
        self.assertAlmostEqual(color.red(), 126, delta=5)
        self.assertAlmostEqual(color.green(), 3, delta=5)
        self.assertAlmostEqual(color.blue(), 168, delta=5)

    def test_value_to_color_midpoint_second_segment(self):
        """val≈168 (t≈0.66) → 接近第三个 stop (204, 71, 120)。"""
        color = HeatmapWidget._value_to_color(168)
        self.assertAlmostEqual(color.red(), 204, delta=5)
        self.assertAlmostEqual(color.green(), 71, delta=5)
        self.assertAlmostEqual(color.blue(), 120, delta=5)

    def test_value_to_color_negative_clamped(self):
        c_neg = HeatmapWidget._value_to_color(-10)
        c_zero = HeatmapWidget._value_to_color(0)
        self.assertEqual(c_neg.red(), c_zero.red())
        self.assertEqual(c_neg.green(), c_zero.green())
        self.assertEqual(c_neg.blue(), c_zero.blue())

    def test_value_to_color_over_255_clamped(self):
        c_over = HeatmapWidget._value_to_color(300)
        c_max = HeatmapWidget._value_to_color(255)
        self.assertEqual(c_over.red(), c_max.red())
        self.assertEqual(c_over.green(), c_max.green())
        self.assertEqual(c_over.blue(), c_max.blue())

    def test_set_matrix_data_updates_internal_state(self):
        widget = HeatmapWidget(0)
        matrix = [[i * j for j in range(6)] for i in range(12)]
        widget.set_matrix_data(matrix)
        self.assertEqual(widget._data, matrix)

    def test_set_mass_updates_internal_state(self):
        widget = HeatmapWidget(0)
        widget.set_mass(42.5)
        self.assertAlmostEqual(widget._mass, 42.5)

    def test_finger_names_count(self):
        self.assertEqual(len(HeatmapWidget.FINGER_NAMES), 5)

    def test_finger_colors_count(self):
        self.assertEqual(len(HeatmapWidget.FINGER_COLORS), 5)


# ══════════════════════════════════════════════════════════════════════
# 4. TactileStripWidget 数据分发
# ══════════════════════════════════════════════════════════════════════


class TestTactileStripWidget(unittest.TestCase):
    """TactileStripWidget 触觉数据分发逻辑。"""

    def setUp(self):
        self.strip = TactileStripWidget()
        self.mock_heatmaps = [MagicMock() for _ in self.strip.heatmaps]
        self.strip.heatmaps = self.mock_heatmaps

    def test_dispatches_matrix_to_correct_finger(self):
        matrix = [[i for i in range(6)] for _ in range(12)]
        self.strip.update_tactile({"little_matrix": matrix}, {})
        self.mock_heatmaps[0].set_matrix_data.assert_called_once_with(matrix)

    def test_dispatches_mass_to_correct_finger(self):
        self.strip.update_tactile({}, {"thumb_mass": 42.5})
        self.mock_heatmaps[4].set_mass.assert_called_once_with(42.5)

    def test_ignores_unknown_keys(self):
        """未知 key 不崩溃，不调用任何子控件。"""
        self.strip.update_tactile({"unknown_matrix": []}, {"unknown_mass": 1.0})
        for mh in self.mock_heatmaps:
            mh.set_matrix_data.assert_not_called()
            mh.set_mass.assert_not_called()

    def test_mass_list_extracts_first_element(self):
        self.strip.update_tactile({}, {"index_mass": [5.0]})
        self.mock_heatmaps[3].set_mass.assert_called_once_with(5.0)

    def test_mass_list_empty_uses_zero(self):
        self.strip.update_tactile({}, {"ring_mass": []})
        self.mock_heatmaps[1].set_mass.assert_called_once_with(0.0)

    def test_all_five_fingers_dispatched(self):
        matrix = [[0] * 6 for _ in range(12)]
        fingers = ["little", "ring", "middle", "index", "thumb"]
        matrix_data = {f"{n}_matrix": matrix for n in fingers}
        mass_data = {f"{n}_mass": float(i) for i, n in enumerate(fingers)}
        self.strip.update_tactile(matrix_data, mass_data)
        for i, mh in enumerate(self.mock_heatmaps):
            mh.set_matrix_data.assert_called_once_with(matrix)
            mh.set_mass.assert_called_once_with(float(i))


# ══════════════════════════════════════════════════════════════════════
# 5. ControlPanelWindow 初始化状态
# ══════════════════════════════════════════════════════════════════════


class TestControlPanelWindowInit(unittest.TestCase):
    """ControlPanelWindow 初始化状态验证。"""

    @classmethod
    def setUpClass(cls):
        cls.window = _create_window()

    def test_window_title(self):
        self.assertEqual(self.window.windowTitle(), "L10 Hand Control Panel")

    def test_window_size(self):
        """窗口最小尺寸为 1100×650，高度可动态调整。"""
        self.assertEqual(self.window.width(), 1100)
        self.assertGreaterEqual(self.window.height(), 650)

    def test_10_sliders_created(self):
        self.assertEqual(len(self.window.sliders), 10)

    def test_10_val_labels_created(self):
        self.assertEqual(len(self.window.val_labels), 10)

    def test_slider_defaults_match_dof_definitions(self):
        for i, slider in enumerate(self.window.sliders):
            expected = DOF_DEFINITIONS[i]["default"]
            self.assertEqual(slider.get_target_int(), expected,
                             f"Slider {i} default mismatch")

    def test_val_labels_show_defaults(self):
        for i, label in enumerate(self.window.val_labels):
            expected = str(DOF_DEFINITIONS[i]["default"])
            self.assertEqual(label.text(), expected,
                             f"Label {i} text mismatch")

    def test_speed_slider_default_75(self):
        self.assertEqual(self.window._speed_slider.get_target_int(), 75)

    def test_speed_label_shows_75(self):
        self.assertEqual(self.window._speed_label.text(), "75%")

    def test_skeleton_widget_exists(self):
        self.assertIsNotNone(self.window.skeleton)

    def test_tactile_strip_exists(self):
        self.assertIsNotNone(self.window.tactile_strip)

    def test_tactile_strip_has_5_heatmaps(self):
        self.assertEqual(len(self.window.tactile_strip.heatmaps), 5)

    def test_syncing_initially_false(self):
        self.assertFalse(self.window._syncing)


# ══════════════════════════════════════════════════════════════════════
# 6. 按钮存在性与文本
# ══════════════════════════════════════════════════════════════════════


class TestControlPanelButtons(unittest.TestCase):
    """按钮存在性、文本和可用性验证。"""

    @classmethod
    def setUpClass(cls):
        cls.window = _create_window()
        from PySide2.QtWidgets import QPushButton
        cls.buttons = cls.window.findChildren(QPushButton)

    def test_action_buttons_exist(self):
        texts = [b.text() for b in self.buttons]
        for name in ["抓取", "张开", "复位"]:
            self.assertIn(name, texts, f"按钮 '{name}' 未找到")

    def test_preset_buttons_exist(self):
        texts = [b.text() for b in self.buttons]
        for name in ["握拳", "OK", "捏取", "指向"]:
            self.assertIn(name, texts, f"预设按钮 '{name}' 未找到")

    def test_all_buttons_enabled(self):
        for btn in self.buttons:
            self.assertTrue(btn.isEnabled(),
                            f"按钮 '{btn.text()}' 不可用")

    def test_preset_label_exists(self):
        """预设手势按钮已迁移到手势管理面板中。"""
        from PySide2.QtWidgets import QLabel
        # 旧版 "预设手势:" 标签已移除，预设按钮统一到 GestureManagePanel
        self.assertIsNotNone(self.window._gesture_panel)


# ══════════════════════════════════════════════════════════════════════
# 7. 按钮点击完整功能链路
# ══════════════════════════════════════════════════════════════════════


class TestControlPanelButtonActions(unittest.TestCase):
    """按钮点击完整功能链路测试。

    每个测试验证: 点击 → 滑块值 → 标签文本 → skeleton DOF → ROS 发布。
    """

    def setUp(self):
        self.window = _create_window()
        self.mock_ros = MagicMock()
        self.window.set_ros_node(self.mock_ros)

    def _verify_full_chain(self, expected_values, msg_prefix=""):
        """验证完整效果链: 滑块 + 标签 + ROS 发布 + syncing 恢复。"""
        # 滑块值
        for i, slider in enumerate(self.window.sliders):
            self.assertEqual(slider.get_target_int(), expected_values[i],
                             f"{msg_prefix}Slider[{i}] value mismatch")
        # 标签文本
        for i, label in enumerate(self.window.val_labels):
            self.assertEqual(label.text(), str(expected_values[i]),
                             f"{msg_prefix}Label[{i}] text mismatch")
        # ROS 发布
        self.mock_ros.publish_dof.assert_called()
        last_call_args = self.mock_ros.publish_dof.call_args[0][0]
        self.assertEqual(last_call_args, expected_values,
                         f"{msg_prefix}ROS publish_dof args mismatch")
        # syncing 恢复
        self.assertFalse(self.window._syncing, f"{msg_prefix}_syncing not reset")

    def test_click_open_hand_full_chain(self):
        self.window.open_hand()
        self._verify_full_chain(list(_GESTURE_PRESETS_REAL["open"]), "open_hand: ")

    def test_click_close_hand_full_chain(self):
        self.window.close_hand()
        self._verify_full_chain(list(_GESTURE_PRESETS_REAL["fist"]), "close_hand: ")

    def test_click_reset_full_chain(self):
        self.window.close_hand()
        self.window.reset_hand()
        expected = [d["default"] for d in DOF_DEFINITIONS]
        self._verify_full_chain(expected, "reset_hand: ")

    def test_click_preset_ok_full_chain(self):
        expected = list(_GESTURE_PRESETS_REAL["ok"])
        self.window.preset_ok()
        self._verify_full_chain(expected, "preset_ok: ")

    def test_click_preset_pinch_full_chain(self):
        expected = list(_GESTURE_PRESETS_REAL["pinch"])
        self.window.preset_pinch()
        self._verify_full_chain(expected, "preset_pinch: ")

    def test_click_preset_point_full_chain(self):
        expected = list(_GESTURE_PRESETS_REAL["point"])
        self.window.preset_point()
        self._verify_full_chain(expected, "preset_point: ")

    def test_button_click_via_click_method(self):
        """通过 QPushButton.click() 模拟点击 "握拳" 按钮。"""
        from PySide2.QtWidgets import QPushButton
        buttons = self.window.findChildren(QPushButton)
        fist_btn = next(b for b in buttons if b.text() == "握拳")
        fist_btn.click()
        self._verify_full_chain(list(_GESTURE_PRESETS_REAL["fist"]), "btn.click(握拳): ")

    def test_button_click_via_signal(self):
        """通过 QPushButton.clicked.emit() 触发 "OK" 按钮。"""
        from PySide2.QtWidgets import QPushButton
        buttons = self.window.findChildren(QPushButton)
        ok_btn = next(b for b in buttons if b.text() == "OK")
        ok_btn.clicked.emit()
        expected = list(_GESTURE_PRESETS_REAL["ok"])
        self._verify_full_chain(expected, "btn.clicked(OK): ")

    def test_sequential_button_clicks(self):
        """连续点击多个按钮，最终状态为最后一次点击的值。"""
        self.window.open_hand()
        self.window.close_hand()
        self.window.preset_ok()
        expected = list(_GESTURE_PRESETS_REAL["ok"])
        self._verify_full_chain(expected, "sequential: ")

    def test_no_ros_node_no_crash(self):
        """没有 ros_node 时，按钮操作不崩溃。"""
        self.window.ros_node = None
        self.window.open_hand()
        self.assertEqual(self.window.sliders[0].get_target_int(), 255)


# ══════════════════════════════════════════════════════════════════════
# 8. _syncing 防循环机制
# ══════════════════════════════════════════════════════════════════════


class TestControlPanelSyncing(unittest.TestCase):
    """_syncing 防循环机制测试（核心业务逻辑）。"""

    def setUp(self):
        self.window = _create_window()
        self.mock_ros = MagicMock()
        self.window.set_ros_node(self.mock_ros)

    def test_syncing_blocks_on_slider(self):
        """_syncing=True 时 _on_slider 不调用 publish。"""
        self.window._syncing = True
        self.window._on_slider()
        self.mock_ros.publish_dof.assert_not_called()

    def test_syncing_blocks_apply_target(self):
        """_syncing=True 时 _apply_target_state 直接返回，不更新滑块。"""
        self.window.sliders[0].set_target(0)
        self.window._syncing = True
        self.window._apply_target_state([128] * 10)
        self.assertEqual(self.window.sliders[0].get_target_int(), 0)

    def test_syncing_allows_apply_current(self):
        """_apply_current_state 不受 _syncing 影响。"""
        self.window._syncing = True
        self.window._apply_current_state([128] * 10)
        self.assertAlmostEqual(self.window.sliders[0]._current, 128.0)

    def test_syncing_blocks_speed_limit(self):
        """_syncing=True 时 _apply_speed_limit 直接返回。"""
        self.window._speed_slider.set_target(0)
        self.window._syncing = True
        self.window._apply_speed_limit(50)
        self.assertEqual(self.window._speed_slider.get_target_int(), 0)

    def test_set_all_restores_syncing(self):
        """_set_all() 结束后 _syncing 恢复为 False。"""
        self.window._syncing = False
        self.window._set_all([128] * 10)
        self.assertFalse(self.window._syncing)

    def test_on_slider_without_syncing_publishes(self):
        """_syncing=False 时 _on_slider 正常发布。"""
        self.window._syncing = False
        self.window._on_slider()
        self.mock_ros.publish_dof.assert_called()


# ══════════════════════════════════════════════════════════════════════
# 8. 手势/序列功能集成测试
# ══════════════════════════════════════════════════════════════════════


class TestGestureSequenceIntegration(unittest.TestCase):
    """手势管理器、手势面板、序列播放与控制面板集成测试。"""

    def setUp(self):
        self.window = _create_window()
        self.mock_ros = MagicMock()
        self.window.set_ros_node(self.mock_ros)

    def test_gesture_manager_initialized(self):
        """窗口初始化后 _gesture_manager 已加载。"""
        self.assertIsNotNone(self.window._gesture_manager)
        # 加载后至少能看到内置手势
        names = self.window._gesture_manager.get_all_gesture_names()
        self.assertIn("open", names)
        self.assertIn("fist", names)

    def test_gesture_panel_exists(self):
        """_gesture_panel 已创建并添加到布局。"""
        self.assertIsNotNone(self.window._gesture_panel)
        # 确认是 GestureManagePanel 类型
        from l10_hand_control_panel.gesture_dialogs import GestureManagePanel
        self.assertIsInstance(self.window._gesture_panel, GestureManagePanel)

    def test_gesture_selection_publishes_dof(self):
        """手势选择信号 → _on_gesture_selected → _set_all → ROS publish。"""
        self.window._syncing = False
        # 模拟手势选择信号（选择 "open" 手势）
        open_dofs = tuple([255] * 10)
        self.window._gesture_panel.gesture_selected.emit("open", open_dofs)
        # 验证 ROS 发布被调用
        self.mock_ros.publish_dof.assert_called()
        call_args = self.mock_ros.publish_dof.call_args[0][0]
        self.assertEqual(len(call_args), 10)
        self.assertTrue(all(v == 255 for v in call_args))

    def test_gesture_selection_updates_sliders(self):
        """手势选择后滑块目标值更新。"""
        self.window._syncing = False
        fist_dofs = tuple([0] * 10)
        self.window._gesture_panel.gesture_selected.emit("fist", fist_dofs)
        for slider in self.window.sliders:
            self.assertEqual(slider.get_target_int(), 0)

    def test_sequence_playback_starts_timer(self):
        """_start_sequence_playback 启动 QTimer 并应用第一步 DOF。"""
        # 先创建序列（注入到管理器）
        self.window._gesture_manager.create_sequence(
            "test_seq",
            [
                {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
                {"gesture_name": "fist", "duration": 1.0, "delay_after": 0.0},
            ],
            loop=False,
        )
        # 初始不播放
        self.assertFalse(getattr(self.window, "_sequence_playing", False))
        # 启动播放
        result = self.window._start_sequence_playback("test_seq")
        self.assertTrue(result)
        self.assertTrue(self.window._sequence_playing)
        # 验证计时器已启动
        self.assertIsNotNone(self.window._sequence_timer)
        self.assertTrue(self.window._sequence_timer.isActive())
        # 验证第一步已应用（所有 DOF = 255）
        for slider in self.window.sliders:
            self.assertEqual(slider.get_target_int(), 255)

    def test_sequence_playback_invalid_sequence_returns_false(self):
        """不存在的序列名返回 False，不启动播放。"""
        result = self.window._start_sequence_playback("nonexistent_seq")
        self.assertFalse(result)
        self.assertFalse(getattr(self.window, "_sequence_playing", False))

    def test_sequence_stop_cleans_up(self):
        """_stop_sequence_playback 停止计时器并清理状态。"""
        # 创建并启动序列
        self.window._gesture_manager.create_sequence(
            "test_seq",
            [{"gesture_name": "open", "duration": 1.0, "delay_after": 0.0}],
            loop=False,
        )
        self.window._start_sequence_playback("test_seq")
        self.assertTrue(self.window._sequence_playing)
        # 停止
        self.window._stop_sequence_playback()
        self.assertFalse(self.window._sequence_playing)
        self.assertIsNone(self.window._sequence_timer)
        self.assertIsNone(self.window._sequence_data)

    def test_sequence_playback_applies_step_change(self):
        """序列 tick 推进到下一步时 DOF 值确实切换为新手势的值。"""
        self.window._gesture_manager.create_sequence(
            "test_seq",
            [
                {"gesture_name": "open", "duration": 0.5, "delay_after": 0.0},
                {"gesture_name": "fist", "duration": 0.5, "delay_after": 0.0},
            ],
            loop=False,
        )
        self.window._start_sequence_playback("test_seq")
        # 第一步是 open — 验证值匹配 mock 预设
        open_vals = _GESTURE_PRESETS_REAL["open"]
        for slider in self.window.sliders:
            self.assertEqual(slider.get_target_int(), 255)
        # 模拟时间推进到第一步结束，进入第二步 (fist)
        data = self.window._sequence_data
        data["phase_start"] = time.time() - 1.0
        self.window._sequence_tick()
        # 第二步应切换为 fist — 验证值与 mock 预设一致，不写死具体数字
        fist_vals = _GESTURE_PRESETS_REAL["fist"]
        for i, slider in enumerate(self.window.sliders):
            self.assertEqual(
                slider.get_target_int(), fist_vals[i],
                f"Step 2 DOF[{i}] should match mock fist preset"
            )

    def test_gesture_create_requested_signal(self):
        """gesture_create_requested 信号可被发射（不触发对话框）。"""
        received = []
        # 暂时阻止 _open_gesture_editor 打开对话框
        with patch.object(self.window, '_open_gesture_editor'):
            self.window._gesture_panel.gesture_create_requested.connect(
                lambda: received.append(True)
            )
            self.window._gesture_panel.gesture_create_requested.emit()
        self.assertEqual(len(received), 1)

    def test_sequence_create_requested_signal(self):
        """sequence_create_requested 信号可被发射（不触发对话框）。"""
        received = []
        # 暂时阻止 _open_sequence_editor 打开对话框
        with patch.object(self.window, '_open_sequence_editor'):
            self.window._gesture_panel.sequence_create_requested.connect(
                lambda: received.append(True)
            )
            self.window._gesture_panel.sequence_create_requested.emit()
        self.assertEqual(len(received), 1)

    def test_gesture_panel_preset_tab_buttons(self):
        """预设标签页有 7 个预设手势按钮。"""
        from PySide2.QtWidgets import QPushButton, QTabWidget
        # 切换到预设标签页
        tab_widget = self.window._gesture_panel.findChild(QTabWidget)
        if tab_widget is not None:
            tab_widget.setCurrentIndex(0)
        buttons = self.window._gesture_panel.findChildren(QPushButton)
        preset_names = ["张开", "握拳", "OK", "捏取", "指向", "比耶", "竖大拇指"]
        found_texts = [b.text() for b in buttons]
        for name in preset_names:
            self.assertIn(name, found_texts,
                          f"预设按钮 '{name}' 未在 GestureManagePanel 中找到")


if __name__ == '__main__':
    unittest.main()
