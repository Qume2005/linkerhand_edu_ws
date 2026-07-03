#!/usr/bin/env python3
"""
石头剪刀布游戏 ROS 节点 + Qt 主入口。

整合 MediaPipe 手势识别、pygame 音频播放、PySide2 GUI、
游戏状态机，通过 ROS gateway 控制灵巧手。
"""

import os

# 修复 OpenCV Qt 插件与系统 Qt5 插件冲突
# OpenCV 自带的 qt/plugins 路径会覆盖系统 Qt5 插件路径，导致 xcb 加载失败
# 必须在 import cv2 / PySide2 之前设置
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms'

import signal
import socket
import sys
import threading
import time

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState

from PySide2.QtCore import QTimer
from PySide2.QtWidgets import QApplication

from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
from l10_right_hand_rock_paper_scissors.game_engine import (
    GameMode, GameState,
)
from l10_right_hand_rock_paper_scissors.game_widget import GameWidget
from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector
from l10_right_hand_rock_paper_scissors.poses import GESTURE_POSES, READY_POSE

# cv2 导入会覆写 QT_QPA_PLATFORM_PLUGIN_PATH，必须在所有 cv2 导入完成后重新设置
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms'


class RockPaperScissorsNode(Node):
    """石头剪刀布游戏 ROS 节点。

    负责:
    - 订阅/发布 gateway 话题
    - smoothstep 插值发送手部姿态
    - 协调 Qt GUI 和 ROS 通信
    """

    INTERP_HZ = 50

    def __init__(self):
        super().__init__('rock_paper_scissors_node')

        # ROS 参数
        self.declare_parameter('camera_id', 0)
        camera_id = self.get_parameter('camera_id').get_parameter_value().integer_value

        # ROS 话题
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self._dof_pub = self.create_publisher(JointState, '/l10_gateway/cmd/dof', qos)
        self._current_dof = [255.0] * 10
        self._dof_sub = self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._current_cb, qos)

        # 插值控制
        self._interp_stop = threading.Event()
        self._interp_thread = None
        self._interp_lock = threading.Lock()

        # 初始化模块
        self._audio = AudioPlayer()
        self._audio.init()

        self._detector = GestureDetector(camera_id=camera_id)

        from l10_right_hand_rock_paper_scissors.game_engine import GameEngine
        self._engine = GameEngine()

        # Qt 应用
        self._app = QApplication(sys.argv)
        self._app.setStyle("Fusion")

        self._widget = GameWidget(self._engine, self._detector, self._audio)
        self._widget.start_game_signal.connect(self._on_start_game)
        self._widget.send_dof_signal.connect(self._on_send_dof)
        self._widget.show()

        # 启动摄像头画面刷新
        self._widget.start_camera_display(fps=30)

        # 首次发送待机姿态
        QTimer.singleShot(1000, lambda: self._send_dof(READY_POSE, 1.0))

        self.get_logger().info("RockPaperScissorsNode 已启动")

    def _current_cb(self, msg: JointState):
        if len(msg.position) >= 10:
            self._current_dof = list(msg.position[:10])

    # === 游戏控制 ===

    def _on_start_game(self):
        """游戏开始 → 触发倒计时。"""
        self._engine.response_strategy = self._widget._get_response_strategy()

        if self._engine.mode == GameMode.COMPETITION:
            self._run_countdown()
        else:
            self._engine.start_round()

    def _run_countdown(self):
        """执行比赛模式倒计时序列。"""
        self._engine.start_round()

        # 发送摇摆预备动作
        self._send_dof(GESTURE_POSES["rock"], 0.3)

        steps = [
            ("get_ready",  700),
            ("rock",       700),
            ("scissors",   700),
            ("paper",      100),
        ]

        def schedule_steps(steps_list, index=0):
            if index >= len(steps_list):
                return
            step_name, delay_ms = steps_list[index]

            def do_step():
                self._engine.on_countdown_step(step_name)
                schedule_steps(steps_list, index + 1)

            QTimer.singleShot(delay_ms, do_step)

        schedule_steps(steps)

    def _on_send_dof(self, dof_values: list, duration: float):
        """UI 请求发送手部姿态。"""
        self._send_dof(dof_values, duration)

    # === 手部姿态控制 ===

    def _send_dof(self, dof_values: list, duration: float = 0.618):
        """通过 smoothstep 插值发送手部姿态到 gateway。"""
        self._stop_interp()

        target = [float(v) for v in dof_values]
        start = list(self._current_dof)

        if start == target:
            self._publish_raw(target)
            return

        self._interp_stop.clear()
        t = threading.Thread(
            target=self._interp_loop,
            args=(start, target, duration),
            daemon=True,
        )
        with self._interp_lock:
            self._interp_thread = t
        t.start()

    def _stop_interp(self):
        self._interp_stop.set()
        with self._interp_lock:
            t = self._interp_thread
        if t is not None and t.is_alive():
            t.join(timeout=1.0)

    def _interp_loop(self, start: list, target: list, duration: float):
        """50Hz smoothstep 插值。"""
        dt = 1.0 / self.INTERP_HZ
        steps = max(1, int(duration * self.INTERP_HZ))

        for i in range(1, steps + 1):
            if self._interp_stop.is_set():
                return
            t = i / steps
            progress = t * t * (3.0 - 2.0 * t)
            interp = [
                start[j] + (target[j] - start[j]) * progress
                for j in range(10)
            ]
            self._publish_raw(interp)
            if i < steps:
                time.sleep(dt)

    def _publish_raw(self, values: list):
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.position = [float(v) for v in values]
        self._dof_pub.publish(msg)
        self._current_dof = list(values)

    # === 生命周期 ===

    def run(self) -> int:
        """启动 Qt 事件循环，阻塞直到窗口关闭。"""
        shutdown_event = threading.Event()

        # socketpair 信号桥接
        sig_wakeup_r, sig_wakeup_w = socket.socketpair()
        sig_wakeup_w.setblocking(False)
        signal.set_wakeup_fd(sig_wakeup_w.fileno())

        def _on_signal():
            sig_wakeup_r.recv(1)
            shutdown_event.set()
            self._widget.close()

        from PySide2.QtCore import QSocketNotifier
        sig_notifier = QSocketNotifier(
            sig_wakeup_r.fileno(), QSocketNotifier.Read)
        sig_notifier.activated.connect(_on_signal)
        signal.signal(signal.SIGINT, lambda sig, frame: None)

        # ROS spin 守护线程
        def ros_spin():
            while not shutdown_event.is_set():
                try:
                    rclpy.spin_once(self, timeout_sec=0.01)
                except Exception:
                    break

        spin_thread = threading.Thread(target=ros_spin, daemon=True)
        spin_thread.start()

        ret = self._app.exec_()

        # 清理
        shutdown_event.set()
        self._detector.stop()
        self._audio.cleanup()
        self._stop_interp()
        self._widget.stop_camera_display()
        spin_thread.join(timeout=1.0)
        self.destroy_node()

        return ret


def main(args=None):
    rclpy.init(args=args)
    node = RockPaperScissorsNode()
    ret = node.run()
    rclpy.try_shutdown()
    sys.exit(ret)


if __name__ == '__main__':
    main()
