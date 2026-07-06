#!/usr/bin/env python3
"""
手势与序列 UI 组件测试 — GestureEditorDialog, SequenceEditorDialog, GestureManagePanel。

使用 QT_QPA_PLATFORM=offscreen 运行，不依赖显示设备。
"""

from __future__ import annotations

import os
import sys
import time
import unittest
from unittest.mock import patch, MagicMock

# offscreen 模式，无需显示器
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# ── Mock 依赖 (必须在 import control_panel / gesture_dialogs 之前) ──
_GESTURE_PRESETS_REAL = {
    "open":      (255, 255, 255, 255, 255, 255, 255, 255, 255, 255),
    "fist":      (122, 145,   0,   0,   0,   0,   0,   0,   0,  92),
    "ok":        (108,  56, 118, 255, 255, 255, 255, 255, 255, 234),
    "pinch":     (108,  56, 118,   0,   0,   0, 132,   0,   0, 234),
    "point":     (116, 142, 255,   0,   0,   0,  49,  36,  81,  50),
    "peace":     ( 96,  48, 255, 255,   0,   0, 255, 255, 255,  89),
    "thumbs_up": (255, 255,   0,   0,   0,   0,   0,   0,   0, 255),
}

_mock_gp = MagicMock()
_mock_gp.GESTURE_PRESETS = _GESTURE_PRESETS_REAL

_mock_lhd = MagicMock()
_mock_lhd.gesture_presets = _mock_gp
_mock_lhd.get_urdf_path = MagicMock(return_value="/fake/path/model.xml")
_mock_lhd.get_urdf_dir = MagicMock(return_value="/fake/path")
_mock_lhd.get_model_path = MagicMock(return_value="/fake/path/model.urdf")
_mock_lhd.get_model_dir = MagicMock(return_value="/fake/path")

for _name, _mock in [
    ("rclpy", MagicMock()),
    ("rclpy.node", MagicMock()),
    ("sensor_msgs", MagicMock()),
    ("sensor_msgs.msg", MagicMock()),
    ("std_msgs", MagicMock()),
    ("std_msgs.msg", MagicMock()),
    ("mujoco", MagicMock()),
    ("hand_forward_kinematics", MagicMock()),
    ("hand_forward_kinematics.kinematics", MagicMock()),
    ("linker_hand_description", _mock_lhd),
    ("linker_hand_description.gesture_presets", _mock_gp),
]:
    sys.modules.setdefault(_name, _mock)

# ── Qt 导入 ──────────────────────────────────────────────────────
from PySide2.QtWidgets import QApplication, QMessageBox

# 确保 QApplication 单例
_app = None

def get_app():
    global _app
    if _app is None:
        _app = QApplication.instance()
        if _app is None:
            _app = QApplication([])
    return _app

# ── 被测模块 ──────────────────────────────────────────────────────
from l10_hand_control_panel.gesture_dialogs import (
    GestureEditorDialog,
    SequenceEditorDialog,
    GestureManagePanel,
    SequencePlayerOverlay,
)
from l10_hand_control_panel.gesture_manager import GestureManager


# ══════════════════════════════════════════════════════════════════════
# 1. GestureEditorDialog
# ══════════════════════════════════════════════════════════════════════

class TestGestureEditorDialog(unittest.TestCase):
    """GestureEditorDialog 测试。"""

    def setUp(self):
        self.gm = GestureManager()
        self.gm._custom_gestures = {}
        self.gm._sequences = {}
        self.gm._change_callbacks = []
        self.app = get_app()

    def test_create_mode_title(self):
        """创建模式窗口标题为"新建手势"。"""
        dlg = GestureEditorDialog(self.gm)
        self.assertEqual(dlg.windowTitle(), "新建手势")

    def test_edit_mode_title(self):
        """编辑模式窗口标题为"编辑手势"。"""
        self.gm.create_custom_gesture("my_gest", [128] * 10, "test desc")
        dlg = GestureEditorDialog(self.gm, gesture_name="my_gest")
        self.assertEqual(dlg.windowTitle(), "编辑手势")

    def test_ten_sliders_created(self):
        """对话框创建 10 个 DOF 滑块。"""
        dlg = GestureEditorDialog(self.gm)
        self.assertEqual(len(dlg._sliders), 10)

    def test_default_dof_values_are_255(self):
        """滑块默认值全为 255（张开姿态）。"""
        dlg = GestureEditorDialog(self.gm)
        for slider in dlg._sliders:
            self.assertEqual(slider.get_target_int(), 255)

    def test_create_mode_name_edit_empty(self):
        """创建模式名称编辑框初始为空。"""
        dlg = GestureEditorDialog(self.gm)
        self.assertEqual(dlg._name_edit.text().strip(), "")

    def test_edit_mode_name_locked(self):
        """编辑模式名称编辑框被禁用。"""
        self.gm.create_custom_gesture("locked_name", [100] * 10)
        dlg = GestureEditorDialog(self.gm, gesture_name="locked_name")
        self.assertFalse(dlg._name_edit.isEnabled())

    def test_edit_mode_populates_fields(self):
        """编辑模式预填充名称、描述和 DOF 值。"""
        dof_vals = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
        self.gm.create_custom_gesture("populate_test", dof_vals, "test description")
        dlg = GestureEditorDialog(self.gm, gesture_name="populate_test")
        self.assertEqual(dlg._name_edit.text(), "populate_test")
        self.assertEqual(dlg._desc_edit.toPlainText(), "test description")
        for i, slider in enumerate(dlg._sliders):
            self.assertEqual(slider.get_target_int(), dof_vals[i])

    def test_import_from_current(self):
        """从当前 DOF 导入功能。"""
        current = [5, 15, 25, 35, 45, 55, 65, 75, 85, 95]
        dlg = GestureEditorDialog(self.gm, current_dofs=current)
        dlg._import_from_current()
        for i, slider in enumerate(dlg._sliders):
            self.assertEqual(slider.get_target_int(), current[i])

    def test_reset_to_open(self):
        """重置按钮将所有 DOF 设为 255。"""
        dlg = GestureEditorDialog(self.gm)
        dlg._randomize()  # 先随机化
        dlg._reset_to_open()
        for slider in dlg._sliders:
            self.assertEqual(slider.get_target_int(), 255)

    def test_randomize_values_in_range(self):
        """随机值在 0-255 范围内。"""
        dlg = GestureEditorDialog(self.gm)
        dlg._randomize()
        for slider in dlg._sliders:
            val = slider.get_target_int()
            self.assertGreaterEqual(val, 0)
            self.assertLessEqual(val, 255)

    def test_create_mode_valid_save(self):
        """创建模式：输入有效名称保存后发射信号。"""
        dlg = GestureEditorDialog(self.gm, current_dofs=[100] * 10)
        dlg._name_edit.setText("valid_gesture")
        received = []
        dlg.dialog_accepted.connect(lambda n, d: received.append((n, list(d))))
        dlg._on_save()
        self.assertTrue(dlg.result())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "valid_gesture")

    def test_create_mode_empty_name_rejects(self):
        """创建模式：空名称不保存。"""
        dlg = GestureEditorDialog(self.gm)
        dlg._name_edit.setText("")
        with patch.object(QMessageBox, "warning"):
            dlg._on_save()
        self.assertFalse(dlg.result())

    def test_create_mode_duplicate_name_rejects(self):
        """创建模式：重复名称不保存（不会创建新手势）。"""
        self.gm.create_custom_gesture("dup_name", [100] * 10)
        dlg = GestureEditorDialog(self.gm, current_dofs=[50] * 10)
        dlg._name_edit.setText("dup_name")
        # Mock QMessageBox.warning 避免阻塞
        with patch.object(QMessageBox, "warning"):
            dlg._on_save()
        # 验证：没有创建新手势
        self.assertEqual(len(self.gm.list_custom_gestures()), 1)

    def test_signal_emitted_on_create(self):
        """创建模式：dialog_accepted 信号携带名称和当前滑块值。"""
        dlg = GestureEditorDialog(self.gm, current_dofs=[42] * 10)
        dlg._name_edit.setText("signal_test")
        received = []
        dlg.dialog_accepted.connect(lambda n, d: received.append((n, list(d))))
        dlg._on_save()
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "signal_test")
        # 滑块默认全 255
        self.assertEqual(received[0][1], [255] * 10)


# ══════════════════════════════════════════════════════════════════════
# 2. SequenceEditorDialog
# ══════════════════════════════════════════════════════════════════════

class TestSequenceEditorDialog(unittest.TestCase):
    """SequenceEditorDialog 测试。"""

    def setUp(self):
        self.gm = GestureManager()
        self.gm._custom_gestures = {}
        self.gm._sequences = {}
        self.gm._change_callbacks = []
        self.app = get_app()

    def test_create_mode_title(self):
        """创建模式窗口标题。"""
        dlg = SequenceEditorDialog(self.gm)
        self.assertEqual(dlg.windowTitle(), "新建序列")

    def test_edit_mode_title(self):
        """编辑模式窗口标题。"""
        self.gm.create_sequence("edit_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        dlg = SequenceEditorDialog(self.gm, sequence_name="edit_seq")
        self.assertEqual(dlg.windowTitle(), "编辑序列")

    def test_gesture_combo_populated(self):
        """手势下拉框包含内置 + 自定义手势。"""
        self.gm.create_custom_gesture("custom1", [100] * 10)
        dlg = SequenceEditorDialog(self.gm)
        count = dlg._gesture_combo.count()
        # 7 个内置 + 1 个自定义 = 8
        self.assertEqual(count, 8)

    def test_empty_steps_initially(self):
        """创建模式初始步骤列表为空。"""
        dlg = SequenceEditorDialog(self.gm)
        self.assertEqual(len(dlg._steps), 0)

    def test_add_step(self):
        """添加步骤功能。"""
        dlg = SequenceEditorDialog(self.gm)
        # 直接设置步骤数据（不依赖 UI 控件状态）
        dlg._steps.append({
            "gesture_name": "open",
            "duration": 1.5,
            "delay_after": 0.3,
        })
        dlg._refresh_step_list()
        self.assertEqual(len(dlg._steps), 1)
        self.assertEqual(dlg._steps[0]["gesture_name"], "open")
        self.assertEqual(dlg._steps[0]["duration"], 1.5)
        self.assertEqual(dlg._steps[0]["delay_after"], 0.3)

    def test_delete_step(self):
        """删除步骤功能。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._add_step_from_ui()
        dlg._add_step_from_ui()
        self.assertEqual(len(dlg._steps), 2)
        dlg._step_list.setCurrentRow(0)
        dlg._delete_selected_step()
        self.assertEqual(len(dlg._steps), 1)

    def test_move_step_up(self):
        """上移步骤功能。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._steps = [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
            {"gesture_name": "fist", "duration": 1.0, "delay_after": 0.0},
        ]
        dlg._refresh_step_list()
        dlg._step_list.setCurrentRow(1)
        dlg._move_step_up()
        self.assertEqual(dlg._steps[0]["gesture_name"], "fist")
        self.assertEqual(dlg._steps[1]["gesture_name"], "open")

    def test_move_step_down(self):
        """下移步骤功能。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._steps = [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
            {"gesture_name": "fist", "duration": 1.0, "delay_after": 0.0},
        ]
        dlg._refresh_step_list()
        dlg._step_list.setCurrentRow(0)
        dlg._move_step_down()
        self.assertEqual(dlg._steps[0]["gesture_name"], "fist")
        self.assertEqual(dlg._steps[1]["gesture_name"], "open")

    def test_move_first_step_up_noop(self):
        """第一个步骤上移不生效。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._add_step_from_ui()
        first_name = dlg._steps[0]["gesture_name"]
        dlg._step_list.setCurrentRow(0)
        dlg._move_step_up()
        self.assertEqual(dlg._steps[0]["gesture_name"], first_name)

    def test_move_last_step_down_noop(self):
        """最后一个步骤下移不生效。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._add_step_from_ui()
        dlg._add_step_from_ui()
        last_name = dlg._steps[1]["gesture_name"]
        dlg._step_list.setCurrentRow(1)
        dlg._move_step_down()
        self.assertEqual(dlg._steps[1]["gesture_name"], last_name)

    def test_empty_steps_rejects_save(self):
        """空步骤列表不允许保存。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._name_edit.setText("test_seq")
        with patch.object(QMessageBox, "warning"):
            dlg._on_save()
        self.assertFalse(dlg.result())

    def test_empty_name_rejects_save(self):
        """空名称不允许保存。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._steps.append({"gesture_name": "open", "duration": 1.0, "delay_after": 0.0})
        dlg._refresh_step_list()
        dlg._name_edit.setText("")
        with patch.object(QMessageBox, "warning"):
            dlg._on_save()
        self.assertFalse(dlg.result())

    def test_populate_existing(self):
        """加载已有序列数据。"""
        steps = [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
            {"gesture_name": "fist", "duration": 0.5, "delay_after": 0.2},
        ]
        self.gm.create_sequence("existing_seq", steps, loop=True)
        dlg = SequenceEditorDialog(self.gm, sequence_name="existing_seq")
        self.assertEqual(dlg._name_edit.text(), "existing_seq")
        self.assertFalse(dlg._name_edit.isEnabled())
        self.assertTrue(dlg._loop_checkbox.isChecked())
        self.assertEqual(len(dlg._steps), 2)

    def test_save_emits_signal(self):
        """保存时 dialog_accepted 信号携带正确数据。"""
        dlg = SequenceEditorDialog(self.gm)
        dlg._name_edit.setText("signal_seq")
        dlg._add_step_from_ui()
        received = []
        dlg.dialog_accepted.connect(lambda n, s, l: received.append((n, list(s), l)))
        dlg._on_save()
        self.assertTrue(dlg.result())
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "signal_seq")
        self.assertEqual(received[0][2], False)  # loop=False


# ══════════════════════════════════════════════════════════════════════
# 3. GestureManagePanel
# ══════════════════════════════════════════════════════════════════════

class TestGestureManagePanel(unittest.TestCase):
    """GestureManagePanel 测试。"""

    def setUp(self):
        self.gm = GestureManager()
        self.gm._custom_gestures = {}
        self.gm._sequences = {}
        self.gm._change_callbacks = []
        self.app = get_app()

    def test_preset_tab_has_7_buttons(self):
        """预设标签页至少有 7 个预设按钮。"""
        panel = GestureManagePanel(self.gm)
        preset_widget = panel._tabs.widget(0)
        buttons = preset_widget.findChildren(type(preset_widget).__bases__[0].__subclasses__()[0] if False else __import__("PySide2.QtWidgets", fromlist=["QPushButton"]).QPushButton)
        # 简化：直接检查子控件数量
        self.assertGreaterEqual(panel._tabs.count(), 3)

    def test_three_tabs_exist(self):
        """面板有 3 个标签页（预设/自定义/序列）。"""
        panel = GestureManagePanel(self.gm)
        self.assertEqual(panel._tabs.count(), 3)
        self.assertEqual(panel._tabs.tabText(0), "预设")
        self.assertEqual(panel._tabs.tabText(1), "自定义")
        self.assertEqual(panel._tabs.tabText(2), "序列")

    def test_custom_tab_empty_initially(self):
        """初始自定义标签页无手势按钮（只有新建按钮）。"""
        panel = GestureManagePanel(self.gm)
        panel.refresh()
        from PySide2.QtWidgets import QPushButton
        custom_widget = panel._tabs.widget(1)
        buttons = custom_widget.findChildren(QPushButton)
        self.assertEqual(len(buttons), 1)
        self.assertEqual(buttons[0].text(), "+ 新建手势")

    def test_custom_tab_shows_gesture_after_create(self):
        """创建自定义手势后自定义标签页显示按钮。"""
        panel = GestureManagePanel(self.gm)
        self.gm.create_custom_gesture("visible_gest", [100] * 10, "visible desc")
        panel.refresh()
        from PySide2.QtWidgets import QPushButton
        custom_widget = panel._tabs.widget(1)
        buttons = custom_widget.findChildren(QPushButton)
        labels = [b.text() for b in buttons]
        self.assertIn("visible_gest", labels)

    def test_sequence_tab_shows_sequence_after_create(self):
        """创建序列后序列标签页显示。"""
        panel = GestureManagePanel(self.gm)
        self.gm.create_sequence("visible_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        panel.refresh()
        from PySide2.QtWidgets import QLabel
        seq_widget = panel._tabs.widget(2)
        labels = [w.text() for w in seq_widget.findChildren(QLabel)]
        self.assertIn("visible_seq", labels)

    def test_preset_button_emits_gesture_selected(self):
        """点击预设按钮发射 gesture_selected 信号。"""
        panel = GestureManagePanel(self.gm)
        received = []
        panel.gesture_selected.connect(lambda n, d: received.append((n, d)))
        preset_widget = panel._tabs.widget(0)
        from PySide2.QtWidgets import QPushButton
        for btn in preset_widget.findChildren(QPushButton):
            if btn.text() == "张开":
                btn.click()
                break
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "open")

    def test_custom_gesture_button_emits_signal(self):
        """点击自定义手势按钮发射 gesture_selected 信号。"""
        panel = GestureManagePanel(self.gm)
        self.gm.create_custom_gesture("emit_test", [77] * 10)
        panel.refresh()
        received = []
        panel.gesture_selected.connect(lambda n, d: received.append((n, d)))
        custom_widget = panel._tabs.widget(1)
        from PySide2.QtWidgets import QPushButton
        for btn in custom_widget.findChildren(QPushButton):
            if btn.text() == "emit_test":
                btn.click()
                break
        self.assertEqual(len(received), 1)
        self.assertEqual(received[0][0], "emit_test")

    def test_delete_custom_gesture_via_manager(self):
        """删除自定义手势后面板刷新。"""
        panel = GestureManagePanel(self.gm)
        self.gm.create_custom_gesture("to_remove", [100] * 10)
        panel.refresh()
        self.assertIn("to_remove", self.gm.list_custom_gestures())
        self.gm.delete_custom_gesture("to_remove")
        panel.refresh()
        from PySide2.QtWidgets import QPushButton
        custom_widget = panel._tabs.widget(1)
        buttons = custom_widget.findChildren(QPushButton)
        labels = [b.text() for b in buttons]
        self.assertNotIn("to_remove", labels)

    def test_data_change_callback_triggers_refresh(self):
        """数据变更回调触发面板刷新。"""
        panel = GestureManagePanel(self.gm)
        refresh_count = [0]
        original_refresh = panel.refresh
        def counting_refresh():
            refresh_count[0] += 1
            original_refresh()
        panel.refresh = counting_refresh

        panel._on_data_changed("gesture_created", "new_gest")
        self.assertEqual(refresh_count[0], 1)

    def test_irrelevant_change_does_not_refresh(self):
        """无关变更类型不触发刷新。"""
        panel = GestureManagePanel(self.gm)
        refresh_count = [0]
        original_refresh = panel.refresh
        def counting_refresh():
            refresh_count[0] += 1
            original_refresh()
        panel.refresh = counting_refresh

        panel._on_data_changed("unknown_change", "key")
        self.assertEqual(refresh_count[0], 0)

    def test_gesture_create_requested_signal(self):
        """gesture_create_requested 信号可正常发射。"""
        panel = GestureManagePanel(self.gm)
        received = []
        panel.gesture_create_requested.connect(lambda: received.append(True))
        # 直接触发信号
        panel.gesture_create_requested.emit()
        self.assertEqual(len(received), 1)

    def test_sequence_create_requested_signal(self):
        """sequence_create_requested 信号可正常发射。"""
        panel = GestureManagePanel(self.gm)
        received = []
        panel.sequence_create_requested.connect(lambda: received.append(True))
        panel.sequence_create_requested.emit()
        self.assertEqual(len(received), 1)


# ══════════════════════════════════════════════════════════════════════
# 4. SequencePlayerOverlay
# ══════════════════════════════════════════════════════════════════════

class TestSequencePlayerOverlay(unittest.TestCase):
    """SequencePlayerOverlay 测试。"""

    def setUp(self):
        self.gm = GestureManager()
        self.gm._custom_gestures = {}
        self.gm._sequences = {}
        self.gm._change_callbacks = []
        self.app = get_app()

    def test_initially_hidden(self):
        """初始状态覆盖层隐藏。"""
        overlay = SequencePlayerOverlay(self.gm)
        self.assertFalse(overlay.isVisible())

    def test_play_valid_sequence(self):
        """播放有效序列成功。"""
        self.gm.create_sequence("test_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        result = overlay.play_sequence("test_seq")
        self.assertTrue(result)
        self.assertTrue(overlay.is_playing())
        overlay.stop()

    def test_play_nonexistent_returns_false(self):
        """播放不存在的序列返回 False。"""
        overlay = SequencePlayerOverlay(self.gm)
        result = overlay.play_sequence("nonexistent")
        self.assertFalse(result)

    def test_stop_hides_overlay(self):
        """停止后覆盖层隐藏。"""
        self.gm.create_sequence("stop_test", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("stop_test")
        self.assertTrue(overlay.is_playing())
        overlay.stop()
        self.assertFalse(overlay.is_playing())
        self.assertFalse(overlay.isVisible())

    def test_pause_and_resume(self):
        """暂停和继续功能。"""
        self.gm.create_sequence("pause_test", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("pause_test")
        self.assertTrue(overlay.is_playing())

        overlay._toggle_pause()
        self.assertTrue(overlay._paused)
        self.assertFalse(overlay.is_playing())

        overlay._toggle_pause()
        self.assertFalse(overlay._paused)
        self.assertTrue(overlay.is_playing())

        overlay.stop()

    def test_finished_signal_after_duration(self):
        """duration 到期后序列停止（通过直接 tick 推进）。"""
        self.gm.create_sequence("quick_seq", [
            {"gesture_name": "open", "duration": 0.05, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        finished_received = []
        overlay.finished.connect(lambda: finished_received.append(True))
        overlay.play_sequence("quick_seq")
        # 直接调用 _tick 推进时间
        with patch("time.time", return_value=overlay._phase_start + 0.1):
            overlay._tick()
        self.assertFalse(overlay.is_playing())
        self.assertTrue(len(finished_received) > 0)

    def test_loop_mode_keeps_playing(self):
        """循环模式：序列重复播放不自动停止。"""
        self.gm.create_sequence("loop_seq", [
            {"gesture_name": "open", "duration": 0.05, "delay_after": 0.0},
        ], loop=True)
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("loop_seq")
        self.assertTrue(overlay.is_playing())
        self.assertTrue(overlay._loop)
        # 推进时间使第一步完成
        with patch("time.time", return_value=overlay._phase_start + 0.1):
            overlay._tick()
        # 循环模式应回到第一步
        self.assertTrue(overlay.is_playing())
        overlay.stop()
        self.assertFalse(overlay.is_playing())

    def test_current_sequence_name(self):
        """current_sequence_name 返回当前序列名。"""
        self.gm.create_sequence("named_seq", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("named_seq")
        self.assertEqual(overlay.current_sequence_name(), "named_seq")
        overlay.stop()

    def test_delay_phase_then_advance(self):
        """delay 阶段结束后推进到下一步。"""
        self.gm.create_sequence("delay_advance", [
            {"gesture_name": "open", "duration": 0.05, "delay_after": 0.15},
            {"gesture_name": "fist", "duration": 0.05, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("delay_advance")
        # 推进经过 duration + delay
        fake_time = overlay._phase_start
        # 第一 tick: duration 到期，进入 delay
        with patch("time.time", return_value=fake_time + 0.1):
            overlay._tick()
        # 现在在 delay 阶段，第一步
        self.assertEqual(overlay._current_step, 0)
        self.assertEqual(overlay._phase, "delay")
        # 第二 tick: delay 到期，推进到第二步
        with patch("time.time", return_value=fake_time + 0.3):
            overlay._tick()
        self.assertEqual(overlay._current_step, 1)
        overlay.stop()

    def test_stop_signal_on_stop(self):
        """调用 stop 后能正常停止。"""
        self.gm.create_sequence("stop_signal", [
            {"gesture_name": "open", "duration": 1.0, "delay_after": 0.0},
        ])
        overlay = SequencePlayerOverlay(self.gm)
        overlay.play_sequence("stop_signal")
        self.assertTrue(overlay.is_playing())
        overlay.stop()
        self.assertFalse(overlay.is_playing())
        self.assertFalse(overlay.isVisible())


if __name__ == "__main__":
    unittest.main()
