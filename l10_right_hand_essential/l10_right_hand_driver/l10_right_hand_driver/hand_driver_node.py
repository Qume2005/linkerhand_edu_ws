#!/usr/bin/env python3
"""
L10 Right Hand Hardware Driver Node
通过 CAN 总线直接驱动真实 L10 右手（使用内置 CAN 驱动，不依赖 linkerhand-ros2-sdk）
发布/订阅话题与 l10_right_hand_mujoco_sim 完全一致，可直接替换

发布:
  /cb_right_hand_state              JointState (10 DOF 0-255)
  /cb_right_hand_info               String (JSON)
  /cb_right_hand_force              Float32MultiArray
  /cb_right_hand_matrix_touch       String (JSON)
  /cb_right_hand_matrix_touch_pc    PointCloud2
  /cb_right_hand_matrix_touch_mass  String (JSON)

订阅:
  /cb_right_hand_control_cmd        JointState (10 DOF 0-255)
  /cb_hand_setting_cmd              String (JSON)
"""

import json
import threading
import time

import numpy as np
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState, PointCloud2, PointField
from std_msgs.msg import Float32MultiArray, String, Header

from l10_right_hand_driver.linkerhand.l10_can import LinkerHandL10Can
from l10_right_hand_driver.linkerhand.load_write_yaml import LoadWriteYaml

# L10 右手 10 DOF 关节名（与 SDK 一致）
L10_FINGER_ORDER = [
    "thumb_cmc_pitch", "thumb_cmc_yaw",
    "index_mcp_pitch", "middle_mcp_pitch",
    "ring_mcp_pitch", "pinky_mcp_pitch",
    "index_mcp_roll", "ring_mcp_roll",
    "pinky_mcp_roll", "thumb_cmc_roll",
]

# CAN ID: 右手 = 0x27
RIGHT_HAND_CAN_ID = 0x27


class L10RightHandDriver(Node):
    def __init__(self):
        super().__init__('l10_right_hand_driver')

        # ---- ROS2 参数 ----
        self.declare_parameter('can_port', 'can0')
        self.declare_parameter('is_touch', True)
        self.declare_parameter('topic_hz', 30)

        can_port = self.get_parameter('can_port').get_parameter_value().string_value
        self.is_touch = self.get_parameter('is_touch').get_parameter_value().bool_value
        topic_hz = self.get_parameter('topic_hz').get_parameter_value().integer_value

        self.get_logger().info(
            f"L10 Right Hand Driver starting... can={can_port} "
            f"is_touch={self.is_touch} hz={topic_hz}"
        )

        # ---- 初始化 CAN 驱动 ----
        yaml_loader = LoadWriteYaml()
        try:
            self.hand = LinkerHandL10Can(
                can_id=RIGHT_HAND_CAN_ID,
                can_channel=can_port,
                yaml=yaml_loader,
            )
        except Exception as e:
            self.get_logger().fatal(
                f"CAN 初始化失败 ({can_port}): {e}\n"
                "请检查 USB-CAN 适配器是否已连接。"
            )
            raise SystemExit(1)

        # 读取触摸传感器类型
        self.touch_type = self.hand.get_touch_type()
        if self.touch_type == -1:
            self.is_touch = False
            self.get_logger().warn("No touch sensors detected")

        # 读取固件版本和序列号
        self.embedded_version = self.hand.get_version()
        self.serial_number = self.hand.get_serial_number()
        self.get_logger().info(
            f"Hardware ready: version={self.embedded_version} sn={self.serial_number}"
        )

        # ---- 命令缓存 ----
        self._cmd_lock = threading.Lock()
        self._pending_pose = None

        # ---- 触觉数据缓存 ----
        self.matrix_dic = {
            "stamp": {"secs": 0, "nsecs": 0},
            "thumb_matrix": [[-1] * 6 for _ in range(12)],
            "index_matrix": [[-1] * 6 for _ in range(12)],
            "middle_matrix": [[-1] * 6 for _ in range(12)],
            "ring_matrix": [[-1] * 6 for _ in range(12)],
            "little_matrix": [[-1] * 6 for _ in range(12)],
        }
        self.matrix_mass_dic = {
            "stamp": {"secs": 0, "nsecs": 0},
            "unit": "g",
            "thumb_mass": [-1],
            "index_mass": [-1],
            "middle_mass": [-1],
            "ring_mass": [-1],
            "little_mass": [-1],
        }

        # ---- Publisher ----
        self.hand_state_pub = self.create_publisher(
            JointState, '/cb_right_hand_state', 10)
        self.hand_info_pub = self.create_publisher(
            String, '/cb_right_hand_info', 10)

        if self.is_touch:
            if self.touch_type > 1:
                self.matrix_touch_pub = self.create_publisher(
                    String, '/cb_right_hand_matrix_touch', 10)
                self.matrix_touch_pc_pub = self.create_publisher(
                    PointCloud2, '/cb_right_hand_matrix_touch_pc', 10)
                self.matrix_touch_mass_pub = self.create_publisher(
                    String, '/cb_right_hand_matrix_touch_mass', 10)
            else:
                self.force_pub = self.create_publisher(
                    Float32MultiArray, '/cb_right_hand_force', 10)

        # ---- Subscriber ----
        self.create_subscription(
            JointState, '/cb_right_hand_control_cmd',
            self._hand_control_cb, 10)
        self.create_subscription(
            String, '/cb_hand_setting_cmd',
            self._hand_setting_cb, 10)

        # ---- 初始化手部到默认姿态 ----
        self.hand.set_speed(speed=[255] * 10)
        time.sleep(0.1)
        self.hand.set_torque(torque=[255] * 10)
        time.sleep(0.1)
        self.hand.set_joint_positions([255, 200, 255, 255, 255, 255, 180, 180, 180, 41])
        time.sleep(0.1)

        # ---- 定时器 ----
        time.sleep(2)
        self._timer = self.create_timer(1.0 / topic_hz, self._run)
        self.get_logger().info("L10 Right Hand Driver running.")

    # ================================================================
    # 命令回调
    # ================================================================

    def _hand_control_cb(self, msg):
        """缓存手指位置命令"""
        if len(msg.position) < 10:
            return
        with self._cmd_lock:
            self._pending_pose = [int(v) for v in msg.position[:10]]

    def _hand_setting_cb(self, msg):
        """处理设置命令"""
        try:
            data = json.loads(msg.data)
            cmd = data.get("setting_cmd", "")
            params = data.get("params", {})

            if cmd == "set_speed":
                speed = params.get("speed", [])
                if isinstance(speed, list) and len(speed) == 10:
                    self.hand.set_speed(speed)
                    self.get_logger().info(f"Speed set: {speed}")

            elif cmd == "set_max_torque_limits":
                torque = params.get("torque", [])
                if isinstance(torque, list):
                    while len(torque) < 10:
                        torque.append(255)
                    self.hand.set_torque(torque)
                    self.get_logger().info(f"Torque set: {torque}")

            elif cmd == "clear_faults":
                self.get_logger().info("Faults clear: no-op in L10")

            elif cmd == "set_electric_current":
                self.get_logger().info("set_electric_current: no-op for L10")

            else:
                self.get_logger().warn(f"Unknown setting_cmd: {cmd}")

        except (json.JSONDecodeError, KeyError) as e:
            self.get_logger().error(f"Error in setting_cb: {e}")

    # ================================================================
    # 主循环
    # ================================================================

    def _run(self):
        # 1. 发送缓存的命令
        with self._cmd_lock:
            pose = self._pending_pose
            self._pending_pose = None

        if pose is not None:
            self.hand.set_joint_positions(pose)

        # 2. 读取并发布关节状态
        now = self.get_clock().now().to_msg()
        try:
            state = self.hand.get_current_pub_status()
            if state and len(state) >= 10:
                js = JointState()
                js.header.stamp = now
                js.name = list(L10_FINGER_ORDER)
                js.position = [float(v) for v in state[:10]]
                js.velocity = [0.0] * 10
                js.effort = [0.0] * 10
                self.hand_state_pub.publish(js)
        except Exception as e:
            self.get_logger().error(f"Error reading state: {e}")

        # 3. 发布手部信息
        if self.hand_info_pub.get_subscription_count() > 0:
            self._publish_hand_info(now)

        # 4. 触觉数据
        if self.is_touch and self.touch_type > 1:
            self._read_and_publish_touch(now)

    # ================================================================
    # 手部信息发布
    # ================================================================

    def _publish_hand_info(self, stamp):
        try:
            speed = self.hand.get_speed()
        except Exception:
            speed = [255] * 10
        try:
            fault = self.hand.get_fault()
        except Exception:
            fault = [0] * 10
        try:
            temp = self.hand.get_temperature()
        except Exception:
            temp = [25] * 10
        try:
            torque = self.hand.get_torque()
        except Exception:
            torque = [255] * 10

        info = {
            "version": self.embedded_version if self.embedded_version else [],
            "hand_joint": "L10",
            "speed": speed,
            "current": [0] * 10,
            "fault": fault,
            "motor_temperature": temp,
            "torque": torque,
            "is_touch": self.is_touch,
            "touch_type": self.touch_type if self.is_touch else -1,
            "finger_order": list(L10_FINGER_ORDER),
        }
        msg = String()
        msg.data = json.dumps(info)
        self.hand_info_pub.publish(msg)

    # ================================================================
    # 触觉数据
    # ================================================================

    def _read_and_publish_touch(self, stamp):
        try:
            self.matrix_dic["thumb_matrix"] = (
                self.hand.get_thumb_matrix_touch(sleep_time=0.003).tolist()
            )
            self.matrix_dic["index_matrix"] = (
                self.hand.get_index_matrix_touch(sleep_time=0.004).tolist()
            )
            self.matrix_dic["middle_matrix"] = (
                self.hand.get_middle_matrix_touch(sleep_time=0.003).tolist()
            )
            self.matrix_dic["ring_matrix"] = (
                self.hand.get_ring_matrix_touch(sleep_time=0.004).tolist()
            )
            self.matrix_dic["little_matrix"] = (
                self.hand.get_little_matrix_touch(sleep_time=0.004).tolist()
            )
        except Exception as e:
            self.get_logger().error(f"Error reading touch: {e}")
            return

        sec = stamp.sec if hasattr(stamp, 'sec') else 0
        nanosec = stamp.nanosec if hasattr(stamp, 'nanosec') else 0
        self.matrix_dic["stamp"]["secs"] = sec
        self.matrix_dic["stamp"]["nsecs"] = nanosec

        # 发布矩阵 JSON
        mat_msg = String()
        mat_msg.data = json.dumps(self.matrix_dic)
        self.matrix_touch_pub.publish(mat_msg)

        # 发布每指质量和
        self.matrix_mass_dic["stamp"]["secs"] = sec
        self.matrix_mass_dic["stamp"]["nsecs"] = nanosec
        for finger in ["thumb", "index", "middle", "ring", "little"]:
            total = sum(sum(row) for row in self.matrix_dic[f"{finger}_matrix"])
            self.matrix_mass_dic[f"{finger}_mass"] = [total]

        mass_msg = String()
        mass_msg.data = json.dumps(self.matrix_mass_dic)
        self.matrix_touch_mass_pub.publish(mass_msg)

        # 发布 PointCloud2
        self._publish_matrix_pc(stamp)

    def _publish_matrix_pc(self, stamp):
        """将 5 个 12x6 矩阵打包为 PointCloud2"""
        flat_vals = []
        for finger in ["thumb", "index", "middle", "ring", "little"]:
            for row in self.matrix_dic[f"{finger}_matrix"]:
                for v in row:
                    flat_vals.append(max(0, min(255, int(v))))

        data = np.array(flat_vals, dtype=np.uint8)

        pc = PointCloud2()
        pc.header = Header(stamp=stamp, frame_id='')
        pc.height = 1
        pc.width = data.size

        field = PointField()
        field.name = "val"
        field.offset = 0
        field.datatype = PointField.UINT8
        field.count = 1
        pc.fields = [field]

        pc.is_bigendian = False
        pc.point_step = 1
        pc.row_step = pc.point_step * pc.width
        pc.data = data.tobytes()

        self.matrix_touch_pc_pub.publish(pc)

    # ================================================================
    # 生命周期
    # ================================================================

    def destroy(self):
        self.get_logger().info("Shutting down L10 Right Hand Driver...")
        try:
            self.hand.close_can_interface()
        except Exception:
            pass
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = L10RightHandDriver()
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, SystemExit):
        pass
    finally:
        rclpy.shutdown()


if __name__ == '__main__':
    main()
