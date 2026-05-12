#!/usr/bin/env python3
"""
L10 灵巧手 LLM 控制节点。
通过大模型自然语言对话控制灵巧手 10-DOF。
"""

import math
import os
import signal
import socket
import sys
import threading
import time

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

    DEFAULT_DURATION = 0.618
    INTERP_HZ = 50  # 插值发布频率

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

        # 插值控制
        self._interp_stop = threading.Event()
        self._interp_thread = None
        self._interp_lock = threading.Lock()

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

    def publish_dof(self, dof_values: list, duration: float = 0.0):
        """发布 10 个 DOF 值 (0-255) 到 gateway 命令话题。

        duration > 0 时执行平滑插值过渡，否则直接发送。
        """
        if duration <= 0:
            duration = self.DEFAULT_DURATION

        # 停止上一次插值
        self._stop_interp()

        target = [float(v) for v in dof_values]
        # 快照当前 DOF 作为插值起点
        start = list(self._current_dof)

        # 起终点相同则直接发送
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
        self.get_logger().info(
            f"开始插值: {start} → {target}, {duration:.3f}s")

    def _stop_interp(self):
        """停止正在进行的插值线程。"""
        self._interp_stop.set()
        with self._interp_lock:
            t = self._interp_thread
        if t is not None and t.is_alive():
            t.join(timeout=1.0)

    def _interp_loop(self, start: list, target: list, duration: float):
        """在后台线程中执行平滑插值。"""
        dt = 1.0 / self.INTERP_HZ
        steps = max(1, int(duration * self.INTERP_HZ))

        for i in range(1, steps + 1):
            if self._interp_stop.is_set():
                return
            t = i / steps
            # smoothstep 缓入缓出
            progress = t * t * (3.0 - 2.0 * t)
            interp = [
                start[j] + (target[j] - start[j]) * progress
                for j in range(10)
            ]
            self._publish_raw(interp)
            # 最后一步不 sleep
            if i < steps:
                time.sleep(dt)

        self.get_logger().info(f"插值完成: {target}")

    def _publish_raw(self, values: list):
        """直接发布 DOF 值。"""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.position = [float(v) for v in values]
        self._dof_pub.publish(msg)
        self._current_dof = list(values)

    def queue_actions(self, actions: list, loop: bool = False):
        """顺序执行一组动作队列。

        actions: list of dict, 每项含 "dof"(10 值), "duration"(秒), "pause"(秒)
        loop: 是否循环播放
        """
        self._stop_interp()
        if not actions:
            return

        self._interp_stop.clear()
        t = threading.Thread(
            target=self._queue_loop,
            args=(actions, loop),
            daemon=True,
        )
        with self._interp_lock:
            self._interp_thread = t
        t.start()
        self.get_logger().info(
            f"开始动作队列: {len(actions)} 步, 循环={loop}")

    def _queue_loop(self, actions: list, loop: bool):
        """在后台线程中顺序执行动作队列。

        使用内部追踪的 last_pos 作为每步起点，不依赖硬件反馈，
        避免反馈延迟导致步骤间跳变。
        """
        # 循环模式下，自动补齐最后一步的 pause，避免衔接处突兀
        if loop and actions:
            last_pause = actions[-1].get("pause", 0.0)
            if last_pause <= 0:
                # 取其余步骤中非零 pause 的中位数，兜底 0.3s
                pauses = [s.get("pause", 0.0) for s in actions[:-1] if s.get("pause", 0) > 0]
                fallback = sorted(pauses)[len(pauses) // 2] if pauses else 0.3
                actions[-1]["pause"] = fallback
                self.get_logger().info(
                    f"循环模式: 自动为最后一步补 pause={fallback:.2f}s")

        last_pos = list(self._current_dof)

        while True:
            for step in actions:
                if self._interp_stop.is_set():
                    return

                target = [float(v) for v in step["dof"]]
                duration = step.get("duration", self.DEFAULT_DURATION)
                pause = step.get("pause", 0.0)

                # 插值过渡到目标姿势
                if last_pos != target:
                    num_steps = max(1, int(duration * self.INTERP_HZ))
                    # 用目标时间驱动，避免 sleep 累积误差
                    next_tick = time.monotonic()
                    dt = 1.0 / self.INTERP_HZ

                    for i in range(1, num_steps + 1):
                        if self._interp_stop.is_set():
                            return
                        t = i / num_steps
                        progress = t * t * (3.0 - 2.0 * t)
                        interp = [
                            last_pos[j] + (target[j] - last_pos[j]) * progress
                            for j in range(10)
                        ]
                        self._publish_raw(interp)
                        if i < num_steps:
                            next_tick += dt
                            now = time.monotonic()
                            sleep_time = next_tick - now
                            if sleep_time > 0:
                                time.sleep(sleep_time)

                last_pos = list(target)

                # 保持姿势
                if pause > 0 and not self._interp_stop.is_set():
                    end_time = time.monotonic() + pause
                    while time.monotonic() < end_time:
                        if self._interp_stop.is_set():
                            return
                        time.sleep(0.02)

            if not loop:
                break

        self.get_logger().info("动作队列执行完成")


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
