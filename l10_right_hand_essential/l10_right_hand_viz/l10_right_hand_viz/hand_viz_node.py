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
    "thumb_cmc_roll", "thumb_cmc_yaw", "thumb_cmc_pitch", "thumb_mcp", "thumb_ip",
    "index_mcp_roll", "index_mcp_pitch", "index_pip", "index_dip",
    "middle_mcp_pitch", "middle_pip", "middle_dip",
    "ring_mcp_roll", "ring_mcp_pitch", "ring_pip", "ring_dip",
    "pinky_mcp_roll", "pinky_mcp_pitch", "pinky_pip", "pinky_dip",
]


class HandVizNode(Node):
    """手部可视化节点 —— 将网关 DOF 状态转换为 URDF 关节角度并发布

    该节点是可视化管道的核心环节:
    1. 从网关订阅当前位姿的 10 DOF 值 (0-255)
    2. 将 DOF 转换为 MuJoCo 20 关节弧度值
    3. 发布到 /joint_states 话题
    4. robot_state_publisher 接收 /joint_states 后发布 TF 变换
    5. RViz2 根据 TF 变换渲染带网格的手部模型

    订阅话题:
        /l10_gateway/current/dof (JointState, 10 DOF)

    发布话题:
        /joint_states (JointState, 20 关节)
    """

    def __init__(self):
        """初始化可视化节点

        创建 /joint_states 发布器和 /l10_gateway/current/dof 订阅器。
        使用 JOINT_NAMES 常量 (20 个 MuJoCo 关节名) 作为发布消息的 name 字段。
        """
        super().__init__('hand_viz_node')

        self.joint_pub = self.create_publisher(JointState, '/joint_states', 10)

        self.create_subscription(
            JointState, '/l10_gateway/current/dof', self._dof_cb, 10)

        self.get_logger().info("Hand Viz Node initialized (model visualization via gateway)")

    def _dof_cb(self, msg):
        """DOF 状态回调 —— 将 10 DOF 转换为 20 关节角度并发布

        转换流程:
        1. 提取前 10 个 DOF 值 (0-255)
        2. range_to_arc_l10_right(): DOF (0-255) → 弧度值
        3. expand_to_20_joints(): 10 弧度 → 20 关节弧度 (含 mimic 关节展开)
        4. 构建 JointState 消息 (name=JOINT_NAMES, position=20 个弧度值)
        5. 发布到 /joint_states

        Args:
            msg: JointState 消息，包含 10 个 DOF 值 (0-255)
        """
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