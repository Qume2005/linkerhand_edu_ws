#!/usr/bin/env python3
"""
L10 灵巧手 LLM 控制节点。
通过大模型自然语言对话控制灵巧手 10-DOF。
"""

import os
import signal
import socket
import sys
import threading

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState

from PySide2.QtCore import QSocketNotifier, QTimer
from PySide2.QtWidgets import QApplication

from l10_right_hand_llm.chat_widget import ChatWindow
from l10_right_hand_llm.settings_dialog import SettingsDialog


class HandLLMControlNode(Node):
    """ROS 节点: 发布 DOF 命令到 gateway, 订阅当前状态。"""

    def __init__(self):
        super().__init__('hand_llm_control')
        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)
        self._dof_pub = self.create_publisher(
            JointState, '/l10_gateway/cmd/dof', qos)
        self._current_dof = [255.0] * 10
        self._target_dof = [255.0] * 10
        self._dof_sub = self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._current_cb, qos)
        self._target_sub = self.create_subscription(
            JointState, '/l10_gateway/target/dof', self._target_cb, qos)
        self.get_logger().info("HandLLMControlNode 已启动")

    def _current_cb(self, msg: JointState):
        if len(msg.position) >= 10:
            self._current_dof = list(msg.position[:10])

    def _target_cb(self, msg: JointState):
        if len(msg.position) >= 10:
            self._target_dof = list(msg.position[:10])

    def get_current_dof(self) -> list:
        return [int(round(v)) for v in self._current_dof]

    def get_target_dof(self) -> list:
        return [int(round(v)) for v in self._target_dof]

    def publish_dof(self, dof_values: list):
        """发布 10 个 DOF 值 (0-255) 到 gateway 命令话题。"""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.position = [float(v) for v in dof_values]
        self._dof_pub.publish(msg)
        self._current_dof = [float(v) for v in dof_values]
        self.get_logger().info(f"已发布 DOF: {dof_values}")


def main(args=None):
    rclpy.init(args=args)

    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    window = ChatWindow()
    window.show()

    ros_node = HandLLMControlNode()
    window.set_ros_node(ros_node)

    # 首次启动检查 API key
    if not SettingsDialog.has_api_key():
        QTimer.singleShot(500, window._open_settings)

    # 用 Event 协调 spin 线程退出
    shutdown_event = threading.Event()

    # 将 SIGINT 接入 Qt 事件循环: socket pair + QSocketNotifier
    sig_wakeup_r, sig_wakeup_w = socket.socketpair()
    sig_wakeup_w.setblocking(False)
    signal.set_wakeup_fd(sig_wakeup_w.fileno())

    def _on_signal():
        # 读取信号编号并关闭窗口
        sig_wakeup_r.recv(1)
        shutdown_event.set()
        window.close()

    sig_notifier = QSocketNotifier(
        sig_wakeup_r.fileno(), QSocketNotifier.Read)
    sig_notifier.activated.connect(_on_signal)

    signal.signal(signal.SIGINT, lambda sig, frame: None)  # 由 wakeup fd 处理

    # ROS spin 守护线程
    def ros_spin():
        while not shutdown_event.is_set():
            try:
                rclpy.spin_once(ros_node, timeout_sec=0.01)
            except Exception:
                break

    spin_thread = threading.Thread(target=ros_spin, daemon=True)
    spin_thread.start()

    ret = app.exec_()
    shutdown_event.set()
    spin_thread.join(timeout=1.0)
    ros_node.destroy_node()
    rclpy.try_shutdown()
    sys.exit(ret)


if __name__ == '__main__':
    main()
