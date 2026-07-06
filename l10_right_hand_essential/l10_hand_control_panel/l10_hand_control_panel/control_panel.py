#!/usr/bin/env python3
"""
L10 手部控制面板 - PySide2 双指示器滑块
作为 l10_hand_gateway 的前端面板

灰色指示器: 当前位姿状态 (订阅 /l10_gateway/current/dof, 只读)
白色指示器: 目标位姿 (用户拖动, 发布到 /l10_gateway/cmd/dof)
同时订阅 /l10_gateway/target/dof 用于外部命令驱动的目标更新 (不重发布)
"""

import sys
import threading
import math
import time
import json

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32, Float32MultiArray, String

from PySide2.QtCore import Qt, Signal, QRectF, QPointF, QTimer
from PySide2.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont
from PySide2.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy, QSplitter,
)

from l10_hand_control_panel.skeleton_widget import HandModelWidget
from l10_hand_control_panel.gesture_manager import GestureManager
from l10_hand_control_panel.gesture_dialogs import (
    GestureEditorDialog,
    SequenceEditorDialog,
    GestureManagePanel,
    SequencePlayerOverlay,
)


# 10 个自由度定义 (0-255 范围)
DOF_DEFINITIONS = [
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
COLOR_BG = "#2d2d2d"
COLOR_SURFACE = "#3c3c3c"
COLOR_TROUGH = "#555555"
COLOR_GRAY_FILL = "#888888"
COLOR_GRAY_OUTLINE = "#666666"
COLOR_WHITE_FILL = "#e0e0e0"
COLOR_WHITE_OUTLINE = "#aaaaaa"
COLOR_TEXT = "#cccccc"
COLOR_TEXT_DIM = "#999999"
COLOR_ACCENT = "#666666"


class DualSlider(QWidget):
    """双指示器滑块控件 —— 灰色菱形表示当前位姿 (只读)，白色菱形表示目标位姿 (可拖动)

    该控件在同一滑槽上显示两个菱形指示器:
    - 灰色指示器: 显示从网关订阅的当前实际位姿 (只读，不可拖动)
    - 白色指示器: 显示用户设置的目标位姿 (可通过鼠标拖动改变)

    当用户拖动白色指示器时，发射 valueChanged 信号，由 ControlPanelWindow
    将新的目标值发布到 /l10_gateway/cmd/dof。

    Attributes:
        TROUGH_PAD: 滑槽两端留白 (像素)
        INDICATOR_HW: 指示器半宽 (像素)
        INDICATOR_HH: 指示器半高 (像素)
    """

    valueChanged = Signal()

    TROUGH_PAD = 10
    INDICATOR_HW = 6
    INDICATOR_HH = 9

    def __init__(self, parent=None, val_range=(0, 255)):
        super().__init__(parent)
        self.val_min, self.val_max = val_range
        self._target = 0.0
        self._current = 0.0
        self._dragging = False

        self.setFixedHeight(22)
        self.setMinimumWidth(180)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def _val_to_x(self, val):
        pad = self.TROUGH_PAD
        w = self.width()
        frac = (val - self.val_min) / (self.val_max - self.val_min)
        return pad + frac * (w - 2 * pad)

    def _x_to_val(self, x):
        pad = self.TROUGH_PAD
        w = self.width()
        frac = (x - pad) / (w - 2 * pad)
        frac = max(0.0, min(1.0, frac))
        return self.val_min + frac * (self.val_max - self.val_min)

    def set_target(self, val):
        self._target = max(self.val_min, min(self.val_max, float(val)))
        self.update()

    def set_current(self, val):
        self._current = max(self.val_min, min(self.val_max, float(val)))
        self.update()

    def get_target_int(self):
        return int(round(self._target))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        cy = h / 2.0
        pad = self.TROUGH_PAD
        w = self.width()

        # 槽道背景 (圆角)
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(COLOR_TROUGH)))
        trough_rect = QRectF(pad, cy - 2, w - 2 * pad, 4)
        p.drawRoundedRect(trough_rect, 2, 2)

        # 灰色指示器 (当前状态)
        gx = self._val_to_x(self._current)
        self._draw_diamond(p, gx, cy, self.INDICATOR_HW - 1, self.INDICATOR_HH - 1,
                           COLOR_GRAY_FILL, COLOR_GRAY_OUTLINE)

        # 白色指示器 (目标)
        wx = self._val_to_x(self._target)
        self._draw_diamond(p, wx, cy, self.INDICATOR_HW, self.INDICATOR_HH,
                           COLOR_WHITE_FILL, COLOR_WHITE_OUTLINE)

        p.end()

    def _draw_diamond(self, painter, cx, cy, hw, hh, fill, outline):
        poly = QPolygonF([
            QPointF(cx, cy - hh),
            QPointF(cx + hw, cy),
            QPointF(cx, cy + hh),
            QPointF(cx - hw, cy),
        ])
        painter.setPen(QPen(QColor(outline), 1))
        painter.setBrush(QBrush(QColor(fill)))
        painter.drawPolygon(poly)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._apply_mouse(event.x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._apply_mouse(event.x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _apply_mouse(self, x):
        val = self._x_to_val(x)
        self._target = val
        self.update()
        self.valueChanged.emit()


class SpeedSlider(QWidget):
    """单指示器速度限制滑块 — 白色菱形 + 填充色条 (0-100%)

    填充色从橙（慢）渐变到绿（快），与 DualSlider 视觉风格一致。
    """
    valueChanged = Signal()

    TROUGH_PAD = 10
    INDICATOR_HW = 6
    INDICATOR_HH = 9

    def __init__(self, parent=None, val_range=(0, 100)):
        super().__init__(parent)
        self.val_min, self.val_max = val_range
        self._target = 100.0
        self._dragging = False
        self.setFixedHeight(22)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)

    def _val_to_x(self, val):
        pad = self.TROUGH_PAD
        w = self.width()
        frac = (val - self.val_min) / (self.val_max - self.val_min)
        return pad + frac * (w - 2 * pad)

    def _x_to_val(self, x):
        pad = self.TROUGH_PAD
        w = self.width()
        frac = (x - pad) / (w - 2 * pad)
        frac = max(0.0, min(1.0, frac))
        return self.val_min + frac * (self.val_max - self.val_min)

    def set_target(self, val):
        self._target = max(self.val_min, min(self.val_max, float(val)))
        self.update()

    def get_target_int(self):
        return int(round(self._target))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        h = self.height()
        cy = h / 2.0
        pad = self.TROUGH_PAD
        w = self.width()

        # 槽道背景
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(COLOR_TROUGH)))
        trough_rect = QRectF(pad, cy - 2, w - 2 * pad, 4)
        p.drawRoundedRect(trough_rect, 2, 2)

        # 填充色条 (橙→绿渐变)
        tx = self._val_to_x(self._target)
        if tx > pad + 1:
            pct = self._target / self.val_max
            fill_color = QColor(
                int(255 * pct),
                int(200 * (1 - pct)),
                50,
            )
            p.setBrush(QBrush(fill_color))
            p.drawRoundedRect(QRectF(pad, cy - 2, tx - pad, 4), 2, 2)

        # 白色菱形指示器
        self._draw_diamond(p, tx, cy, self.INDICATOR_HW, self.INDICATOR_HH,
                           COLOR_WHITE_FILL, COLOR_WHITE_OUTLINE)
        p.end()

    def _draw_diamond(self, painter, cx, cy, hw, hh, fill, outline):
        poly = QPolygonF([
            QPointF(cx, cy - hh),
            QPointF(cx + hw, cy),
            QPointF(cx, cy + hh),
            QPointF(cx - hw, cy),
        ])
        painter.setPen(QPen(QColor(outline), 1))
        painter.setBrush(QBrush(QColor(fill)))
        painter.drawPolygon(poly)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._apply_mouse(event.x())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._apply_mouse(event.x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def _apply_mouse(self, x):
        val = self._x_to_val(x)
        self._target = val
        self.update()
        self.valueChanged.emit()


class LegendIndicator(QWidget):
    """图例中的小菱形图标"""
    def __init__(self, fill, outline, parent=None):
        super().__init__(parent)
        self.fill = QColor(fill)
        self.outline = QColor(outline)
        self.setFixedSize(16, 16)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = 8, 8
        poly = QPolygonF([
            QPointF(cx, cy - 5),
            QPointF(cx + 4, cy),
            QPointF(cx, cy + 5),
            QPointF(cx - 4, cy),
        ])
        p.setPen(QPen(self.outline, 1))
        p.setBrush(QBrush(self.fill))
        p.drawPolygon(poly)
        p.end()


# ---- 触觉传感器热力图组件 ----

class HeatmapWidget(QWidget):
    """单指触觉传感器热力图控件 —— 12×6 压力矩阵的可视化

    使用 plasma 色表 (4 段渐变) 将 12×6 压力矩阵渲染为彩色热力图。
    每个单元格的颜色表示该位置的压力值 (0=深蓝, 255=亮黄)。
    上方显示手指名称标签，下方显示总压力质量 (克)。

    Attributes:
        FINGER_NAMES: 5 个手指的英文名称 (用于标签显示)
        FINGER_COLORS: 5 个手指的标识颜色 (紫/金/蓝/绿/红)
        ROWS: 压力矩阵行数 (12)
        COLS: 压力矩阵列数 (6)
    """

    FINGER_NAMES = ["Pinky", "Ring", "Middle", "Index", "Thumb"]
    FINGER_COLORS = [
        QColor(218, 112, 214),
        QColor(255, 215, 0),
        QColor(65, 105, 255),
        QColor(50, 205, 50),
        QColor(255, 75, 75),
    ]
    ROWS = 12
    COLS = 6

    # plasma 色表 4-stop 渐变
    _STOPS = [
        (0.00, (13, 8, 135)),
        (0.33, (126, 3, 168)),
        (0.66, (204, 71, 120)),
        (1.00, (240, 249, 33)),
    ]

    def __init__(self, finger_index, parent=None):
        super().__init__(parent)
        self.finger_index = finger_index
        self._data = [[0] * self.COLS for _ in range(self.ROWS)]
        self._mass = 0.0
        self.setFixedSize(96, 128)

    @staticmethod
    def _value_to_color(val):
        t = max(0.0, min(255.0, val)) / 255.0
        stops = HeatmapWidget._STOPS
        for i in range(len(stops) - 1):
            t0, c0 = stops[i]
            t1, c1 = stops[i + 1]
            if t <= t1:
                frac = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
                r = int(c0[0] + frac * (c1[0] - c0[0]))
                g = int(c0[1] + frac * (c1[1] - c0[1]))
                b = int(c0[2] + frac * (c1[2] - c0[2]))
                return QColor(r, g, b)
        return QColor(240, 249, 33)

    def set_matrix_data(self, matrix_12x6):
        self._data = matrix_12x6
        self.update()

    def set_mass(self, mass_grams):
        self._mass = mass_grams
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)

        label_h = 16
        mass_h = 14
        pad = 3
        grid_w = self.width() - 2 * pad
        grid_h = self.height() - label_h - mass_h - 2 * pad
        cell_w = grid_w / self.COLS
        cell_h = grid_h / self.ROWS

        # 手指名称标签
        p.setPen(QPen(self.FINGER_COLORS[self.finger_index]))
        p.setFont(QFont("Sans", 9, QFont.Bold))
        p.drawText(QRectF(0, 0, self.width(), label_h), Qt.AlignCenter,
                   self.FINGER_NAMES[self.finger_index])

        # 热力图格子
        grid_top = label_h + pad
        for r in range(self.ROWS):
            for c in range(self.COLS):
                val = self._data[r][c]
                color = self._value_to_color(val)
                x = pad + c * cell_w
                y = grid_top + r * cell_h
                p.fillRect(QRectF(x, y, cell_w - 0.5, cell_h - 0.5), color)

        # 边框
        p.setPen(QPen(QColor("#555555"), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(pad - 0.5, grid_top - 0.5, grid_w + 1, grid_h + 1))

        # 质量数值
        p.setPen(QPen(QColor(COLOR_TEXT_DIM)))
        p.setFont(QFont("Monospace", 8))
        p.drawText(QRectF(0, self.height() - mass_h, self.width(), mass_h),
                   Qt.AlignCenter, f"{self._mass:.0f}g")

        p.end()


class _ColorBarWidget(QWidget):
    """垂直色标条"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(16)

    def paintEvent(self, event):
        p = QPainter(self)
        h = self.height()
        w = self.width()
        for y in range(h):
            val = int(255.0 * (1.0 - y / h))
            color = HeatmapWidget._value_to_color(val)
            p.setPen(QPen(color))
            p.drawLine(0, y, w, y)
        p.end()


class TactileStripWidget(QWidget):
    """触觉传感器底部条形控件 —— 5 个手指热力图 + 垂直色标

    水平排列显示 5 个手指的热力图 (HeatmapWidget)，左侧附带垂直色标条。
    接收来自网关的触觉矩阵数据和质量数据，分发到对应的热力图子控件。
    排列顺序: 色标 | 标题 | 小指 | 无名指 | 中指 | 食指 | 拇指
    """
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 4, 10, 4)
        layout.setSpacing(26)

        # 色标 (最左边)
        legend = QWidget()
        legend.setFixedWidth(24)
        legend_lay = QVBoxLayout(legend)
        legend_lay.setContentsMargins(0, 16, 0, 4)
        legend_lay.setSpacing(0)

        lbl_max = QLabel("255")
        lbl_max.setFont(QFont("Monospace", 7))
        lbl_max.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        lbl_max.setAlignment(Qt.AlignCenter)
        legend_lay.addWidget(lbl_max)

        bar = _ColorBarWidget()
        bar.setFixedHeight(64)
        legend_lay.addWidget(bar)

        lbl_min = QLabel("0")
        lbl_min.setFont(QFont("Monospace", 7))
        lbl_min.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        lbl_min.setAlignment(Qt.AlignCenter)
        legend_lay.addWidget(lbl_min)

        layout.addWidget(legend)

        title = QLabel("Tactile Sensor")
        title.setFont(QFont("Sans", 10, QFont.Bold))
        title.setStyleSheet(f"color: {COLOR_TEXT};")
        title.setFixedWidth(95)
        layout.addWidget(title)

        layout.addStretch()

        # 5 个热力图: 小指 → 大拇指 (index 0=little, 1=ring, 2=middle, 3=index, 4=thumb)
        self.heatmaps = []
        for i in range(5):
            hw = HeatmapWidget(i)
            layout.addWidget(hw)
            self.heatmaps.append(hw)

    def update_tactile(self, matrix_data, mass_data):
        # 热力图顺序: 0=little, 1=ring, 2=middle, 3=index, 4=thumb
        finger_names = ["little", "ring", "middle", "index", "thumb"]
        for i, name in enumerate(finger_names):
            key_matrix = f"{name}_matrix"
            key_mass = f"{name}_mass"

            if key_matrix in matrix_data:
                self.heatmaps[i].set_matrix_data(matrix_data[key_matrix])
            if key_mass in mass_data:
                val = mass_data[key_mass]
                if isinstance(val, list):
                    val = val[0] if val else 0.0
                self.heatmaps[i].set_mass(float(val))


class ControlPanelNode(Node):
    """ROS 2 控制面板节点 —— 通过 l10_hand_gateway 网关与后端通信

    负责将面板的用户操作 (DOF 命令、相机命令) 发布到网关，
    同时订阅网关广播的当前/目标状态和触觉传感器数据，
    通过回调函数传递给 ControlPanelWindow。

    发布话题:
        - /l10_gateway/cmd/dof: 用户设置的目标 DOF 值
        - /l10_gateway/cmd/camera: 用户调整的相机状态

    订阅话题:
        - /l10_gateway/current/dof: 后端当前实际位姿
        - /l10_gateway/target/dof: 网关确认的目标位姿 (外部命令更新)
        - /l10_gateway/sensor/matrix_touch: 触觉矩阵数据
        - /l10_gateway/sensor/matrix_touch_mass: 触觉质量数据
        - /l10_gateway/camera: 相机状态广播
    """

    def __init__(self):
        super().__init__('l10_control_panel')

        # 发布器: 命令 → 网关
        self.dof_pub = self.create_publisher(
            JointState, '/l10_gateway/cmd/dof', 10
        )
        self.camera_pub = self.create_publisher(
            Float32MultiArray, '/l10_gateway/cmd/camera', 10
        )
        self.speed_limit_pub = self.create_publisher(
            Float32, '/l10_gateway/cmd/speed_limit', 10
        )

        # 订阅: 网关广播的当前/目标状态
        self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._current_cb, 10
        )
        self.create_subscription(
            JointState, '/l10_gateway/target/dof', self._target_cb, 10
        )

        # 订阅: 网关广播的触觉传感器数据
        self.create_subscription(
            String, '/l10_gateway/sensor/matrix_touch', self._matrix_cb, 10
        )
        self.create_subscription(
            String, '/l10_gateway/sensor/matrix_touch_mass', self._mass_cb, 10
        )

        # 外部回调 (由 ControlPanelWindow 设置)
        self.on_current_state = None
        self.on_target_state = None
        self.on_tactile_matrix = None
        self.on_tactile_mass = None
        self.on_camera_state = None
        self.on_speed_limit = None

        # 订阅: 网关广播的相机状态
        self.create_subscription(
            Float32MultiArray, '/l10_gateway/camera', self._camera_cb, 10
        )

        # 订阅: 网关广播的速度限制
        self.create_subscription(
            Float32, '/l10_gateway/speed_limit', self._speed_limit_cb, 10
        )

        self.get_logger().info("L10 Control Panel Node initialized (gateway mode)")

    def publish_dof(self, positions):
        """发布 DOF 命令到网关"""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.position = [float(p) for p in positions]
        self.dof_pub.publish(msg)

    def publish_camera(self, camera_data):
        """发布相机状态到网关"""
        msg = Float32MultiArray()
        msg.data = [float(v) for v in camera_data]
        self.camera_pub.publish(msg)

    def publish_speed_limit(self, percentage):
        """发布速度限制百分比到网关 (0-100, 100=不限)"""
        msg = Float32()
        msg.data = float(percentage)
        self.speed_limit_pub.publish(msg)

    def _current_cb(self, msg):
        if len(msg.position) < 10:
            return
        values = [float(p) for p in msg.position[:10]]
        if self.on_current_state:
            self.on_current_state(values)

    def _target_cb(self, msg):
        if len(msg.position) < 10:
            return
        values = [float(p) for p in msg.position[:10]]
        if self.on_target_state:
            self.on_target_state(values)

    def _matrix_cb(self, msg):
        if self.on_tactile_matrix:
            self.on_tactile_matrix(msg.data)

    def _mass_cb(self, msg):
        if self.on_tactile_mass:
            self.on_tactile_mass(msg.data)

    def _camera_cb(self, msg):
        if len(msg.data) >= 4 and self.on_camera_state:
            self.on_camera_state(list(msg.data[:4]))

    def _speed_limit_cb(self, msg):
        if self.on_speed_limit:
            self.on_speed_limit(float(msg.data))


class _StateSignal(QWidget):
    """跨线程信号中转控件 —— 将 ROS spin 线程的状态更新安全传递到 Qt 主线程

    Qt 的信号/槽机制是线程安全的，而直接在非 Qt 线程操作 QWidget 会导致崩溃。
    _StateSignal 提供一组 Signal 属性，由 ROS 回调函数 (运行在 spin daemon 线程)
    通过 emit() 发射，对应的槽函数在 Qt 主线程中执行。
    """
    current_received = Signal(list)
    target_received = Signal(list)
    tactile_matrix_received = Signal(str)
    tactile_mass_received = Signal(str)
    camera_received = Signal(list)
    speed_limit_received = Signal(float)

    def __init__(self):
        super().__init__()


class ControlPanelWindow(QWidget):
    """L10 手部控制面板主窗口 —— 滑块控制 + 3D 骨架交互 + 触觉热力图

    窗口分为上下两个区域:
    - 上部: 左侧 10 个双指示器滑块 + 预设手势按钮，右侧 3D 骨架交互控件
    - 下部: 5 个手指的触觉传感器热力图条

    线程模型:
    - Qt 主线程: 处理 UI 渲染和用户交互
    - ROS spin daemon 线程: 接收网关消息
    - _StateSignal 桥接两个线程，确保 UI 操作在主线程执行

    防循环机制 (_syncing 标志):
    当外部命令更新目标状态时 (如 LLM 控制器发送手势)，面板需要同步更新
    滑块位置。但滑块更新的 valueChanged 信号又会触发发布命令，形成死循环。
    _syncing 标志在同步更新期间设为 True，阻止回调中的重入发布。
    """

    def __init__(self):
        super().__init__()
        self._state_signal = _StateSignal()
        self._state_signal.current_received.connect(self._apply_current_state)
        self._state_signal.target_received.connect(self._apply_target_state)
        self._state_signal.tactile_matrix_received.connect(self._apply_tactile_matrix)
        self._state_signal.tactile_mass_received.connect(self._apply_tactile_mass)
        self._state_signal.camera_received.connect(self._apply_camera_state)
        self._state_signal.speed_limit_received.connect(self._apply_speed_limit)
        self.setWindowTitle("L10 Hand Control Panel")
        self.setStyleSheet(f"""
            QWidget {{ background: {COLOR_BG}; color: {COLOR_TEXT}; }}
            QLabel {{ color: {COLOR_TEXT}; }}
            QPushButton {{
                background: {COLOR_SURFACE};
                color: {COLOR_TEXT};
                border: 1px solid #555555;
                border-radius: 6px;
                padding: 6px 16px;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: #4a4a4a;
                border-color: #777777;
            }}
            QPushButton:pressed {{
                background: #555555;
                color: white;
            }}
        """)
        self.setMinimumSize(1100, 650)

        self.ros_node = None
        self.sliders = []
        self.val_labels = []
        self._syncing = False

        # 手势与序列管理
        self._gesture_manager = GestureManager()
        self._gesture_manager.load()
        self._sequence_playing = False
        self._sequence_data: dict[str, Any] | None = None
        self._sequence_timer: QTimer | None = None

        self._build_ui()

    def _build_ui(self):
        root_vbox = QVBoxLayout(self)
        root_vbox.setContentsMargins(0, 0, 0, 0)
        root_vbox.setSpacing(0)

        # === 上部: 原有水平布局 (滑块 + 3D 模型) ===
        h_container = QWidget()
        outer = QHBoxLayout(h_container)
        outer.setContentsMargins(20, 15, 20, 15)
        outer.setSpacing(0)

        # ========== 左侧: 滑块面板 ==========
        left = QVBoxLayout()
        left.setSpacing(8)

        # 标题
        title = QLabel("L10 手部控制 (0-255)")
        title.setFont(QFont("Sans", 15, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        left.addWidget(title)

        # 图例
        legend = QHBoxLayout()
        legend.setSpacing(4)
        legend.addWidget(LegendIndicator(COLOR_GRAY_FILL, COLOR_GRAY_OUTLINE))
        legend.addWidget(self._dim_label("当前位姿"))
        legend.addSpacing(16)
        legend.addWidget(LegendIndicator(COLOR_WHITE_FILL, COLOR_WHITE_OUTLINE))
        legend.addWidget(self._dim_label("目标位姿 (可拖动)"))
        legend.addStretch()
        left.addLayout(legend)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet("color: #444444;")
        left.addWidget(line)

        # 滑块网格
        grid = QGridLayout()
        grid.setSpacing(6)
        for i, dof in enumerate(DOF_DEFINITIONS):
            lbl = QLabel(dof["label"])
            lbl.setFixedWidth(160)
            grid.addWidget(lbl, i, 0)

            ds = DualSlider(val_range=(0, 255))
            ds.set_target(dof["default"])
            ds.valueChanged.connect(self._on_slider)
            grid.addWidget(ds, i, 1)
            self.sliders.append(ds)

            val_lbl = QLabel(str(dof["default"]))
            val_lbl.setFixedWidth(36)
            val_lbl.setAlignment(Qt.AlignCenter)
            val_lbl.setFont(QFont("Monospace", 11))
            grid.addWidget(val_lbl, i, 2)
            self.val_labels.append(val_lbl)

        left.addLayout(grid)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        line2.setStyleSheet("color: #333355;")
        left.addWidget(line2)

        # 速度限制滑块
        speed_row = QHBoxLayout()
        speed_row.setSpacing(8)
        speed_lbl = QLabel("速度限制:")
        speed_lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        speed_row.addWidget(speed_lbl)

        self._speed_slider = SpeedSlider(val_range=(0, 100))
        self._speed_slider.set_target(75)  # 默认 75%
        self._speed_slider.valueChanged.connect(self._on_speed_slider)
        speed_row.addWidget(self._speed_slider, stretch=1)

        self._speed_label = QLabel("75%")
        self._speed_label.setFixedWidth(40)
        self._speed_label.setAlignment(Qt.AlignCenter)
        self._speed_label.setFont(QFont("Monospace", 11))
        self._speed_label.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        speed_row.addWidget(self._speed_label)
        left.addLayout(speed_row)

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        for text, fn in [("抓取", self.close_hand), ("张开", self.open_hand), ("复位", self.reset_hand)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            btn_row.addWidget(b)
        left.addLayout(btn_row)

        # ── 手势管理面板 (含预设/自定义/序列三个标签页) ──
        self._gesture_panel = GestureManagePanel(self._gesture_manager, self)
        self._gesture_panel.gesture_selected.connect(self._on_gesture_selected)
        self._gesture_panel.sequence_play_requested.connect(self._on_sequence_play)
        self._gesture_panel.sequence_stop_requested.connect(self._on_sequence_stop)
        self._gesture_panel.gesture_create_requested.connect(self._open_gesture_editor)
        self._gesture_panel.sequence_create_requested.connect(self._open_sequence_editor)
        self._gesture_panel.gesture_edit_requested.connect(self._open_gesture_editor)
        self._gesture_panel.sequence_edit_requested.connect(self._open_sequence_editor)
        left.addWidget(self._gesture_panel)

        left.addStretch()
        outer.addLayout(left)

        # ========== 竖线分隔 + 间距 ==========
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #444444;")
        outer.addWidget(sep)
        outer.addSpacing(30)

        # ========== 右侧: 骨架交互 ==========
        self.skeleton = HandModelWidget()
        self.skeleton.set_dof_values([d["default"] for d in DOF_DEFINITIONS])
        self.skeleton.on_dof_changed = self._on_skeleton_drag
        self.skeleton.on_camera_changed = self._on_camera_changed
        self.skeleton.setMinimumWidth(350)
        outer.addWidget(self.skeleton, stretch=1)

        root_vbox.addWidget(h_container, stretch=1)

        # === 下部: 触觉传感器热力图条 ===
        sep_bottom = QFrame()
        sep_bottom.setFrameShape(QFrame.HLine)
        sep_bottom.setStyleSheet("color: #444444;")
        root_vbox.addWidget(sep_bottom)

        self.tactile_strip = TactileStripWidget()
        root_vbox.addWidget(self.tactile_strip)

    def _dim_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        return lbl

    # ---- ROS 接口 ----

    def set_ros_node(self, node):
        self.ros_node = node
        node.on_current_state = self._ros_current_update
        node.on_target_state = self._ros_target_update
        node.on_tactile_matrix = self._ros_tactile_matrix_update
        node.on_tactile_mass = self._ros_tactile_mass_update
        node.on_camera_state = self._ros_camera_update
        node.on_speed_limit = self._ros_speed_limit_update

    def _ros_current_update(self, values):
        """从 ROS spin 线程调用, 通过信号传递到 Qt 主线程"""
        self._state_signal.current_received.emit(values)

    def _ros_target_update(self, values):
        """从 ROS spin 线程调用, 通过信号传递到 Qt 主线程"""
        self._state_signal.target_received.emit(values)

    def _ros_tactile_matrix_update(self, json_str):
        self._state_signal.tactile_matrix_received.emit(json_str)

    def _ros_tactile_mass_update(self, json_str):
        self._state_signal.tactile_mass_received.emit(json_str)

    def _ros_camera_update(self, camera_data):
        self._state_signal.camera_received.emit(camera_data)

    def _ros_speed_limit_update(self, pct):
        self._state_signal.speed_limit_received.emit(pct)

    def _apply_current_state(self, values):
        """更新灰色指示器 — 当前位姿, 不发布"""
        for i, v in enumerate(values):
            if i < len(self.sliders):
                self.sliders[i].set_current(v)

    def _apply_target_state(self, values):
        """更新白色指示器 + 骨架 — 外部命令更新, 不发布"""
        if self._syncing:
            return
        self._syncing = True
        try:
            for i, v in enumerate(values):
                if i < len(self.sliders):
                    self.sliders[i].set_target(v)
                    self.val_labels[i].setText(str(int(round(v))))
            self.skeleton.set_dof_values([int(round(v)) for v in values])
        finally:
            self._syncing = False

    def _apply_tactile_matrix(self, json_str):
        try:
            self._latest_matrix = json.loads(json_str)
            self._update_tactile_display()
        except Exception:
            pass

    def _apply_tactile_mass(self, json_str):
        try:
            self._latest_mass = json.loads(json_str)
            self._update_tactile_display()
        except Exception:
            pass

    def _apply_camera_state(self, camera_data):
        self.skeleton.apply_camera_state(camera_data)

    def _apply_speed_limit(self, pct):
        """从网关同步速度限制值 — 不重发布"""
        if self._syncing:
            return
        self._syncing = True
        try:
            self._speed_slider.set_target(pct)
            self._speed_label.setText(f"{int(round(pct))}%")
        finally:
            self._syncing = False

    def _update_tactile_display(self):
        matrix = getattr(self, '_latest_matrix', None)
        mass = getattr(self, '_latest_mass', None)
        if matrix is not None and mass is not None:
            self.tactile_strip.update_tactile(matrix, mass)

    def _on_slider(self):
        """用户拖动滑块 → 发布到网关"""
        if self._syncing:
            return
        self._syncing = True
        try:
            values = [ds.get_target_int() for ds in self.sliders]
            self.skeleton.set_dof_values(values)
            self.publish_current()
            for i, ds in enumerate(self.sliders):
                self.val_labels[i].setText(str(ds.get_target_int()))
        finally:
            self._syncing = False

    def publish_current(self):
        if self.ros_node:
            positions = [ds.get_target_int() for ds in self.sliders]
            self.ros_node.publish_dof(positions)

    def _on_skeleton_drag(self, new_values):
        """骨架拖拽回调 — 同步更新滑块 + 发布到网关"""
        if self._syncing:
            return
        self._syncing = True
        try:
            for i, v in enumerate(new_values):
                self.sliders[i].set_target(v)
                self.val_labels[i].setText(str(int(round(v))))
            self.publish_current()
        finally:
            self._syncing = False

    def _on_camera_changed(self, camera_data):
        """相机变化回调 — 发布到网关"""
        if self.ros_node:
            self.ros_node.publish_camera(camera_data)

    def _on_speed_slider(self):
        """用户拖动速度滑块 → 发布到网关"""
        if self._syncing:
            return
        pct = self._speed_slider.get_target_int()
        self._speed_label.setText(f"{pct}%")
        if self.ros_node:
            self.ros_node.publish_speed_limit(pct)

    def _set_all(self, values):
        """用户操作 (按钮/预设) → 设置所有滑块 + 发布"""
        self._syncing = True
        try:
            for i, v in enumerate(values):
                self.sliders[i].set_target(v)
                self.val_labels[i].setText(str(int(round(v))))
            self.skeleton.set_dof_values(values)
        finally:
            self._syncing = False
        # 在 _syncing 外发布，避免回调阻塞
        self.publish_current()

    def open_hand(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        self._set_all(list(GESTURE_PRESETS["open"]))

    def close_hand(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        self._set_all(list(GESTURE_PRESETS["fist"]))

    def reset_hand(self):
        self._set_all([d["default"] for d in DOF_DEFINITIONS])

    def preset_ok(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        self._set_all(list(GESTURE_PRESETS["ok"]))

    def preset_pinch(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        self._set_all(list(GESTURE_PRESETS["pinch"]))

    def preset_point(self):
        from linker_hand_description.gesture_presets import GESTURE_PRESETS
        self._set_all(list(GESTURE_PRESETS["point"]))

    # ── 手势管理信号槽 ──────────────────────────────────────────────

    def _on_gesture_selected(self, name: str, dof_values: tuple) -> None:
        """用户选择了手势（预设或自定义）→ 设置所有滑块并发布。"""
        self._set_all(list(dof_values))

    def _open_gesture_editor(self, gesture_name: str | None = None) -> None:
        """打开手势编辑器对话框（创建或编辑）。"""
        current_dofs = [s.get_target_int() for s in self.sliders]

        dialog = GestureEditorDialog(
            self._gesture_manager,
            gesture_name=gesture_name,
            current_dofs=current_dofs,
            parent=self,
        )
        dialog.dialog_accepted.connect(self._on_gesture_editor_accepted)
        dialog.exec_()

    def _on_gesture_editor_accepted(self, name: str, dof_values: list) -> None:
        """手势编辑器保存回调。"""
        try:
            if self._gesture_manager.get_custom_gesture(name):
                self._gesture_manager.update_custom_gesture(name, dof_values)
            else:
                self._gesture_manager.create_custom_gesture(name, dof_values)
        except (ValueError, KeyError) as exc:
            from PySide2.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", str(exc))

    def _open_sequence_editor(self, sequence_name: str | None = None) -> None:
        """打开序列编辑器对话框（创建或编辑）。"""
        dialog = SequenceEditorDialog(
            self._gesture_manager,
            sequence_name=sequence_name,
            parent=self,
        )
        dialog.dialog_accepted.connect(self._on_sequence_editor_accepted)
        dialog.exec_()

    def _on_sequence_editor_accepted(
        self, name: str, steps: list, loop: bool
    ) -> None:
        """序列编辑器保存回调。"""
        try:
            if self._gesture_manager.get_sequence(name):
                self._gesture_manager.update_sequence(name, steps, loop)
            else:
                self._gesture_manager.create_sequence(name, steps, loop)
        except (ValueError, KeyError) as exc:
            from PySide2.QtWidgets import QMessageBox
            QMessageBox.warning(self, "保存失败", str(exc))

    # ── 序列播放控制 ────────────────────────────────────────────────

    def _on_sequence_play(self, name: str) -> None:
        """用户点击播放序列。"""
        if self._start_sequence_playback(name):
            self._gesture_panel.set_sequences_enabled(False)

    def _on_sequence_stop(self) -> None:
        """用户点击停止序列。"""
        self._stop_sequence_playback()

    def _start_sequence_playback(self, sequence_name: str) -> bool:
        """启动序列播放。

        Returns:
            True 如果成功启动，False 如果序列不存在或无效。
        """
        seq = self._gesture_manager.get_sequence(sequence_name)
        if not seq:
            return False

        steps = seq.get("steps", [])
        if not steps:
            return False

        # 验证所有步骤引用有效
        for step in steps:
            if self._gesture_manager.resolve_gesture(
                step.get("gesture_name", "")
            ) is None:
                return False

        # 停止已有播放
        self._stop_sequence_playback()

        self._sequence_data = {
            "name": sequence_name,
            "steps": [dict(s) for s in steps],
            "loop": seq.get("loop", False),
            "current_step": 0,
            "phase": "duration",
            "phase_start": time.time(),
        }
        self._sequence_playing = True

        # 应用第一步
        self._apply_sequence_step(0)

        # 启动计时器 (30Hz)
        self._sequence_timer = QTimer(self)
        self._sequence_timer.timeout.connect(self._sequence_tick)
        self._sequence_timer.start(33)

        return True

    def _stop_sequence_playback(self) -> None:
        """停止当前序列播放。"""
        if self._sequence_timer is not None:
            self._sequence_timer.stop()
            self._sequence_timer = None
        self._sequence_playing = False
        self._sequence_data = None

    def _sequence_tick(self) -> None:
        """QTimer 回调 — 推进序列状态机。"""
        if not self._sequence_playing or not self._sequence_data:
            return

        data = self._sequence_data
        now = time.time()
        elapsed = now - data["phase_start"]
        step = data["steps"][data["current_step"]]

        if data["phase"] == "duration":
            duration = step.get("duration", 1.0)
            if elapsed >= duration:
                delay = step.get("delay_after", 0.0)
                if delay > 0:
                    data["phase"] = "delay"
                    data["phase_start"] = now
                else:
                    self._advance_sequence_step()
        elif data["phase"] == "delay":
            delay = step.get("delay_after", 0.0)
            if elapsed >= delay:
                self._advance_sequence_step()

    def _advance_sequence_step(self) -> None:
        """推进到序列的下一步。"""
        data = self._sequence_data
        if not data:
            return

        data["current_step"] += 1

        if data["current_step"] >= len(data["steps"]):
            if data.get("loop", False):
                data["current_step"] = 0
                self._apply_sequence_step(0)
                data["phase"] = "duration"
                data["phase_start"] = time.time()
            else:
                self._stop_sequence_playback()
                self._gesture_panel.set_sequences_enabled(True)
            return

        self._apply_sequence_step(data["current_step"])
        data["phase"] = "duration"
        data["phase_start"] = time.time()

    def _apply_sequence_step(self, step_index: int) -> None:
        """应用序列中指定步骤的 DOF 值。"""
        data = self._sequence_data
        if not data or step_index >= len(data["steps"]):
            return

        step = data["steps"][step_index]
        gesture_name = step.get("gesture_name", "")
        dof_values = self._gesture_manager.resolve_gesture(gesture_name)
        if dof_values:
            self._set_all(list(dof_values))


def main() -> None:
    """应用程序入口。"""
    import signal
    rclpy.init()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ControlPanelWindow()
    window.show()

    ros_node = ControlPanelNode()
    window.set_ros_node(ros_node)

    # 启动后立即发布默认目标值
    window.publish_current()

    # SIGINT (Ctrl+C) → 关闭 Qt 窗口 → app.exec_() 返回
    signal.signal(signal.SIGINT, lambda sig, frame: app.quit())

    # ROS spin 线程
    def ros_spin():
        while rclpy.ok():
            rclpy.spin_once(ros_node, timeout_sec=0.01)

    spin_thread = threading.Thread(target=ros_spin, daemon=True)
    spin_thread.start()

    ret = app.exec_()
    ros_node.destroy_node()
    rclpy.shutdown()
    sys.exit(ret)


if __name__ == '__main__':
    main()
