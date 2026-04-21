#!/usr/bin/env python3
"""
Hand Forward Kinematics Node
订阅 /cb_right_hand_state (10 DOF, 0-255) → FK → 发布 /skeleton_body_positions (21 poses)
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseArray, Pose

from .kinematics import range_to_arc_l10_right, expand_to_20_joints, compute_fk


class HandFKNode(Node):
    def __init__(self):
        super().__init__('hand_fk_node')
        self.get_logger().info("Hand Forward Kinematics Node starting...")

        # 发布: 与 MuJoCo 仿真相同的话题和格式
        self.pose_pub = self.create_publisher(
            PoseArray, '/skeleton_body_positions', 10)

        # 订阅: 官方 SDK 的手部状态
        self.create_subscription(
            JointState, '/cb_right_hand_state',
            self.state_callback, 10)

        self.get_logger().info(
            "Subscribing: /cb_right_hand_state | Publishing: /skeleton_body_positions")

    def state_callback(self, msg):
        position = msg.position
        if len(position) < 10:
            return

        # 1. 0-255 → 弧度
        arc = range_to_arc_l10_right(list(position[:10]))
        # 2. 10 DOF → 20 关节
        joints = expand_to_20_joints(arc)
        # 3. FK
        positions, quaternions = compute_fk(joints)

        # 4. 打包 PoseArray
        pose_array = PoseArray()
        pose_array.header.stamp = self.get_clock().now().to_msg()
        pose_array.header.frame_id = "world"

        for i in range(21):
            pose = Pose()
            pose.position.x = float(positions[i][0])
            pose.position.y = float(positions[i][1])
            pose.position.z = float(positions[i][2])
            pose.orientation.w = float(quaternions[i][0])
            pose.orientation.x = float(quaternions[i][1])
            pose.orientation.y = float(quaternions[i][2])
            pose.orientation.z = float(quaternions[i][3])
            pose_array.poses.append(pose)

        self.pose_pub.publish(pose_array)


def main(args=None):
    rclpy.init(args=args)
    node = HandFKNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
