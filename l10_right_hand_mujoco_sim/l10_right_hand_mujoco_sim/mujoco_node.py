"""
L10 Right Hand MuJoCo Simulation Node
简化版：只支持 L10 右手
"""

import os
import time
import threading

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseArray, Pose
from std_msgs.msg import Header
import numpy as np
import mujoco
import mujoco.viewer


# ============================================================================
# L10 右手关节映射配置 (硬编码)
# ============================================================================

L10_JOINT_MAP = {
    0: 9,  1: 1,   2: 0,   3: 0,  4: 0,  5: 6,
    6: 2, 7: 2,   8: 2,   9: 3,  10: 3, 11: 3,
    12: 7, 13: 4, 14: 4,  15: 4, 16: 8, 17: 5,
    18: 5, 19: 5
}

# L10 右手关节范围
L10_R_MIN = [0, 0, 0, 0, 0, 0, -0.26, 0, 0, -0.52]
L10_R_MAX = [0.75, 1.43, 1.62, 1.62, 1.62, 1.62, 0, 0.13, 0.26, 1.01]
L10_R_DIRECT = [-1, -1, -1, -1, -1, -1, -1, 0, 0, -1]


def scale_value(original_value, a_min, a_max, b_min, b_max):
    """线性映射函数"""
    return (original_value - a_min) * (b_max - b_min) / (a_max - a_min) + b_min


def is_within_range(value, min_value, max_value):
    """限制值在范围内"""
    return min(max_value, max(min_value, value))


def range_to_arc_l10_right(position_range):
    """将 0-255 的位置值转换为 L10 右手的弧度值"""
    hand_arc = [0.0] * 10
    for i in range(10):
        val = is_within_range(position_range[i], 0, 255)
        if L10_R_DIRECT[i] == -1:
            hand_arc[i] = scale_value(val, 0, 255, L10_R_MAX[i], L10_R_MIN[i])
        else:
            hand_arc[i] = scale_value(val, 0, 255, L10_R_MIN[i], L10_R_MAX[i])
    return hand_arc


# ============================================================================
# MuJoCo ROS2 节点
# ============================================================================

class L10RightMujocoNode(Node):
    def __init__(self):
        super().__init__('l10_right_mujoco_node')

        # 声明参数
        self.declare_parameter("topic_hz", 30)
        self.declare_parameter("is_touch", True)

        self.topic_hz = self.get_parameter('topic_hz').get_parameter_value().integer_value
        self.is_touch = self.get_parameter('is_touch').get_parameter_value().bool_value

        self.get_logger().info(f"L10 Right Hand MuJoCo Simulation starting...")
        self.get_logger().info(f"  topic_hz: {self.topic_hz}")
        self.get_logger().info(f"  is_touch: {self.is_touch}")

        # 订阅控制命令话题
        self.create_subscription(
            JointState,
            "/cb_right_hand_control_cmd",
            self.hand_cb,
            10
        )

        # 发布关节状态
        self.joint_pub = self.create_publisher(JointState, "/joint_states", 10)

        # 发布 body 位置（用于骨骼可视化）
        self.body_pos_pub = self.create_publisher(PoseArray, "/skeleton_body_positions", 10)

        # 加载 MuJoCo 模型
        xml_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)),
            "urdf/linker_hand_l10_right/linker_hand_l10_right.xml"
        )
        self.get_logger().info(f"Loading model from: {xml_path}")

        self.model = mujoco.MjModel.from_xml_path(xml_path)
        self.model.dof_damping[:] = 0.8
        self.data = mujoco.MjData(self.model)

        self.get_logger().info(f"MuJoCo version: {mujoco.mj_versionString()}")

        self.data.qpos[:] = 0
        self.data.qvel[:] = 0
        self.model.opt.disableflags = 1
        mujoco.mj_forward(self.model, self.data)

        # 打印关节信息
        joint_count = self.model.nu

        # 关节名称列表
        self.joint_names = []
        for i in range(self.model.njnt):
            joint_name = self.model.joint(i).name
            self.joint_names.append(joint_name)
            self.get_logger().info(f"  Joint {i}: {joint_name}")

        self.ctrl_values = np.zeros(joint_count)
        self.ctrl_ranges = self.model.actuator_ctrlrange.copy()

        # 启动 MuJoCo 仿真线程
        sim_thread = threading.Thread(target=self.mujoco_thread, daemon=True)
        sim_thread.start()

    def mujoco_thread(self):
        """MuJoCo 仿真线程"""
        pub_rate = 0.03  # 30Hz 发布关节状态
        last_pub_time = time.time()

        with mujoco.viewer.launch_passive(self.model, self.data) as viewer:
            self.get_logger().info("MuJoCo viewer running...")
            while viewer.is_running():
                self.data.ctrl[:] = self.ctrl_values
                mujoco.mj_step(self.model, self.data)
                viewer.sync()

                # 发布关节状态
                current_time = time.time()
                if current_time - last_pub_time >= pub_rate:
                    self.publish_joint_states()
                    last_pub_time = current_time

                time.sleep(0.001)

    def publish_joint_states(self):
        """发布当前关节状态和 body 位置"""
        # 发布关节角度
        msg = JointState()
        msg.header.stamp = self.get_clock().now().to_msg()
        msg.name = self.joint_names
        msg.position = self.data.qpos.tolist()
        msg.velocity = self.data.qvel.tolist()
        self.joint_pub.publish(msg)

        # 发布 body 位置（用于骨骼可视化）
        self.publish_body_positions()

    def publish_body_positions(self):
        """发布所有 body 的 3D 位置"""
        pose_array = PoseArray()
        pose_array.header.stamp = self.get_clock().now().to_msg()
        pose_array.header.frame_id = "world"

        # 遍历所有 body， 发布位置
        for i in range(self.model.nbody):
            body_name = self.model.body(i).name
            pos = self.data.xpos[i]  # 获取 body 的全局位置

            pose = Pose()
            pose.position.x = pos[0]
            pose.position.y = pos[1]
            pose.position.z = pos[2]
            pose.orientation.w = 1.0  # 单位四元数
            pose_array.poses.append(pose)

        self.body_pos_pub.publish(pose_array)

    def hand_cb(self, msg):
        """处理控制命令回调"""
        try:
            position = msg.position
            if len(position) >= 10:
                # 转换为弧度值
                arc_values = range_to_arc_l10_right(position)
                # 映射到 MuJoCo 控制值
                self.ctrl_values[:] = self.map_position_array(arc_values, L10_JOINT_MAP)
        except Exception as e:
            self.get_logger().error(f"Error in hand_cb: {e}")

    def map_position_array(self, position, joint_map):
        """将位置数组映射到 MuJoCo 控制数组"""
        max_idx = max(joint_map.keys()) + 1
        mapped_array = [0.0] * max_idx

        for target_idx, source_idx in joint_map.items():
            if source_idx < len(position):
                mapped_array[target_idx] = position[source_idx]

        return mapped_array


def main(args=None):
    rclpy.init(args=args)
    node = L10RightMujocoNode()
    rclpy.spin(node)
    rclpy.shutdown()


if __name__ == '__main__':
    main()
