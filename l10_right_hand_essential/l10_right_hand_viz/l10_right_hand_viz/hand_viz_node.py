#!/usr/bin/env python3
"""
L10 Right Hand Viz Node
从网关订阅 DOF 状态，转换为 20 关节角度发布 /joint_states
配合 robot_state_publisher 在 RViz2 中显示带网格的手部模型
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState

from hand_forward_kinematics.kinematics import range_to_arc_l10_right, expand_to_20_joints

# MuJoCo XML 中的 20 个关节名 (按 qpos 索引顺序)
JOINT_NAMES = [
    "thumb_joint0", "thumb_joint1", "thumb_joint2", "thumb_joint3", "thumb_joint4",
    "index_joint0", "index_joint1", "index_joint2", "index_joint3",
    "middle_joint0", "middle_joint1", "middle_joint2",
    "ring_joint0", "ring_joint1", "ring_joint2", "ring_joint3",
    "little_joint0", "little_joint1", "little_joint2", "little_joint3",
]


class HandVizNode(Node):
    def __init__(self):
        super().__init__('hand_viz_node')

        self.joint_pub = self.create_publisher(JointState, '/joint_states', 10)

        self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._dof_cb, 10)

        self.get_logger().info("Hand Viz Node initialized (model visualization via gateway)")

    def _dof_cb(self, msg):
        if len(msg.position) < 10:
            return

        # 10 DOF (0-255) → 弧度 → 20 关节
        arc = range_to_arc_l10_right(list(msg.position[:10]))
        joints = expand_to_20_joints(arc)

        # 发布 /joint_states
        js = JointState()
        js.header.stamp = self.get_clock().now().to_msg()
        js.name = JOINT_NAMES
        js.position = [float(j) for j in joints]
        self.joint_pub.publish(js)


def main(args=None):
    rclpy.init(args=args)
    node = HandVizNode()
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == '__main__':
    main()