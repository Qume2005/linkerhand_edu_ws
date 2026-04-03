#!/usr/bin/env python3
"""
L10 Right Hand Skeleton Visualization Node
使用 MuJoCo 的实际 body 位置来显示骨骼
"""

import rclpy
from rclpy.node import Node
from visualization_msgs.msg import Marker, MarkerArray
from geometry_msgs.msg import Point, PoseArray
from std_msgs.msg import ColorRGBA
import numpy as np

# 手指颜色
FINGER_COLORS = {
    'thumb': (1.0, 0.3, 0.3, 1.0),
    'index': (0.3, 1.0, 0.3, 1.0),
    'middle': (0.3, 0.3, 1.0, 1.0),
    'ring': (1.0, 1.0, 0.3, 1.0),
    'little': (1.0, 0.3, 1.0, 1.0),
    'palm': (0.8, 0.8, 0.8, 1.0),
}

# MuJoCo 中实际的 body 顺序 (从 0 开始):
# 0: world
# 1-5: thumb_link0, thumb_link1, thumb_link2, thumb_link3, thumb_link4
# 6-9: index_link0, index_link1, index_link2, index_link3
# 10-12: middle_link0, middle_link1, middle_link2
# 13-16: ring_link0, ring_link1, ring_link2, ring_link3
# 17-20: little_link0, little_link1, little_link2, little_link3

# 骨骼连接定义（正确的 body 索引）
SKELETON_CONNECTIONS = [
    # 拇指: 1->2->3->4->5
    (1, 2), (2, 3), (3, 4), (4, 5),
    # 食指: 6->7->8->9
    (6, 7), (7, 8), (8, 9),
    # 中指: 10->11->12
    (10, 11), (11, 12),
    # 无名指: 13->14->15->16
    (13, 14), (14, 15), (15, 16),
    # 小指: 17->18->19->20
    (17, 18), (18, 19), (19, 20),
]

# 各连接对应的颜色
CONNECTION_COLORS = {
    # 拇指
    (1, 2): 'thumb', (2, 3): 'thumb', (3, 4): 'thumb', (4, 5): 'thumb',
    # 食指
    (6, 7): 'index', (7, 8): 'index', (8, 9): 'index',
    # 中指
    (10, 11): 'middle', (11, 12): 'middle',
    # 无名指
    (13, 14): 'ring', (14, 15): 'ring', (15, 16): 'ring',
    # 小指
    (17, 18): 'little', (18, 19): 'little', (19, 20): 'little',
}

# 手指根部索引（用于显示手掌位置）
FINGER_ROOTS = {
    'thumb': 1,
    'index': 6,
    'middle': 10,
    'ring': 13,
    'little': 17,
}


class SkeletonVizNode(Node):
    def __init__(self):
        super().__init__('skeleton_viz_node')

        self.get_logger().info("Skeleton Visualization Node starting...")

        # 发布骨骼可视化
        self.skeleton_pub = self.create_publisher(MarkerArray, '/skeleton_visualization', 10)

        # 订阅 MuJoCo 发布的 body 位置
        self.body_pos_sub = self.create_subscription(
            PoseArray,
            '/skeleton_body_positions',
            self.body_pos_callback,
            10
        )

        # 存储 body 位置
        self.body_positions = []

        # 定时发布
        self.timer = self.create_timer(0.05, self.publish_skeleton)

        self.get_logger().info("Skeleton Visualization Node initialized")

    def body_pos_callback(self, msg):
        """处理 body 位置回调"""
        self.body_positions = []
        for pose in msg.poses:
            pos = [pose.position.x, pose.position.y, pose.position.z]
            self.body_positions.append(pos)

    def create_sphere_marker(self, marker_id, position, color, size):
        """创建球体标记点"""
        marker = Marker()
        marker.header.frame_id = 'world'
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = 'skeleton_joints'
        marker.id = marker_id
        marker.type = Marker.SPHERE
        marker.action = Marker.ADD
        marker.pose.position.x = position[0]
        marker.pose.position.y = position[1]
        marker.pose.position.z = position[2]
        marker.pose.orientation.w = 1.0
        marker.scale.x = size
        marker.scale.y = size
        marker.scale.z = size
        marker.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=color[3])
        marker.lifetime.sec = 0
        marker.lifetime.nanosec = 0
        return marker

    def create_line_marker(self, marker_id, start_pos, end_pos, color):
        """创建连接线"""
        marker = Marker()
        marker.header.frame_id = 'world'
        marker.header.stamp = self.get_clock().now().to_msg()
        marker.ns = 'skeleton_lines'
        marker.id = marker_id
        marker.type = Marker.LINE_STRIP
        marker.action = Marker.ADD

        start_point = Point(x=start_pos[0], y=start_pos[1], z=start_pos[2])
        end_point = Point(x=end_pos[0], y=end_pos[1], z=end_pos[2])
        marker.points = [start_point, end_point]
        marker.pose.orientation.w = 1.0
        marker.scale.x = 0.003
        marker.color = ColorRGBA(r=color[0], g=color[1], b=color[2], a=color[3])
        marker.lifetime.sec = 0
        marker.lifetime.nanosec = 0
        return marker

    def publish_skeleton(self):
        """发布骨骼可视化 Marker"""
        if len(self.body_positions) < 21:  # 需要至少 21 个 body
            return

        marker_array = MarkerArray()

        # 创建手指根部点（代表手掌）
        for finger_name, root_idx in FINGER_ROOTS.items():
            color = FINGER_COLORS[finger_name]
            pos = self.body_positions[root_idx]
            marker = self.create_sphere_marker(root_idx, pos, color, 0.012)
            marker_array.markers.append(marker)

        # 创建所有关节点
        for conn in SKELETON_CONNECTIONS:
            color_name = CONNECTION_COLORS.get(conn, 'palm')
            color = FINGER_COLORS[color_name]

            # 起点
            start_pos = self.body_positions[conn[0]]
            marker = self.create_sphere_marker(conn[0] * 10, start_pos, color, 0.008)
            marker_array.markers.append(marker)

            # 终点
            end_pos = self.body_positions[conn[1]]
            marker = self.create_sphere_marker(conn[1] * 10 + 1, end_pos, color, 0.008)
            marker_array.markers.append(marker)

        # 创建连接线
        for conn in SKELETON_CONNECTIONS:
            start_pos = self.body_positions[conn[0]]
            end_pos = self.body_positions[conn[1]]
            color_name = CONNECTION_COLORS.get(conn, 'palm')
            color = FINGER_COLORS[color_name]
            line_marker = self.create_line_marker(conn[0] * 100 + conn[1], start_pos, end_pos, color)
            marker_array.markers.append(line_marker)

        self.skeleton_pub.publish(marker_array)


def main(args=None):
    rclpy.init(args=args)
    node = SkeletonVizNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()