#!/usr/bin/env python3
"""
手势与序列 UI 组件 — 对话框和面板。

包含:
- GestureEditorDialog: 创建/编辑自定义手势
- SequenceEditorDialog: 创建/编辑手势序列
- GestureManagePanel: 嵌入主窗口的手势管理面板（三标签页）
- SequencePlayerOverlay: 序列播放进度覆盖层
"""

from __future__ import annotations

import time
from typing import Any

from PySide2.QtCore import Qt, Signal, QTimer, QSize
from PySide2.QtGui import QColor, QFont
from PySide2.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QLineEdit, QTextEdit, QComboBox,
    QDoubleSpinBox, QCheckBox, QListWidget, QListWidgetItem,
    QFrame, QScrollArea, QSizePolicy, QMessageBox, QProgressBar,
    QAbstractItemView,
)

from l10_hand_control_panel.gesture_manager import GestureManager


# ── 本地常量（避免从 control_panel.py 循环导入） ──────────────────

# 10 个自由度定义 (0-255 范围)
_DOF_DEFINITIONS = [
    {"idx": 0, "label": "DOF0 - 拇指弯曲", "default": 255},
    {"idx": 1, "label": "DOF1 - 拇指侧摆", "default": 255},
    {"idx": 2, "label": "DOF2 - 食指弯曲", "default": 255},
    {"idx": 3, "label": "DOF3 - 中指弯曲", "default": 255},
    {"idx": 4, "label": "DOF4 - 无名指弯曲", "default": 255},
    {"idx": 5, "label": "DOF5 - 小指弯曲", "default": 255},
    {"idx": 6, "label": "DOF6 - 食指侧摆", "default": 255},
    {"idx": 7, "label": "DOF7 - 无名指侧摆", "default": 255},
    {"idx": 8, "label": "DOF8 - 小指侧摆", "default": 255},
    {"idx": 9, "label": "DOF9 - 拇指侧旋", "default": 255},
]

# 颜色常量
_COLOR_TEXT_DIM = "#999999"
_COLOR_SURFACE = "#3c3c3c"
_COLOR_BG = "#2d2d2d"
_COLOR_TEXT = "#cccccc"
_COLOR_TROUGH = "#555555"
_COLOR_GRAY_FILL = "#888888"
_COLOR_GRAY_OUTLINE = "#666666"


# ──────────────────────────────────────────────────────────────────
# 辅助：深拷贝当前 DOF 值列表
# ──────────────────────────────────────────────────────────────────

def _default_dof_values() -> list[int]:
    """返回默认 DOF 值列表（全 255 = 张开）。"""
    return [255] * 10


def _current_dofs_from_window(window) -> list[int]:
    """从 ControlPanelWindow 获取当前滑块目标值。"""
    try:
        return [s.get_target_int() for s in window.sliders]
    except Exception:
        return _default_dof_values()


# ──────────────────────────────────────────────────────────────────
# 1. GestureEditorDialog — 创建/编辑自定义手势
# ──────────────────────────────────────────────────────────────────

class GestureEditorDialog(QDialog):
    """创建/编辑自定义手势对话框。

    提供 10 个 DOF 滑块用于编辑手势值，支持从当前滑块导入、重置为张开、随机生成。
    """

    dialog_accepted = Signal(str, list)  # (name, dof_values)

    def __init__(
        self,
        gesture_manager: GestureManager,
        gesture_name: str | None = None,
        current_dofs: list[int] | None = None,
        parent: QWidget | None = None,
    ):
        """初始化对话框。

        Args:
            gesture_manager: 手势数据管理器实例。
            gesture_name: 要编辑的手势名称，None 表示创建模式。
            current_dofs: 当前窗口的 DOF 值（用于"从当前滑块导入"按钮）。
            parent: 父控件。
        """
        super().__init__(parent)
        self._gm = gesture_manager
        self._editing_name = gesture_name
        self._current_dofs = current_dofs or _default_dof_values()

        self.setWindowTitle("编辑手势" if gesture_name else "新建手势")
        self.setModal(True)
        self.setFixedSize(520, 520)

        self._sliders: list[DualSlider] = []
        self._value_labels: list[QLabel] = []
        self._name_edit: QLineEdit | None = None
        self._desc_edit: QTextEdit | None = None

        self._build_ui()

        if gesture_name:
            self._populate_existing(gesture_name)

    def _build_ui(self) -> None:
        """构建对话框 UI。"""
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 20, 20, 20)

        # 名称 + 描述
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入手势名称")
        self._name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px 8px;
            }}
        """)
        name_row.addWidget(self._name_edit, stretch=1)
        root.addLayout(name_row)

        desc_row = QHBoxLayout()
        desc_row.addWidget(QLabel("描述:"))
        self._desc_edit = QTextEdit()
        self._desc_edit.setPlaceholderText("可选描述")
        self._desc_edit.setMaximumHeight(50)
        self._desc_edit.setStyleSheet(f"""
            QTextEdit {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px;
            }}
        """)
        desc_row.addWidget(self._desc_edit, stretch=1)
        root.addLayout(desc_row)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        root.addWidget(line)

        # DOF 滑块区域 — 延迟导入避免循环依赖
        from l10_hand_control_panel.control_panel import DualSlider
        sliders_label = QLabel("DOF 滑块:")
        sliders_label.setStyleSheet(f"color: {_COLOR_TEXT_DIM}; font-size: 11px;")
        root.addWidget(sliders_label)

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, dof in enumerate(_DOF_DEFINITIONS):
            lbl = QLabel(dof["label"])
            lbl.setFixedWidth(140)
            grid.addWidget(lbl, i, 0)

            ds = DualSlider(val_range=(0, 255))
            ds.set_target(255)
            ds.setFixedWidth(260)
            grid.addWidget(ds, i, 1)
            self._sliders.append(ds)

            val_lbl = QLabel("255")
            val_lbl.setFixedWidth(36)
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setFont(QFont("Monospace", 10))
            val_lbl.setStyleSheet(f"color: {_COLOR_TEXT_DIM};")
            grid.addWidget(val_lbl, i, 2)
            self._value_labels.append(val_lbl)

            # 滑块值变化时更新标签
            ds.valueChanged.connect(
                self._make_label_updater(i, val_lbl)
            )

        root.addLayout(grid)

        # 辅助按钮行
        helper_row = QHBoxLayout()
        helper_row.setSpacing(8)

        import_btn = QPushButton("从当前滑块导入")
        import_btn.clicked.connect(self._import_from_current)
        helper_row.addWidget(import_btn)

        reset_btn = QPushButton("重置为张开")
        reset_btn.clicked.connect(self._reset_to_open)
        helper_row.addWidget(reset_btn)

        random_btn = QPushButton("随机")
        random_btn.clicked.connect(self._randomize)
        helper_row.addWidget(random_btn)

        helper_row.addStretch()
        root.addLayout(helper_row)

        root.addStretch()

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        root.addLayout(btn_row)

    def _make_label_updater(self, index: int, label: QLabel):
        """返回一个更新指定索引滑块标签的函数。"""
        def _updater():
            val = self._sliders[index].get_target_int()
            label.setText(str(val))
        return _updater

    def _populate_existing(self, name: str) -> None:
        """用已有手势数据预填充对话框。"""
        data = self._gm.get_custom_gesture(name)
        if not data:
            return

        self._name_edit.setText(name)
        self._name_edit.setEnabled(False)  # 编辑模式不允许改名
        self._desc_edit.setText(data.get("description", ""))

        dof_values = data.get("dof_values", [])
        for i, ds in enumerate(self._sliders):
            if i < len(dof_values):
                ds.set_target(dof_values[i])
                self._value_labels[i].setText(str(dof_values[i]))

    def _import_from_current(self) -> None:
        """从主窗口当前滑块值填充编辑器。"""
        for i, ds in enumerate(self._sliders):
            val = self._current_dofs[i] if i < len(self._current_dofs) else 255
            ds.set_target(val)
            self._value_labels[i].setText(str(val))

    def _reset_to_open(self) -> None:
        """将所有 DOF 重置为张开（全 255）。"""
        for i, ds in enumerate(self._sliders):
            ds.set_target(255)
            self._value_labels[i].setText("255")

    def _randomize(self) -> None:
        """随机设置所有 DOF 值。"""
        import random
        for i, ds in enumerate(self._sliders):
            val = random.randint(0, 255)
            ds.set_target(val)
            self._value_labels[i].setText(str(val))

    def _on_save(self) -> None:
        """保存按钮回调 — 验证并发射信号。"""
        name = self._name_edit.text().strip()
        description = self._desc_edit.toPlainText().strip()
        dof_values = [ds.get_target_int() for ds in self._sliders]

        # 创建模式验证名称
        if not self._editing_name:
            valid, err = self._gm.validate_gesture_name(name)
            if not valid:
                QMessageBox.warning(self, "名称无效", err)
                return
        else:
            if not name:
                QMessageBox.warning(self, "名称无效", "手势名称不能为空")
                return

        self.dialog_accepted.emit(name, dof_values)
        self.accept()


# ──────────────────────────────────────────────────────────────────
# 2. SequenceEditorDialog — 创建/编辑手势序列
# ──────────────────────────────────────────────────────────────────

class _StepListWidget(QListWidget):
    """自定义步骤列表控件。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setStyleSheet(f"""
            QListWidget {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px;
            }}
            QListWidget::item {{
                padding: 6px 8px; margin: 2px;
                border-radius: 4px;
            }}
            QListWidget::item:selected {{
                background: #555555;
            }}
            QListWidget::item:hover {{
                background: #4a4a4a;
            }}
        """)


class SequenceEditorDialog(QDialog):
    """创建/编辑手势序列对话框。

    提供步骤列表管理（增/删/排序），每步包含手势选择、持续时间、延迟设置。
    """

    dialog_accepted = Signal(str, list, bool)  # (name, steps, loop)

    def __init__(
        self,
        gesture_manager: GestureManager,
        sequence_name: str | None = None,
        parent: QWidget | None = None,
    ):
        """初始化对话框。

        Args:
            gesture_manager: 手势数据管理器实例。
            sequence_name: 要编辑的序列名称，None 表示创建模式。
            parent: 父控件。
        """
        super().__init__(parent)
        self._gm = gesture_manager
        self._editing_name = sequence_name

        self.setWindowTitle("编辑序列" if sequence_name else "新建序列")
        self.setModal(True)
        self.setFixedSize(540, 500)

        self._name_edit: QLineEdit | None = None
        self._loop_checkbox: QCheckBox | None = None
        self._step_list: _StepListWidget | None = None
        self._gesture_combo: QComboBox | None = None
        self._duration_spin: QDoubleSpinBox | None = None
        self._delay_spin: QDoubleSpinBox | None = None

        self._steps: list[dict[str, Any]] = []

        self._build_ui()

        if sequence_name:
            self._populate_existing(sequence_name)

    def _build_ui(self) -> None:
        """构建对话框 UI。"""
        root = QVBoxLayout(self)
        root.setSpacing(10)
        root.setContentsMargins(20, 20, 20, 20)

        # 名称 + 循环
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("序列名称:"))
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("输入序列名称")
        self._name_edit.setStyleSheet(f"""
            QLineEdit {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px 8px;
            }}
        """)
        top_row.addWidget(self._name_edit, stretch=1)

        self._loop_checkbox = QCheckBox("循环播放")
        self._loop_checkbox.setStyleSheet(f"color: {_COLOR_TEXT};")
        top_row.addWidget(self._loop_checkbox)

        root.addLayout(top_row)

        # 步骤列表
        list_label = QLabel("步骤列表:")
        list_label.setStyleSheet(f"color: {_COLOR_TEXT_DIM}; font-size: 11px;")
        root.addWidget(list_label)

        self._step_list = _StepListWidget()
        self._step_list.itemSelectionChanged.connect(
            self._on_step_selected
        )
        root.addWidget(self._step_list, stretch=1)

        # 步骤编辑区域
        edit_row = QHBoxLayout()
        edit_row.setSpacing(8)

        edit_row.addWidget(QLabel("手势:"))
        self._gesture_combo = QComboBox()
        self._gesture_combo.setStyleSheet(f"""
            QComboBox {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px;
            }}
            QComboBox QAbstractItemView {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
            }}
        """)
        edit_row.addWidget(self._gesture_combo, stretch=1)

        edit_row.addWidget(QLabel("持续:"))
        self._duration_spin = QDoubleSpinBox()
        self._duration_spin.setRange(0.1, 60.0)
        self._duration_spin.setSingleStep(0.1)
        self._duration_spin.setValue(1.0)
        self._duration_spin.setSuffix(" s")
        self._duration_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px;
            }}
        """)
        edit_row.addWidget(self._duration_spin)

        edit_row.addWidget(QLabel("延迟:"))
        self._delay_spin = QDoubleSpinBox()
        self._delay_spin.setRange(0.0, 30.0)
        self._delay_spin.setSingleStep(0.1)
        self._delay_spin.setValue(0.0)
        self._delay_spin.setSuffix(" s")
        self._delay_spin.setStyleSheet(f"""
            QDoubleSpinBox {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px; padding: 4px;
            }}
        """)
        edit_row.addWidget(self._delay_spin)

        root.addLayout(edit_row)

        # 步骤操作按钮
        step_btn_row = QHBoxLayout()
        step_btn_row.setSpacing(8)

        add_btn = QPushButton("添加步骤")
        add_btn.clicked.connect(self._add_step_from_ui)
        step_btn_row.addWidget(add_btn)

        up_btn = QPushButton("↑")
        up_btn.setFixedWidth(30)
        up_btn.clicked.connect(self._move_step_up)
        step_btn_row.addWidget(up_btn)

        down_btn = QPushButton("↓")
        down_btn.setFixedWidth(30)
        down_btn.clicked.connect(self._move_step_down)
        step_btn_row.addWidget(down_btn)

        del_btn = QPushButton("✕ 删除")
        del_btn.clicked.connect(self._delete_selected_step)
        step_btn_row.addWidget(del_btn)

        step_btn_row.addStretch()
        root.addLayout(step_btn_row)

        # 底部按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch()

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)

        save_btn = QPushButton("保存")
        save_btn.setDefault(True)
        save_btn.clicked.connect(self._on_save)
        btn_row.addWidget(save_btn)

        root.addLayout(btn_row)

        # 填充手势下拉框
        self._populate_gesture_combo()

    def _populate_gesture_combo(self) -> None:
        """用所有可用手势名称填充下拉框。"""
        self._gesture_combo.clear()
        names = self._gm.get_all_gesture_names()
        for name in names:
            display = name
            if self._gm.is_builtin_gesture(name):
                display = f"(内置) {name}"
            self._gesture_combo.addItem(display, name)

    def _populate_existing(self, name: str) -> None:
        """用已有序列数据预填充对话框。"""
        data = self._gm.get_sequence(name)
        if not data:
            return

        self._name_edit.setText(name)
        self._name_edit.setEnabled(False)
        self._loop_checkbox.setChecked(data.get("loop", False))

        self._steps = [dict(s) for s in data.get("steps", [])]
        self._refresh_step_list()

    def _refresh_step_list(self) -> None:
        """刷新步骤列表显示。"""
        self._step_list.clear()
        for i, step in enumerate(self._steps):
            gesture_name = step.get("gesture_name", "?")
            duration = step.get("duration", 0)
            delay = step.get("delay_after", 0)
            item_text = (
                f"{i + 1}. {gesture_name}  "
                f"持续 {duration:.1f}s  →  延迟 {delay:.1f}s"
            )
            item = QListWidgetItem(item_text)
            # 检查引用是否有效
            if self._gm.resolve_gesture(gesture_name) is None:
                item.setForeground(QColor("#ff6666"))
            self._step_list.addItem(item)

    def _on_step_selected(self) -> None:
        """步骤列表选择变化 — 将编辑区域同步到选中步骤。"""
        row = self._step_list.currentRow()
        if row < 0 or row >= len(self._steps):
            return

        step = self._steps[row]
        gesture_name = step.get("gesture_name", "")

        # 在下拉框中找到对应项
        idx = self._gesture_combo.findData(gesture_name)
        if idx >= 0:
            self._gesture_combo.setCurrentIndex(idx)
        else:
            # 自定义手势可能不在列表中（如果刚创建），刷新列表
            self._populate_gesture_combo()
            idx = self._gesture_combo.findData(gesture_name)
            if idx >= 0:
                self._gesture_combo.setCurrentIndex(idx)

        self._duration_spin.setValue(step.get("duration", 1.0))
        self._delay_spin.setValue(step.get("delay_after", 0.0))

    def _add_step_from_ui(self) -> None:
        """从编辑区域的值添加新步骤。"""
        gesture_name = self._gesture_combo.currentData()
        if not gesture_name:
            return

        step = {
            "gesture_name": gesture_name,
            "duration": self._duration_spin.value(),
            "delay_after": self._delay_spin.value(),
        }
        self._steps.append(step)
        self._refresh_step_list()
        # 滚动到底部
        self._step_list.scrollToBottom()
        self._step_list.setCurrentRow(len(self._steps) - 1)

    def _delete_selected_step(self) -> None:
        """删除选中的步骤。"""
        row = self._step_list.currentRow()
        if row >= 0 and row < len(self._steps):
            del self._steps[row]
            self._refresh_step_list()

    def _move_step_up(self) -> None:
        """将选中步骤上移。"""
        row = self._step_list.currentRow()
        if row > 0:
            self._steps[row - 1], self._steps[row] = (
                self._steps[row], self._steps[row - 1]
            )
            self._refresh_step_list()
            self._step_list.setCurrentRow(row - 1)

    def _move_step_down(self) -> None:
        """将选中步骤下移。"""
        row = self._step_list.currentRow()
        if row < len(self._steps) - 1:
            self._steps[row + 1], self._steps[row] = (
                self._steps[row], self._steps[row + 1]
            )
            self._refresh_step_list()
            self._step_list.setCurrentRow(row + 1)

    def _on_save(self) -> None:
        """保存按钮回调。"""
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "名称无效", "序列名称不能为空")
            return

        if not self._steps:
            QMessageBox.warning(self, "步骤为空", "序列至少需要 1 个步骤")
            return

        # 验证所有步骤
        valid, err = self._gm.validate_sequence_steps(self._steps)
        if not valid:
            QMessageBox.warning(self, "步骤验证失败", err)
            return

        self.dialog_accepted.emit(
            name, list(self._steps), self._loop_checkbox.isChecked()
        )
        self.accept()


# ──────────────────────────────────────────────────────────────────
# 3. GestureManagePanel — 嵌入主窗口的手势管理面板
# ──────────────────────────────────────────────────────────────────

class GestureManagePanel(QWidget):
    """手势管理面板 — 嵌入主窗口左侧，提供预设/自定义/序列管理入口。

    三个标签页:
    - 预设: 内置手势快捷按钮
    - 自定义: 用户创建的手势，支持编辑/删除
    - 序列: 序列列表，支持播放/编辑/删除
    """

    gesture_selected = Signal(str, tuple)       # (name, dof_values)
    sequence_play_requested = Signal(str)        # sequence_name
    sequence_stop_requested = Signal()
    gesture_create_requested = Signal()
    sequence_create_requested = Signal()
    gesture_edit_requested = Signal(str)         # gesture_name
    sequence_edit_requested = Signal(str)        # sequence_name

    def __init__(
        self,
        gesture_manager: GestureManager,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._gm = gesture_manager
        self._custom_buttons: dict[str, QPushButton] = {}
        self._sequence_items: dict[str, QWidget] = {}

        self._gm.on_changed(self._on_data_changed)

        self._build_ui()
        self.setMinimumHeight(170)
        self.refresh()

    def _build_ui(self) -> None:
        """构建面板 UI。"""
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 8, 0, 0)
        root.setSpacing(0)

        # 面板标题
        title = QLabel("手势管理")
        title.setFont(QFont("Sans", 11, QFont.Bold))
        title.setStyleSheet(f"color: {_COLOR_TEXT_DIM};")
        root.addWidget(title)

        # 标签页
        from PySide2.QtWidgets import QTabWidget
        self._tabs = QTabWidget()
        self._tabs.setStyleSheet(f"""
            QTabWidget::pane {{
                border: 1px solid #444444;
                background: {_COLOR_SURFACE};
            }}
            QTabBar::tab {{
                background: {_COLOR_BG};
                color: {_COLOR_TEXT_DIM};
                padding: 6px 16px;
                border: 1px solid #444444;
                border-bottom: none;
                margin-right: 2px;
            }}
            QTabBar::tab:selected {{
                background: {_COLOR_SURFACE};
                color: {_COLOR_TEXT};
            }}
            QTabBar::tab:hover {{
                background: #4a4a4a;
            }}
        """)

        # 预设标签页
        self._tabs.addTab(self._build_preset_tab(), "预设")

        # 自定义标签页
        self._tabs.addTab(self._build_custom_tab(), "自定义")

        # 序列标签页
        self._tabs.addTab(self._build_sequence_tab(), "序列")

        root.addWidget(self._tabs, stretch=1)

    def _build_preset_tab(self) -> QWidget:
        """构建预设手势标签页。"""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(140)

        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        preset_names = [
            ("张开", "open"),
            ("握拳", "fist"),
            ("OK", "ok"),
            ("捏取", "pinch"),
            ("指向", "point"),
            ("比耶", "peace"),
            ("竖大拇指", "thumbs_up"),
        ]

        grid = QGridLayout()
        grid.setSpacing(6)
        for i, (display, name) in enumerate(preset_names):
            btn = QPushButton(display)
            btn.setFixedHeight(32)
            btn.setMinimumWidth(72)
            btn.clicked.connect(
                lambda checked=False, n=name, d=display: (
                    self.gesture_selected.emit(n, self._gm.resolve_gesture(n) or tuple([255] * 10))
                )
            )
            row, col = divmod(i, 2)
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        layout.addStretch()

        scroll.setWidget(inner)
        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(scroll)
        return container

    def _build_custom_tab(self) -> QWidget:
        """构建自定义手势标签页。"""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(140)

        inner = QWidget()
        self._custom_layout = QVBoxLayout(inner)
        self._custom_layout.setSpacing(6)
        self._custom_layout.setContentsMargins(8, 8, 8, 8)

        # 新建按钮
        new_btn = QPushButton("+ 新建手势")
        new_btn.setFixedHeight(32)
        new_btn.setMinimumWidth(72)
        new_btn.clicked.connect(self.gesture_create_requested)
        self._custom_layout.addWidget(new_btn)

        self._custom_layout.addStretch()
        scroll.setWidget(inner)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(scroll)
        return container

    def _build_sequence_tab(self) -> QWidget:
        """构建序列标签页。"""
        widget = QWidget()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setMinimumWidth(140)

        inner = QWidget()
        self._sequence_layout = QVBoxLayout(inner)
        self._sequence_layout.setSpacing(6)
        self._sequence_layout.setContentsMargins(8, 8, 8, 8)

        # 新建按钮
        new_seq_btn = QPushButton("+ 新建序列")
        new_seq_btn.setFixedHeight(32)
        new_seq_btn.setMinimumWidth(72)
        new_seq_btn.clicked.connect(self.sequence_create_requested)
        self._sequence_layout.addWidget(new_seq_btn)

        self._sequence_layout.addStretch()
        scroll.setWidget(inner)

        container = QWidget()
        container_layout = QVBoxLayout(container)
        container_layout.setContentsMargins(0, 0, 0, 0)
        container_layout.addWidget(scroll)
        return container

    def refresh(self) -> None:
        """刷新所有标签页内容。"""
        self._refresh_custom_tab()
        self._refresh_sequence_tab()

    def _refresh_custom_tab(self) -> None:
        """刷新自定义手势标签页。"""
        # 清除旧按钮（保留"新建"按钮）
        for btn in self._custom_buttons.values():
            btn.setParent(None)
            btn.deleteLater()
        self._custom_buttons.clear()

        # 在 stretch 之前插入按钮
        layout = self._custom_layout
        custom_names = self._gm.list_custom_gestures()

        for name in sorted(custom_names.keys()):
            data = custom_names[name]
            btn = QPushButton(name)
            btn.setFixedHeight(32)
            btn.setMinimumWidth(72)
            btn.setToolTip(data.get("description", ""))
            btn.clicked.connect(
                lambda checked=False, n=name: self._on_custom_gesture_clicked(n)
            )
            # 右键菜单
            btn.setContextMenuPolicy(Qt.CustomContextMenu)
            btn.customContextMenuRequested.connect(
                lambda pos, n=name, b=btn: self._show_custom_context_menu(n, b)
            )

            # 插入到 stretch 之前
            layout.insertWidget(layout.count() - 1, btn)
            self._custom_buttons[name] = btn

    def _refresh_sequence_tab(self) -> None:
        """刷新序列标签页。"""
        for item_widget in self._sequence_items.values():
            item_widget.setParent(None)
            item_widget.deleteLater()
        self._sequence_items.clear()

        layout = self._sequence_layout
        sequences = self._gm.list_sequences()

        for name in sorted(sequences.keys()):
            seq_data = sequences[name]
            item_widget = self._build_sequence_item(name, seq_data)
            layout.insertWidget(layout.count() - 1, item_widget)
            self._sequence_items[name] = item_widget

    def _build_sequence_item(
        self, name: str, data: dict[str, Any]
    ) -> QWidget:
        """构建单个序列项控件。"""
        item = QWidget()
        row = QHBoxLayout(item)
        row.setContentsMargins(4, 4, 4, 4)
        row.setSpacing(6)

        name_label = QLabel(name)
        name_label.setStyleSheet(f"color: {_COLOR_TEXT};")
        row.addWidget(name_label, stretch=1)

        play_btn = QPushButton("▶")
        play_btn.setFixedHeight(28)
        play_btn.setMinimumWidth(36)
        play_btn.setStyleSheet("padding: 4px 6px; text-align: center;")
        play_btn.clicked.connect(
            lambda checked=False, n=name: self.sequence_play_requested.emit(n)
        )
        row.addWidget(play_btn)

        edit_btn = QPushButton("编辑")
        edit_btn.setFixedHeight(28)
        edit_btn.setMinimumWidth(64)
        edit_btn.setStyleSheet("padding: 4px 10px;")
        edit_btn.clicked.connect(
            lambda checked=False, n=name: self._on_sequence_edit(n)
        )
        row.addWidget(edit_btn)

        del_btn = QPushButton("✕")
        del_btn.setFixedHeight(28)
        del_btn.setMinimumWidth(32)
        del_btn.setStyleSheet("padding: 4px 6px;")
        del_btn.clicked.connect(
            lambda checked=False, n=name: self._on_sequence_delete(n)
        )
        row.addWidget(del_btn)

        item.setStyleSheet(f"""
            QWidget {{
                background: {_COLOR_SURFACE};
                border-radius: 4px;
            }}
        """)

        return item

    def _on_custom_gesture_clicked(self, name: str) -> None:
        """自定义手势按钮点击 — 发射信号。"""
        dof_values = self._gm.resolve_gesture(name)
        if dof_values:
            self.gesture_selected.emit(name, dof_values)

    def _show_custom_context_menu(self, name: str, button: QPushButton) -> None:
        """自定义手势右键菜单。"""
        from PySide2.QtWidgets import QMenu, QAction

        menu = QMenu(self)
        menu.setStyleSheet(f"""
            QMenu {{
                background: {_COLOR_SURFACE};
                color: {_COLOR_TEXT};
                border: 1px solid #555555;
            }}
            QMenu::item:selected {{
                background: #555555;
            }}
        """)

        edit_action = QAction(f"编辑 '{name}'", self)
        edit_action.triggered.connect(lambda: self._on_custom_gesture_edit(name))
        menu.addAction(edit_action)

        delete_action = QAction(f"删除 '{name}'", self)
        delete_action.triggered.connect(
            lambda: self._on_custom_gesture_delete(name)
        )
        menu.addAction(delete_action)

        menu.exec_(button.mapToGlobal(button.rect().bottomLeft()))

    def _on_custom_gesture_edit(self, name: str) -> None:
        """编辑自定义手势 — 由主窗口处理对话框。"""
        # 使用 signal 通知主窗口
        # 这里我们直接发出一个自定义信号或者让主窗口监听
        # 简化处理：让 GestureManagePanel 的 parent (ControlPanelWindow) 处理
        # 实际上通过 event filter 或直接调用比较麻烦，
        # 所以我们发一个信号让外部处理
        self.gesture_edit_requested.emit(name)

    def _on_custom_gesture_delete(self, name: str) -> None:
        """删除自定义手势。"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除自定义手势 '{name}' 吗？\n"
            f"引用该手势的序列步骤会变为无效。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._gm.delete_custom_gesture(name)

    def _on_sequence_edit(self, name: str) -> None:
        """编辑序列 — 由主窗口处理。"""
        self.sequence_edit_requested.emit(name)

    def _on_sequence_delete(self, name: str) -> None:
        """删除序列。"""
        reply = QMessageBox.question(
            self,
            "确认删除",
            f"确定删除序列 '{name}' 吗？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if reply == QMessageBox.Yes:
            self._gm.delete_sequence(name)

    def _on_data_changed(self, change_type: str, key: str) -> None:
        """数据变更回调 — 刷新面板显示。"""
        if change_type in (
            "gesture_created", "gesture_updated", "gesture_deleted",
            "sequence_created", "sequence_updated", "sequence_deleted",
        ):
            self.refresh()

    def set_sequences_enabled(self, enabled: bool) -> None:
        """启用/禁用序列按钮（播放期间禁用）。"""
        for item_widget in self._sequence_items.values():
            play_btn = item_widget.findChild(QPushButton)
            if play_btn:
                play_btn.setEnabled(enabled)


# ──────────────────────────────────────────────────────────────────
# 4. SequencePlayerOverlay — 序列播放进度覆盖层
# ──────────────────────────────────────────────────────────────────

class SequencePlayerOverlay(QWidget):
    """序列播放进度覆盖层 — 在主窗口左侧顶部显示。

    播放期间显示当前序列名称、步骤进度、当前手势倒计时。
    提供暂停/停止按钮。
    """

    stopped = Signal()
    finished = Signal()

    def __init__(
        self,
        gesture_manager: GestureManager,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._gm = gesture_manager

        self._sequence_name: str = ""
        self._steps: list[dict[str, Any]] = []
        self._loop: bool = False
        self._current_step: int = 0
        self._phase: str = "duration"  # "duration" | "delay"
        self._phase_start: float = 0.0
        self._paused: bool = False
        self._pause_start: float = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.setInterval(33)  # ~30Hz

        self._progress_bar: QProgressBar | None = None
        self._status_label: QLabel | None = None
        self._step_label: QLabel | None = None
        self._pause_btn: QPushButton | None = None
        self._stop_btn: QPushButton | None = None

        self._build_ui()
        self.setVisible(False)

    def _build_ui(self) -> None:
        """构建覆盖层 UI。"""
        self.setStyleSheet(f"""
            QWidget {{
                background: #333340;
                border-radius: 6px;
            }}
            QPushButton {{
                background: {_COLOR_SURFACE}; color: {_COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px;
                padding: 4px 10px; font-size: 11px;
            }}
            QPushButton:hover {{
                background: #4a4a4a;
            }}
        """)
        self.setFixedHeight(70)

        root = QHBoxLayout(self)
        root.setContentsMargins(12, 8, 12, 8)
        root.setSpacing(10)

        # 播放图标 + 状态
        info_layout = QVBoxLayout()
        info_layout.setSpacing(2)

        self._status_label = QLabel("播放中")
        self._status_label.setFont(QFont("Sans", 10, QFont.Bold))
        self._status_label.setStyleSheet(f"color: {_COLOR_TEXT};")
        info_layout.addWidget(self._status_label)

        self._step_label = QLabel("")
        self._step_label.setFont(QFont("Sans", 9))
        self._step_label.setStyleSheet(f"color: {_COLOR_TEXT_DIM};")
        info_layout.addWidget(self._step_label)

        root.addLayout(info_layout, stretch=1)

        # 进度条
        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedWidth(150)
        self._progress_bar.setFixedHeight(16)
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setStyleSheet(f"""
            QProgressBar {{
                background: {_COLOR_TROUGH};
                border: none;
                border-radius: 4px;
            }}
            QProgressBar::chunk {{
                background: #6666aa;
                border-radius: 4px;
            }}
        """)
        root.addWidget(self._progress_bar)

        # 按钮行
        btn_layout = QVBoxLayout()
        btn_layout.setSpacing(2)

        self._pause_btn = QPushButton("⏸ 暂停")
        self._pause_btn.setFixedWidth(60)
        self._pause_btn.clicked.connect(self._toggle_pause)
        btn_layout.addWidget(self._pause_btn)

        self._stop_btn = QPushButton("⏹ 停止")
        self._stop_btn.setFixedWidth(60)
        self._stop_btn.clicked.connect(self.stop)
        btn_layout.addWidget(self._stop_btn)

        root.addLayout(btn_layout)

    def play_sequence(self, sequence_name: str) -> bool:
        """开始播放序列。

        Args:
            sequence_name: 要播放的序列名称。

        Returns:
            True 如果成功开始播放，False 如果序列不存在或无效。
        """
        seq = self._gm.get_sequence(sequence_name)
        if not seq:
            return False

        steps = seq.get("steps", [])
        if not steps:
            return False

        # 检查所有步骤引用有效
        for step in steps:
            if self._gm.resolve_gesture(step.get("gesture_name", "")) is None:
                return False

        self._sequence_name = sequence_name
        self._steps = [dict(s) for s in steps]
        self._loop = seq.get("loop", False)
        self._current_step = 0
        self._phase = "duration"
        self._phase_start = time.time()
        self._paused = False
        self._pause_start = 0.0

        self._pause_btn.setText("⏸ 暂停")
        self._status_label.setText(f"播放中: {sequence_name}")
        self.setVisible(True)

        self._timer.start()
        self._update_display()

        return True

    def stop(self) -> None:
        """停止播放。"""
        self._timer.stop()
        self.setVisible(False)

    def _toggle_pause(self) -> None:
        """切换暂停/继续。"""
        if self._paused:
            # 继续 — 将暂停时长加到 phase_start 上，补偿计时
            self._paused = False
            pause_duration = time.time() - self._pause_start
            self._phase_start += pause_duration
            self._pause_btn.setText("⏸ 暂停")
            self._timer.start()
        else:
            # 暂停
            self._paused = True
            self._pause_start = time.time()
            self._timer.stop()
            self._pause_btn.setText("▶ 继续")

    def _tick(self) -> None:
        """30Hz 更新 — 推进序列状态。"""
        if self._paused or not self._steps:
            return

        now = time.time()
        elapsed = now - self._phase_start
        step = self._steps[self._current_step]

        if self._phase == "duration":
            duration = step.get("duration", 1.0)
            if elapsed >= duration:
                delay = step.get("delay_after", 0.0)
                if delay > 0:
                    self._phase = "delay"
                    self._phase_start = now
                else:
                    if not self._advance_step():
                        return  # 序列已结束
        elif self._phase == "delay":
            delay = step.get("delay_after", 0.0)
            if elapsed >= delay:
                if not self._advance_step():
                    return  # 序列已结束

        self._update_display()

    def _advance_step(self) -> bool:
        """推进到序列的下一步。

        Returns:
            True 如果序列继续，False 如果序列已结束。
        """
        self._current_step += 1

        if self._current_step >= len(self._steps):
            if self._loop:
                self._current_step = 0
                self._phase = "duration"
                self._phase_start = time.time()
                return True
            else:
                self._timer.stop()
                self.finished.emit()
                return False

        self._phase = "duration"
        self._phase_start = time.time()
        return True

    def _update_display(self) -> None:
        """更新进度条和文本显示。"""
        if not self._steps:
            return

        total = len(self._steps)
        current = self._current_step + 1

        # 总进度
        total_progress = int(100 * current / total)
        if self._progress_bar:
            self._progress_bar.setValue(total_progress)

        # 当前步骤信息
        step = self._steps[self._current_step]
        gesture_name = step.get("gesture_name", "?")

        if self._phase == "duration":
            duration = step.get("duration", 1.0)
            remaining = max(0, duration - (time.time() - self._phase_start))
            if self._step_label:
                self._step_label.setText(
                    f"步骤 {current}/{total}: {gesture_name}  "
                    f"剩余 {remaining:.1f}s"
                )
        elif self._phase == "delay":
            delay = step.get("delay_after", 0.0)
            remaining = max(0, delay - (time.time() - self._phase_start))
            if self._step_label:
                self._step_label.setText(
                    f"步骤 {current}/{total}: {gesture_name}  "
                    f"延迟中 {remaining:.1f}s"
                )

    def is_playing(self) -> bool:
        """返回是否正在播放中。"""
        return self._timer.isActive()

    def current_sequence_name(self) -> str:
        """返回当前播放的序列名称。"""
        return self._sequence_name