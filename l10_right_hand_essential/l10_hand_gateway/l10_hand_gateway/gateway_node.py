#!/usr/bin/env python3
"""
L10 Hand Gateway Node
控制 topic 反向代理 + 状态 topic 代理服务

广播:
  /l10_gateway/camera              Float32MultiArray [distance, nx, ny, nz]
  /l10_gateway/current/dof         JointState (10 DOF 0-255)
  /l10_gateway/current/skeleton    PoseArray (21 poses)
  /l10_gateway/current/control_points PoseArray (5 positions)
  /l10_gateway/target/dof          JointState (10 DOF 0-255)
  /l10_gateway/target/skeleton     PoseArray (21 poses)
  /l10_gateway/target/control_points PoseArray (5 positions)

订阅命令:
  /l10_gateway/cmd/dof             JointState → 直接更新 target
  /l10_gateway/cmd/skeleton        PoseArray → 逆 FK → DOF
  /l10_gateway/cmd/control_points  PoseArray → IK → DOF
  /l10_gateway/cmd/control_points_diff PoseArray → 当前 cp + diff → IK → DOF
  /l10_gateway/cmd/camera          Float32MultiArray → 存储 + 广播
  /l10_gateway/cmd/camera_diff     Float32MultiArray [delta_distance, qx, qy, qz] → 旋转法向量 + 距离差分 → 广播

后端:
  订阅 /cb_right_hand_state → 广播 current/*
  发布 /cb_right_hand_control_cmd ← 命令转发
"""

import rclpy
import math
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from sensor_msgs.msg import JointState
from geometry_msgs.msg import PoseArray, Pose
from std_msgs.msg import Float32MultiArray, String

from l10_hand_gateway.ik_solver import (
    inverse_skeleton_to_dof,
    ik_control_points,
    compute_control_points_from_dof,
    compute_skeleton_from_dof,
)


class L10HandGatewayNode(Node):
    def __init__(self):
        super().__init__('l10_hand_gateway')

        # ---- 状态 ----
        self._current_dof = [255.0] * 10
        self._target_dof = [255.0, 200.0, 255.0, 255.0, 255.0, 255.0, 180.0, 180.0, 180.0, 41.0]
        self._last_forwarded_dof = None  # 消抖：上次转发给后端的 DOF
        self._camera = [0.25, 0.0, 0.0, -1.0]  # [distance, nx, ny, nz]

        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)

        # ---- 广播发布器 (7 个) ----
        self._pub_camera = self.create_publisher(
            Float32MultiArray, '/l10_gateway/camera', qos)
        self._pub_current_dof = self.create_publisher(
            JointState, '/l10_gateway/current/dof', qos)
        self._pub_current_skeleton = self.create_publisher(
            PoseArray, '/l10_gateway/current/skeleton', qos)
        self._pub_current_cp = self.create_publisher(
            PoseArray, '/l10_gateway/current/control_points', qos)
        self._pub_target_dof = self.create_publisher(
            JointState, '/l10_gateway/target/dof', qos)
        self._pub_target_skeleton = self.create_publisher(
            PoseArray, '/l10_gateway/target/skeleton', qos)
        self._pub_target_cp = self.create_publisher(
            PoseArray, '/l10_gateway/target/control_points', qos)

        # ---- 后端发布器 ----
        self._pub_backend_cmd = self.create_publisher(
            JointState, '/cb_right_hand_control_cmd', qos)

        # ---- 触觉传感器广播发布器 (3 个) ----
        self._pub_force = self.create_publisher(
            Float32MultiArray, '/l10_gateway/sensor/force', qos)
        self._pub_matrix_touch = self.create_publisher(
            String, '/l10_gateway/sensor/matrix_touch', qos)
        self._pub_matrix_mass = self.create_publisher(
            String, '/l10_gateway/sensor/matrix_touch_mass', qos)

        # ---- 命令订阅器 (5 个) ----
        self.create_subscription(
            JointState, '/l10_gateway/cmd/dof', self._on_cmd_dof, qos)
        self.create_subscription(
            PoseArray, '/l10_gateway/cmd/skeleton', self._on_cmd_skeleton, qos)
        self.create_subscription(
            PoseArray, '/l10_gateway/cmd/control_points', self._on_cmd_cp, qos)
        self.create_subscription(
            PoseArray, '/l10_gateway/cmd/control_points_diff', self._on_cmd_cp_diff, qos)
        self.create_subscription(
            Float32MultiArray, '/l10_gateway/cmd/camera', self._on_cmd_camera, qos)
        self.create_subscription(
            Float32MultiArray, '/l10_gateway/cmd/camera_diff', self._on_cmd_camera_diff, qos)

        # ---- 后端状态订阅 ----
        self.create_subscription(
            JointState, '/cb_right_hand_state', self._on_backend_state, qos)

        # ---- 触觉传感器后端订阅 (3 个) ----
        self.create_subscription(
            Float32MultiArray, '/cb_right_hand_force', self._on_backend_force, qos)
        self.create_subscription(
            String, '/cb_right_hand_matrix_touch', self._on_backend_matrix, qos)
        self.create_subscription(
            String, '/cb_right_hand_matrix_touch_mass', self._on_backend_mass, qos)

        # ---- 启动时广播初始状态并转发预设位置 ----
        self._broadcast_current()
        self._broadcast_target()
        self._broadcast_camera()
        self._forward_to_backend()

        self.get_logger().info(
            "L10 Hand Gateway started. "
            f"Broadcasting 10 topics, subscribing 6 cmd + 4 backend.")

    # ====================================================================
    # 后端状态回调 → 广播 current/*
    # ====================================================================

    def _on_backend_state(self, msg):
        if len(msg.position) < 10:
            return
        self._current_dof = [float(v) for v in msg.position[:10]]
        self._broadcast_current()

    # ====================================================================
    # 触觉传感器回调 → 透传到 /l10_gateway/sensor/*
    # ====================================================================

    def _on_backend_force(self, msg):
        self._pub_force.publish(msg)

    def _on_backend_matrix(self, msg):
        self._pub_matrix_touch.publish(msg)

    def _on_backend_mass(self, msg):
        self._pub_matrix_mass.publish(msg)

    # ====================================================================
    # 命令回调 → 更新 target → 广播 target/* → 转发后端
    # ====================================================================

    def _on_cmd_dof(self, msg):
        if len(msg.position) < 10:
            return
        self._target_dof = [float(v) for v in msg.position[:10]]
        self._broadcast_target()
        self._forward_to_backend()

    def _on_cmd_skeleton(self, msg):
        if len(msg.poses) < 21:
            return
        orientations = []
        for pose in msg.poses:
            orientations.append(np.array([
                pose.orientation.w, pose.orientation.x,
                pose.orientation.y, pose.orientation.z,
            ]))
        dof = inverse_skeleton_to_dof(orientations)
        self._target_dof = [max(0.0, min(255.0, v)) for v in dof]
        self._broadcast_target()
        self._forward_to_backend()

    def _on_cmd_cp(self, msg):
        if len(msg.poses) < 5:
            return
        import numpy as np
        targets = []
        for pose in msg.poses:
            targets.append(np.array([
                pose.position.x, pose.position.y, pose.position.z,
            ]))
        cam_normal = np.array(self._camera[1:4]) if self._camera else None
        dof = ik_control_points(targets, self._target_dof, camera_normal=cam_normal)
        self._target_dof = [max(0.0, min(255.0, v)) for v in dof]
        self._broadcast_target()
        self._forward_to_backend()

    def _on_cmd_cp_diff(self, msg):
        if len(msg.poses) < 5:
            return
        import numpy as np
        # 当前控制点 + 差分 = 目标控制点
        current_cp = compute_control_points_from_dof(self._current_dof)
        targets = []
        for i in range(5):
            diff = np.array([
                msg.poses[i].position.x,
                msg.poses[i].position.y,
                msg.poses[i].position.z,
            ])
            targets.append(current_cp[i] + diff)
        cam_normal = np.array(self._camera[1:4]) if self._camera else None
        dof = ik_control_points(targets, self._target_dof, camera_normal=cam_normal)
        self._target_dof = [max(0.0, min(255.0, v)) for v in dof]
        self._broadcast_target()
        self._forward_to_backend()

    def _on_cmd_camera(self, msg):
        if len(msg.data) < 4:
            return
        self._camera = [float(v) for v in msg.data[:4]]  # [distance, nx, ny, nz]
        self._broadcast_camera()

    def _on_cmd_camera_diff(self, msg):
        """相机差分命令: [delta_distance, qx, qy, qz]"""
        if len(msg.data) < 4:
            return
        delta_distance = float(msg.data[0])
        qx, qy, qz = float(msg.data[1]), float(msg.data[2]), float(msg.data[3])

        # 从 qx,qy,qz 恢复四元数 w 分量
        ss = qx * qx + qy * qy + qz * qz
        if ss > 1.0:
            scale = 1.0 / math.sqrt(ss)
            qx *= scale
            qy *= scale
            qz *= scale
            ss = 1.0
        qw = math.sqrt(max(0.0, 1.0 - ss))

        # 四元数旋转当前法向量 (camera 存储: [distance, nx, ny, nz])
        nx, ny, nz = self._camera[1], self._camera[2], self._camera[3]
        # v' = q * v * q^(-1)
        # 展开四元数旋转公式
        t0 = qw * qx
        t1 = qw * qy
        t2 = qw * qz
        t3 = -qx * qx
        t4 = qx * qy
        t5 = qx * qz
        t6 = -qy * qy
        t7 = qy * qz
        t8 = -qz * qz
        new_nx = 2.0 * ((t6 + t8 + 1.0) * nx + (t4 - t2) * ny + (t1 + t5) * nz) + nx
        new_ny = 2.0 * ((t2 + t4) * nx + (t3 + t8 + 1.0) * ny + (t5 - t0) * nz) + ny
        new_nz = 2.0 * ((t5 - t1) * nx + (t0 + t5) * ny + (t3 + t6 + 1.0) * nz) + nz

        # 归一化
        mag = math.sqrt(new_nx * new_nx + new_ny * new_ny + new_nz * new_nz)
        if mag > 1e-8:
            new_nx /= mag
            new_ny /= mag
            new_nz /= mag

        new_dist = max(0.1, min(1.0, self._camera[0] + delta_distance))
        self._camera = [new_dist, new_nx, new_ny, new_nz]
        self._broadcast_camera()

    # ====================================================================
    # 广播方法
    # ====================================================================

    def _now(self):
        return self.get_clock().now().to_msg()

    def _broadcast_camera(self):
        msg = Float32MultiArray()
        msg.data = [float(v) for v in self._camera]
        self._pub_camera.publish(msg)

    def _broadcast_current(self):
        stamp = self._now()

        # current/dof
        dof_msg = JointState()
        dof_msg.header.stamp = stamp
        dof_msg.position = [float(v) for v in self._current_dof]
        self._pub_current_dof.publish(dof_msg)

        # current/skeleton + current/control_points
        try:
            positions, quaternions = compute_skeleton_from_dof(self._current_dof)
            self._pub_current_skeleton.publish(
                self._make_pose_array(positions, quaternions, stamp))
            cp_positions = [positions[bi] for bi in [5, 9, 12, 16, 20]]
            self._pub_current_cp.publish(
                self._make_cp_array(cp_positions, stamp))
        except Exception:
            pass

    def _broadcast_target(self):
        stamp = self._now()

        # target/dof
        dof_msg = JointState()
        dof_msg.header.stamp = stamp
        dof_msg.position = [float(v) for v in self._target_dof]
        self._pub_target_dof.publish(dof_msg)

        # target/skeleton + target/control_points
        try:
            positions, quaternions = compute_skeleton_from_dof(self._target_dof)
            self._pub_target_skeleton.publish(
                self._make_pose_array(positions, quaternions, stamp))
            cp_positions = [positions[bi] for bi in [5, 9, 12, 16, 20]]
            self._pub_target_cp.publish(
                self._make_cp_array(cp_positions, stamp))
        except Exception:
            pass

    def _forward_to_backend(self):
        # 消抖：与上次转发的 DOF 比较，差分 < 3 的命令不转发
        if self._last_forwarded_dof is not None:
            diff = any(
                abs(a - b) >= 3
                for a, b in zip(self._last_forwarded_dof, self._target_dof)
            )
            if not diff:
                return
        self._last_forwarded_dof = list(self._target_dof)

        msg = JointState()
        msg.header.stamp = self._now()
        msg.position = [float(v) for v in self._target_dof]
        self._pub_backend_cmd.publish(msg)

    # ====================================================================
    # 辅助: 构建 PoseArray 消息
    # ====================================================================

    def _make_pose_array(self, positions, quaternions, stamp):
        """21 个 body 位姿 → PoseArray"""
        pa = PoseArray()
        pa.header.stamp = stamp
        pa.header.frame_id = "world"
        for i in range(21):
            p = Pose()
            p.position.x = float(positions[i][0])
            p.position.y = float(positions[i][1])
            p.position.z = float(positions[i][2])
            p.orientation.w = float(quaternions[i][0])
            p.orientation.x = float(quaternions[i][1])
            p.orientation.y = float(quaternions[i][2])
            p.orientation.z = float(quaternions[i][3])
            pa.poses.append(p)
        return pa

    def _make_cp_array(self, cp_positions, stamp):
        """5 个控制点位置 → PoseArray"""
        pa = PoseArray()
        pa.header.stamp = stamp
        pa.header.frame_id = "world"
        for pos in cp_positions:
            p = Pose()
            p.position.x = float(pos[0])
            p.position.y = float(pos[1])
            p.position.z = float(pos[2])
            p.orientation.w = 1.0
            pa.poses.append(p)
        return pa


# numpy import for inverse_skeleton_to_dof callback
import numpy as np


def main(args=None):
    rclpy.init(args=args)
    node = L10HandGatewayNode()
    rclpy.spin(node)
    node.destroy_node()
    rclpy.shutdown()


if __name__ == '__main__':
    main()
