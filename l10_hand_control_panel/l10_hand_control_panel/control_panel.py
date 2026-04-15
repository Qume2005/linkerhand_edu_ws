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

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray

from PySide2.QtCore import Qt, Signal, QRectF, QPointF
from PySide2.QtGui import QPainter, QPen, QBrush, QColor, QPolygonF, QFont
from PySide2.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QPushButton, QFrame, QSizePolicy, QSplitter,
)

from l10_hand_control_panel.skeleton_widget import HandModelWidget


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
    """自定义双指示器滑块: 灰色=当前状态(只读), 白色=目标(可拖动)"""

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


class ControlPanelNode(Node):
    """ROS2 节点 — 通过 l10_hand_gateway 通信"""

    def __init__(self):
        super().__init__('l10_control_panel')

        # 发布器: 命令 → 网关
        self.dof_pub = self.create_publisher(
            JointState, '/l10_gateway/cmd/dof', 10
        )
        self.camera_pub = self.create_publisher(
            Float32MultiArray, '/l10_gateway/cmd/camera', 10
        )

        # 订阅: 网关广播的当前/目标状态
        self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._current_cb, 10
        )
        self.create_subscription(
            JointState, '/l10_gateway/target/dof', self._target_cb, 10
        )

        # 外部回调 (由 ControlPanelWindow 设置)
        self.on_current_state = None
        self.on_target_state = None

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


class _StateSignal(QWidget):
    """用于跨线程传递状态更新的信号中转"""
    current_received = Signal(list)
    target_received = Signal(list)

    def __init__(self):
        super().__init__()


class ControlPanelWindow(QWidget):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self._state_signal = _StateSignal()
        self._state_signal.current_received.connect(self._apply_current_state)
        self._state_signal.target_received.connect(self._apply_target_state)
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
        self.setFixedSize(920, 540)

        self.ros_node = None
        self.sliders = []
        self.val_labels = []
        self._syncing = False

        self._build_ui()

    def _build_ui(self):
        outer = QHBoxLayout(self)
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

        # 操作按钮
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        for text, fn in [("张开手", self.open_hand), ("握拳", self.close_hand), ("复位", self.reset_hand)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            btn_row.addWidget(b)
        left.addLayout(btn_row)

        # 预设手势
        preset_row = QHBoxLayout()
        preset_row.setSpacing(6)
        plbl = QLabel("预设手势:")
        plbl.setStyleSheet(f"color: {COLOR_TEXT_DIM};")
        preset_row.addWidget(plbl)
        for text, fn in [("OK", self.preset_ok), ("捏取", self.preset_pinch), ("指向", self.preset_point)]:
            b = QPushButton(text)
            b.setFixedWidth(60)
            b.clicked.connect(fn)
            preset_row.addWidget(b)
        preset_row.addStretch()
        left.addLayout(preset_row)

        left.addStretch()
        outer.addLayout(left)

        # ========== 竖线分隔 ==========
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("color: #444444;")
        outer.addWidget(sep)

        # ========== 右侧: 骨架交互 ==========
        self.skeleton = HandModelWidget()
        self.skeleton.set_dof_values([d["default"] for d in DOF_DEFINITIONS])
        self.skeleton.on_dof_changed = self._on_skeleton_drag
        self.skeleton.on_camera_changed = self._on_camera_changed
        self.skeleton.setMinimumWidth(350)
        outer.addWidget(self.skeleton, stretch=1)

    def _dim_label(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 11px;")
        return lbl

    # ---- ROS 接口 ----

    def set_ros_node(self, node):
        self.ros_node = node
        node.on_current_state = self._ros_current_update
        node.on_target_state = self._ros_target_update

    def _ros_current_update(self, values):
        """从 ROS spin 线程调用, 通过信号传递到 Qt 主线程"""
        self._state_signal.current_received.emit(values)

    def _ros_target_update(self, values):
        """从 ROS spin 线程调用, 通过信号传递到 Qt 主线程"""
        self._state_signal.target_received.emit(values)

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
        self._set_all([255] * 10)

    def close_hand(self):
        self._set_all([0] * 10)

    def reset_hand(self):
        self._set_all([d["default"] for d in DOF_DEFINITIONS])

    def preset_ok(self):
        self._set_all([100, 150, 200, 0, 0, 0, 200, 0, 0, 100])

    def preset_pinch(self):
        self._set_all([80, 120, 180, 0, 0, 0, 180, 0, 0, 80])

    def preset_point(self):
        self._set_all([50, 0, 0, 0, 200, 200, 0, 200, 200, 50])


def main(args=None):
    rclpy.init()

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ControlPanelWindow()
    window.show()

    ros_node = ControlPanelNode()
    window.set_ros_node(ros_node)

    # 启动后立即发布默认目标值
    window.publish_current()

    # ROS spin 线程
    def ros_spin():
        while rclpy.ok():
            rclpy.spin_once(ros_node, timeout_sec=0.01)

    spin_thread = threading.Thread(target=ros_spin, daemon=True)
    spin_thread.start()

    ret = app.exec_()
    rclpy.shutdown()
    sys.exit(ret)


if __name__ == '__main__':
    main()
