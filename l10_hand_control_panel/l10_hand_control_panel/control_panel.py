#!/usr/bin/env python3
"""
L10 手部控制面板 - 控制 10 个自由度
发布到 /cb_right_hand_control_cmd，值范围 0-255
"""

import tkinter as tk
from tkinter import ttk
import threading
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState


# 10 个自由度定义 (0-255 范围)
# 对应 L10_JOINT_MAP: {0:9, 1:1, 2:0, 3:0, 4:0, 5:6, 6:2, 7:2, 8:2, 9:3, 10:3, 11:3, 12:7, 13:4, 14:4, 15:4, 16:8, 17:5, 18:5, 19:5}
DOF_DEFINITIONS = [
    {"idx": 0, "label": "DOF0 - 拇指根部旋转", "default": 255},
    {"idx": 1, "label": "DOF1 - 拇指侧摆", "default": 255},
    {"idx": 2, "label": "DOF2 - 食指侧摆+弯曲", "default": 255},
    {"idx": 3, "label": "DOF3 - 中指弯曲", "default": 255},
    {"idx": 4, "label": "DOF4 - 无名指侧摆+弯曲", "default": 255},
    {"idx": 5, "label": "DOF5 - 小指侧摆+弯曲", "default": 255},
    {"idx": 6, "label": "DOF6 - 食指根部", "default": 255},
    {"idx": 7, "label": "DOF7 - 无名指根部", "default": 255},
    {"idx": 8, "label": "DOF8 - 小指根部", "default": 255},
    {"idx": 9, "label": "DOF9 - 拇指弯曲", "default": 255},
]


class ControlPanelNode(Node):
    def __init__(self):
        super().__init__('l10_control_panel')
        self.publisher = self.create_publisher(
            JointState,
            '/cb_right_hand_control_cmd',
            10
        )
        self.get_logger().info("L10 Control Panel Node initialized")

    def publish_command(self, positions):
        """发布 10 个位置值 (0-255)"""
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.position = [float(p) for p in positions]
        self.publisher.publish(msg)


class ControlPanelGUI:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("L10 手部控制面板")
        self.root.geometry("450x550")

        # ROS2 节点
        self.ros_node = None

        # 滑块变量
        self.slider_vars = []

        self.setup_gui()
        self.init_ros()

    def setup_gui(self):
        """设置 GUI 布局"""
        # 标题
        title = ttk.Label(self.root, text="L10 手部控制 (0-255)", font=("Arial", 14, "bold"))
        title.pack(pady=10)

        # 滑块框架
        slider_frame = ttk.Frame(self.root, padding="10")
        slider_frame.pack(fill=tk.BOTH, expand=True)

        for i, dof in enumerate(DOF_DEFINITIONS):
            # 标签
            label = ttk.Label(slider_frame, text=dof["label"], width=22)
            label.grid(row=i, column=0, sticky="w", pady=3)

            # 滑块变量
            var = tk.IntVar(value=dof["default"])
            self.slider_vars.append(var)

            # 滑块
            slider = ttk.Scale(
                slider_frame,
                from_=0,
                to=255,
                variable=var,
                orient=tk.HORIZONTAL,
                length=180,
                command=lambda v, idx=i: self.on_slider_change(idx)
            )
            slider.grid(row=i, column=1, padx=5, pady=3)

            # 数值显示
            value_label = ttk.Label(slider_frame, text=str(dof["default"]), width=4)
            value_label.grid(row=i, column=2, pady=3)
            setattr(self, f"value_label_{i}", value_label)

        # 按钮框架
        btn_frame = ttk.Frame(self.root, padding="10")
        btn_frame.pack(fill=tk.X)

        # 张开手
        open_btn = ttk.Button(btn_frame, text="张开手", command=self.open_hand)
        open_btn.pack(side=tk.LEFT, padx=5, expand=True)

        # 握拳
        close_btn = ttk.Button(btn_frame, text="握拳", command=self.close_hand)
        close_btn.pack(side=tk.LEFT, padx=5, expand=True)

        # 复位
        reset_btn = ttk.Button(btn_frame, text="复位", command=self.reset_hand)
        reset_btn.pack(side=tk.LEFT, padx=5, expand=True)

        # 预设手势框架
        preset_frame = ttk.Frame(self.root, padding="10")
        preset_frame.pack(fill=tk.X)

        preset_label = ttk.Label(preset_frame, text="预设手势:")
        preset_label.pack(side=tk.LEFT, padx=5)

        # OK手势
        ok_btn = ttk.Button(preset_frame, text="OK", command=self.preset_ok, width=6)
        ok_btn.pack(side=tk.LEFT, padx=3)

        # 捏取
        pinch_btn = ttk.Button(preset_frame, text="捏取", command=self.preset_pinch, width=6)
        pinch_btn.pack(side=tk.LEFT, padx=3)

        # 指向
        point_btn = ttk.Button(preset_frame, text="指向", command=self.preset_point, width=6)
        point_btn.pack(side=tk.LEFT, padx=3)

    def init_ros(self):
        """初始化 ROS2 节点"""
        rclpy.init()
        self.ros_node = ControlPanelNode()

        # ROS2 spin 线程
        self.ros_thread = threading.Thread(target=self.ros_spin, daemon=True)
        self.ros_thread.start()

    def ros_spin(self):
        """ROS2 spin 线程"""
        while rclpy.ok():
            rclpy.spin_once(self.ros_node, timeout_sec=0.01)

    def on_slider_change(self, idx):
        """滑块值变化回调"""
        value = int(self.slider_vars[idx].get())
        label = getattr(self, f"value_label_{idx}")
        label.config(text=str(value))
        self.publish_current()

    def publish_current(self):
        """发布当前所有滑块值"""
        if self.ros_node:
            positions = [int(var.get()) for var in self.slider_vars]
            self.ros_node.publish_command(positions)

    def open_hand(self):
        """张开手 - 255是张开"""
        for var in self.slider_vars:
            var.set(255)
        self.update_all_labels()
        self.publish_current()

    def close_hand(self):
        """握拳 - 0是握紧"""
        for var in self.slider_vars:
            var.set(0)
        self.update_all_labels()
        self.publish_current()

    def reset_hand(self):
        """复位"""
        for i, var in enumerate(self.slider_vars):
            var.set(DOF_DEFINITIONS[i]["default"])
        self.update_all_labels()
        self.publish_current()

    def preset_ok(self):
        """OK手势 - 拇指和食指接触"""
        values = [100, 150, 200, 0, 0, 0, 200, 0, 0, 100]
        for i, var in enumerate(self.slider_vars):
            var.set(values[i])
        self.update_all_labels()
        self.publish_current()

    def preset_pinch(self):
        """捏取手势"""
        values = [80, 120, 180, 0, 0, 0, 180, 0, 0, 80]
        for i, var in enumerate(self.slider_vars):
            var.set(values[i])
        self.update_all_labels()
        self.publish_current()

    def preset_point(self):
        """指向手势 - 只伸食指"""
        values = [50, 0, 0, 0, 200, 200, 0, 200, 200, 50]
        for i, var in enumerate(self.slider_vars):
            var.set(values[i])
        self.update_all_labels()
        self.publish_current()

    def update_all_labels(self):
        """更新所有数值标签"""
        for i, var in enumerate(self.slider_vars):
            label = getattr(self, f"value_label_{i}")
            label.config(text=str(int(var.get())))

    def run(self):
        """运行 GUI"""
        self.root.mainloop()
        rclpy.shutdown()


def main(args=None):
    gui = ControlPanelGUI()
    gui.run()


if __name__ == '__main__':
    main()
