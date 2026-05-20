#!/usr/bin/env python3
"""
Hand Forward Kinematics ROS2 节点

订阅后端（MuJoCo 仿真或真实驱动）发布的手部状态话题
``/cb_right_hand_state``（10 DOF, 0-255），经过正向运动学求解，
发布 21 个骨骼体的全局位姿到 ``/skeleton_body_positions``。

此节点可独立运行于仿真/真实后端之上，提供骨架可视化数据。
也可不启动此节点，由 gateway 内部直接调用 kinematics 模块完成 FK 计算。
"""

import rclpy
from rclpy.node import Node
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseArray, Pose

from .kinematics import range_to_arc_l10_right, expand_to_20_joints, compute_fk


class HandFKNode(Node):
    """L10 右手正向运动学 ROS2 节点。

    订阅后端发布的 10 DOF 手部状态，经 FK 计算后发布 21 个骨骼体的位姿。

    话题接口：
        - 订阅: ``/cb_right_hand_state`` (sensor_msgs/JointState, 10 DOF 0-255)
        - 发布: ``/skeleton_body_positions`` (geometry_msgs/PoseArray, 21 poses)
    """

    def __init__(self):
        """初始化 FK 节点：创建发布者和订阅者。"""
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
        """手部状态回调：执行 4 步 FK 管线并发布结果。

        管线步骤：
            1. **值域转换**：0-255 整数 → 弧度值（根据各 DOF 的范围和方向）
            2. **关节展开**：10 DOF → 20 MuJoCo 关节（填充 mimic 耦合关节）
            3. **FK 求解**：遍历运动链，累积四元数变换，计算 21 个 body 的全局位姿
            4. **打包发布**：将位姿列表转换为 PoseArray 消息并发布

        Args:
            msg: JointState 消息，position 字段含 10 个 DOF 值 (0-255)
        """
        position = msg.position
        if len(position) < 10:
            return

        # 步骤 1: 0-255 值域 → 弧度值（含方向反转处理）
        arc = range_to_arc_l10_right(list(position[:10]))
        # 步骤 2: 10 DOF 弧度 → 20 MuJoCo 关节角度（展开 mimic 关节）
        joints = expand_to_20_joints(arc)
        # 步骤 3: 正向运动学求解 → 21 个全局位姿
        positions, quaternions = compute_fk(joints)

        # 步骤 4: 打包为 PoseArray 消息
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
    """节点入口点：初始化 ROS2 并阻塞 spin。"""
    rclpy.init(args=args)
    node = HandFKNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
