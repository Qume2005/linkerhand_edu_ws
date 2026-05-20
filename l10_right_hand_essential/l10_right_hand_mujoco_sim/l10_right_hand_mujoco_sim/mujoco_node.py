"""
L10 右手 MuJoCo 仿真 ROS2 节点

提供与真实 CAN 总线驱动 (l10_right_hand_driver) **完全相同**的话题接口，
使下游节点（gateway、面板、LLM 等）无需区分仿真与真实硬件。

核心功能：
- **关节状态仿真**：接收 0-255 DOF 命令，驱动 MuJoCo 物理引擎，反馈实际关节角度
- **触觉数据仿真**：从 MuJoCo 接触力反算 5 指压力值（单点 + 12x6 矩阵 + 点云）
- **手部信息仿真**：模拟 SDK 信息回报（版本号、速度、温度、故障码等）

线程架构：
- MuJoCo 仿真线程 (daemon)：独立步进物理引擎，按 topic_hz 频率发布状态
- ROS2 spin 线程：处理控制命令回调和设置命令回调

依赖：mujoco, numpy, linker_hand_description, hand_forward_kinematics
"""

import os
import time
import json
import threading

import rclpy
from rclpy.node import Node
from std_msgs.msg import String, Float32MultiArray
from sensor_msgs.msg import JointState, PointCloud2, PointField
import numpy as np

from linker_hand_description import get_urdf_path
import mujoco
import mujoco.viewer
from hand_forward_kinematics.kinematics import collapse_20_to_10, arc_to_range_l10_right


# ============================================================================
# L10 右手关节映射配置 (硬编码)
# ============================================================================

L10_JOINT_MAP = {
    0: 9,  1: 1,   2: 0,   3: 0,  4: 0,  5: 6,
    6: 2, 7: 2,   8: 2,   9: 3,  10: 3, 11: 3,
    12: 7, 13: 4, 14: 4,  15: 4, 16: 8, 17: 5,
    18: 5, 19: 5
}

# URDF mimic 关系: mimic_joint = primary_joint * multiplier
# 键为 mimic 关节的 MuJoCo 索引，值为 (主关节 MuJoCo 索引, 乘数)
MIMIC_JOINTS = {
    2:  (3,  0.58),   # thumb_joint2 = thumb_joint3 * 0.58
    4:  (3,  0.93),   # thumb_joint4 = thumb_joint3 * 0.93
    6:  (7,  0.87),   # index_joint1 = index_joint2 * 0.87
    8:  (7,  0.59),   # index_joint3 = index_joint2 * 0.59
    9:  (10, 0.87),   # middle_joint0 = middle_joint1 * 0.87
    11: (10, 0.59),   # middle_joint2 = middle_joint1 * 0.59
    13: (14, 0.87),   # ring_joint1 = ring_joint2 * 0.87
    15: (14, 0.59),   # ring_joint3 = ring_joint2 * 0.59
    17: (18, 0.87),   # little_joint1 = little_joint2 * 0.87
    19: (18, 0.59),   # little_joint3 = little_joint2 * 0.59
}

# L10 右手关节范围
# DOF0: 拇指弯曲  DOF1: 拇指侧摆  DOF2: 食指弯曲  DOF3: 中指弯曲  DOF4: 无名指弯曲
# DOF5: 小指弯曲  DOF6: 食指侧摆  DOF7: 无名指侧摆  DOF8: 小指侧摆  DOF9: 拇指侧旋
L10_R_MIN = [0, 0, 0, 0, 0, 0, -0.26, 0, 0, -0.52]
L10_R_MAX = [0.75, 1.43, 1.62, 1.62, 1.62, 1.62, 0.21, 0.21, 0.34, 1.01]
L10_R_DIRECT = [-1, -1, -1, -1, -1, -1, 0, 0, 0, -1]

# L10 手指顺序（与 SDK linker_hand_l10_can.py:478 一致）
L10_FINGER_ORDER = [
    "thumb_cmc_pitch", "thumb_cmc_yaw", "index_mcp_pitch", "middle_mcp_pitch",
    "ring_mcp_pitch", "pinky_mcp_pitch", "index_mcp_roll", "ring_mcp_roll",
    "pinky_mcp_roll", "thumb_cmc_roll"
]

# 指尖 body 名称（只有指尖有传感器）
FINGERTIP_BODIES = {
    "thumb_distal": 0,   # thumb
    "index_distal": 1,   # index
    "middle_distal": 2,  # middle
    "ring_distal": 3,    # ring
    "pinky_distal": 4,   # little
}


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
    """L10 右手 MuJoCo 仿真 ROS2 节点。

    本节点作为仿真后端，提供与真实 CAN 总线驱动完全相同的 ROS2 话题接口。
    内部运行 MuJoCo 物理引擎，在独立线程中以固定频率步进仿真并发布状态。

    话题接口（与 l10_right_hand_driver 一致）：
        发布:
            - ``/cb_right_hand_state`` (JointState, 10 DOF 0-255)
            - ``/cb_right_hand_info`` (String, JSON)
            - ``/cb_right_hand_force`` (Float32MultiArray, is_touch 时)
            - ``/cb_right_hand_matrix_touch`` (String, JSON)
            - ``/cb_right_hand_matrix_touch_pc`` (PointCloud2)
            - ``/cb_right_hand_matrix_touch_mass`` (String, JSON)
        订阅:
            - ``/cb_right_hand_control_cmd`` (JointState, 10 DOF 0-255)
            - ``/cb_hand_setting_cmd`` (String, JSON)

    ROS 参数:
        - ``topic_hz`` (int, 默认 30): 状态发布频率 (Hz)
        - ``is_touch`` (bool, 默认 True): 是否仿真触觉数据

    Attributes:
        model: MuJoCo 模型实例
        data: MuJoCo 数据实例
        ctrl_values: 当前 20 个执行器控制值（由命令回调更新）
        finger_geom_map: geom_id -> 手指索引的映射表
    """

    def __init__(self):
        """初始化 MuJoCo 仿真节点：声明参数、加载模型、构建映射、启动仿真线程。"""
        super().__init__('l10_right_mujoco_node')

        # 声明参数
        self.declare_parameter("topic_hz", 30)
        self.declare_parameter("is_touch", True)

        self.topic_hz = self.get_parameter('topic_hz').get_parameter_value().integer_value
        self.is_touch = self.get_parameter('is_touch').get_parameter_value().bool_value

        self.get_logger().info(f"L10 Right Hand MuJoCo Simulation starting...")
        self.get_logger().info(f"  topic_hz: {self.topic_hz}")
        self.get_logger().info(f"  is_touch: {self.is_touch}")

        # 状态变量
        self.last_state_velocity = [0.0] * 10

        # 模拟手部信息（与 SDK linker_hand.py:72-83 结构一致）
        self.hand_info = {
            "version": [10, 1, 0, 82],
            "hand_joint": "L10",
            "speed": [200, 250, 250, 250, 250, 250, 250, 250, 250, 250],
            "current": [0] * 10,
            "fault": [0] * 10,
            "motor_temperature": [25] * 10,
            "torque": [255] * 10,
            "is_touch": self.is_touch,
            "touch_type": 2 if self.is_touch else -1,
            "finger_order": L10_FINGER_ORDER
        }

        # 模拟压感数据
        self.force_data = [[0.0] * 5 for _ in range(4)]  # 4组 x 5手指
        self.matrix_dic = {
            "stamp": {"sec": 0, "nanosec": 0},
            "thumb_matrix": [[0] * 6 for _ in range(12)],
            "index_matrix": [[0] * 6 for _ in range(12)],
            "middle_matrix": [[0] * 6 for _ in range(12)],
            "ring_matrix": [[0] * 6 for _ in range(12)],
            "little_matrix": [[0] * 6 for _ in range(12)]
        }
        self.matrix_mass_dic = {
            "stamp": {"secs": 0, "nsecs": 0},
            "unit": "g",
            "thumb_mass": [0],
            "index_mass": [0],
            "middle_mass": [0],
            "ring_mass": [0],
            "little_mass": [0]
        }

        # 订阅控制命令话题
        self.create_subscription(
            JointState,
            "/cb_right_hand_control_cmd",
            self.hand_cb,
            10
        )

        # /joint_states 由 l10_right_hand_viz/hand_viz_node 通过网关发布，此处不再直接发布

        # 发布实际仿真位姿 0-255（用于下游 FK 推导骨架）
        self.hand_state_pub = self.create_publisher(JointState, "/cb_right_hand_state", 10)

        # 发布手部信息（与 SDK /cb_right_hand_info 一致）
        self.hand_info_pub = self.create_publisher(String, "/cb_right_hand_info", 10)

        # 压感相关发布者（is_touch 为 true 时）
        if self.is_touch:
            self.touch_pub = self.create_publisher(Float32MultiArray, "/cb_right_hand_force", 10)
            self.matrix_touch_pub = self.create_publisher(String, "/cb_right_hand_matrix_touch", 10)
            self.matrix_touch_pc_pub = self.create_publisher(PointCloud2, "/cb_right_hand_matrix_touch_pc", 10)
            self.matrix_touch_mass_pub = self.create_publisher(String, "/cb_right_hand_matrix_touch_mass", 10)

        # 订阅设置命令（与 SDK /cb_hand_setting_cmd 一致）
        self.create_subscription(
            String,
            "/cb_hand_setting_cmd",
            self.hand_setting_cb,
            10
        )

        # 加载 MuJoCo 模型
        xml_path = get_urdf_path()
        self.get_logger().info(f"Loading model from: {xml_path}")

        self.model = mujoco.MjModel.from_xml_path(xml_path)
        self.model.dof_damping[:] = 0.8
        self.data = mujoco.MjData(self.model)

        self.get_logger().info(f"MuJoCo version: {mujoco.mj_versionString()}")

        self.data.qpos[:] = 0
        self.data.qvel[:] = 0
        self.model.opt.disableflags = 1  # 禁用重力
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

        # 构建 geom -> 手指索引映射（用于接触力计算）
        # 遍历所有 geom，检查其所属 body 名称是否在 FINGERTIP_BODIES 中。
        # 若匹配，记录 geom_id -> finger_idx 的映射，后续计算接触力时
        # 即可通过 geom_id 快速定位是哪根手指在接触。
        self.finger_geom_map = {}
        body_name_to_id = {}
        for i in range(self.model.nbody):
            body_name_to_id[mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, i)] = i
        for geom_id in range(self.model.ngeom):
            body_id = self.model.geom_bodyid[geom_id]
            body_name = mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_BODY, body_id)
            if body_name in FINGERTIP_BODIES:
                self.finger_geom_map[geom_id] = FINGERTIP_BODIES[body_name]

        # 启动 MuJoCo 仿真线程
        sim_thread = threading.Thread(target=self.mujoco_thread, daemon=True)
        sim_thread.start()

    def mujoco_thread(self):
        """MuJoCo 仿真线程（无头模式）。

        在独立守护线程中持续运行，每 1ms 步进一次 MuJoCo 物理引擎，
        按 ``topic_hz`` 频率调用 :meth:`publish_joint_states` 发布状态。
        线程随 ROS2 关闭而退出。
        """
        pub_rate = 1.0 / self.topic_hz
        last_pub_time = time.time()
        self.get_logger().info("MuJoCo simulation running (headless)...")

        while rclpy.ok():
            self.data.ctrl[:] = self.ctrl_values
            mujoco.mj_step(self.model, self.data)

            # 发布关节状态
            current_time = time.time()
            if current_time - last_pub_time >= pub_rate:
                self.publish_joint_states()
                last_pub_time = current_time

            time.sleep(0.001)

    def publish_joint_states(self):
        """发布当前关节状态和手部信息。

        从 MuJoCo 仿真数据中读取 20 个关节角度，折叠为 10 DOF 后转换为
        0-255 值域发布到 ``/cb_right_hand_state``。同时发布手部信息 JSON
        和（如启用）触觉数据。
        """
        now = self.get_clock().now().to_msg()

        # 从 MuJoCo 实际关节角度反推 0-255
        qpos_20 = self.data.qpos.tolist()
        arc_10 = collapse_20_to_10(qpos_20)
        ctrl_10 = arc_to_range_l10_right(arc_10)

        # 发布手部状态（与 SDK joint_state_msg 对齐）
        state_msg = JointState()
        state_msg.header.stamp = now
        state_msg.name = list(L10_FINGER_ORDER)
        state_msg.position = [float(x) for x in ctrl_10]
        state_msg.velocity = [float(x) for x in self.last_state_velocity]
        state_msg.effort = [0.0] * 10
        self.hand_state_pub.publish(state_msg)

        # 发布手部信息（与 SDK pub_state info 对齐）
        if self.hand_info_pub.get_subscription_count() > 0:
            info_msg = String()
            info_msg.data = json.dumps(self.hand_info)
            self.hand_info_pub.publish(info_msg)

        # 发布压感数据（is_touch 为 true 时从接触力反算）
        if self.is_touch:
            self.compute_touch_data()
            self.publish_touch_data(now)

    def compute_touch_data(self):
        """从 MuJoCo 接触力计算各手指压力数据。

        遍历所有 MuJoCo 接触对，通过 ``finger_geom_map`` 判断接触是否
        涉及指尖 geom。对每个指尖累加法向力，然后乘以缩放因子 (100.0)
        得到 0-255 范围的压力值。

        同时将总力均匀分配到 12x6 矩阵网格，模拟矩阵触觉传感器的输出。
        """
        finger_forces = [0.0] * 5  # thumb, index, middle, ring, little

        for i in range(self.data.ncon):
            contact = self.data.contact[i]
            geom1 = int(contact.geom1)
            geom2 = int(contact.geom2)

            # 判断接触是否涉及手指 geom
            finger_idx = self.finger_geom_map.get(geom1)
            if finger_idx is None:
                finger_idx = self.finger_geom_map.get(geom2)
            if finger_idx is None:
                continue

            # 计算接触力
            c_array = np.zeros(6)
            mujoco.mj_contactForce(self.model, self.data, i, c_array)
            normal_force = abs(c_array[0])  # 法向力
            finger_forces[finger_idx] += normal_force

        # 缩放到 0-255 范围
        scale = 100.0
        self.force_data = [
            [min(255.0, f * scale) for f in finger_forces],  # normal force
            [0.0] * 5,  # tangential force
            [0.0] * 5,  # tangential direction
            [0.0] * 5,  # approach increment
        ]

        # 矩阵压感：将总力分配到 12x6 网格
        finger_names = ["thumb", "index", "middle", "ring", "little"]
        for i, force in enumerate(finger_forces):
            total = min(255, force * scale)
            per_cell = total / 72.0
            self.matrix_dic[f"{finger_names[i]}_matrix"] = [
                [per_cell] * 6 for _ in range(12)
            ]

    def publish_touch_data(self, stamp):
        """发布压感相关话题（与 SDK pub_state 对齐）"""
        # 单点压力
        if hasattr(self, 'touch_pub') and self.touch_pub.get_subscription_count() > 0:
            force_msg = Float32MultiArray()
            force_msg.data = [float(v) for row in self.force_data for v in row]
            self.touch_pub.publish(force_msg)

        # 矩阵压感
        has_matrix_subs = (hasattr(self, 'matrix_touch_pub') and (
            self.matrix_touch_pub.get_subscription_count() > 0 or
            self.matrix_touch_pc_pub.get_subscription_count() > 0 or
            self.matrix_touch_mass_pub.get_subscription_count() > 0
        ))
        if has_matrix_subs:
            now = self.get_clock().now().to_msg()

            # JSON 格式矩阵数据
            if self.matrix_touch_pub.get_subscription_count() > 0:
                self.matrix_dic["stamp"]["sec"] = now.sec
                self.matrix_dic["stamp"]["nanosec"] = now.nanosec
                mat_msg = String()
                mat_msg.data = json.dumps(self.matrix_dic)
                self.matrix_touch_pub.publish(mat_msg)

            # 矩阵质量和值
            if self.matrix_touch_mass_pub.get_subscription_count() > 0:
                self.matrix_mass_dic["stamp"]["secs"] = now.sec
                self.matrix_mass_dic["stamp"]["nsecs"] = now.nanosec
                finger_names = ["thumb", "index", "middle", "ring", "little"]
                for name in finger_names:
                    self.matrix_mass_dic[f"{name}_mass"] = sum(
                        sum(row) for row in self.matrix_dic[f"{name}_matrix"]
                    )
                mass_msg = String()
                mass_msg.data = json.dumps(self.matrix_mass_dic)
                self.matrix_touch_mass_pub.publish(mass_msg)

            # 点云格式
            if self.matrix_touch_pc_pub.get_subscription_count() > 0:
                self._publish_matrix_point_cloud(now)

    def _publish_matrix_point_cloud(self, stamp):
        """发布矩阵压感点云（与 SDK pub_matrix_point_cloud 对齐）"""
        tmp_dic = self.matrix_dic.copy()
        del tmp_dic['stamp']
        all_matrices = list(tmp_dic.values())
        flat_list = [v for frame in all_matrices for v in frame]
        flat = np.concatenate([
            np.asarray(np.clip(c, 0, 255), dtype=np.uint8) for c in flat_list
        ])

        fields = [PointField(
            name='val',
            offset=0,
            datatype=PointField.UINT8,
            count=1
        )]

        pc = PointCloud2()
        pc.header.stamp = stamp
        pc.header.frame_id = ''
        pc.height = 1
        pc.width = flat.size
        pc.fields = fields
        pc.is_bigendian = False
        pc.point_step = 1
        pc.row_step = pc.point_step * pc.width
        pc.data = flat.tobytes()
        self.matrix_touch_pc_pub.publish(pc)

    def hand_cb(self, msg):
        """处理关节控制命令回调（与 SDK hand_control_cb 对齐）。

        接收 10 DOF 0-255 的位置命令，转换为弧度值后映射到 20 个
        MuJoCo 执行器控制值（含 mimic 展开），写入 ``ctrl_values`` 供
        仿真线程下次步进时应用。

        Args:
            msg: JointState 消息，position 含 10 个 DOF 值 (0-255)
        """
        try:
            position = msg.position
            if len(position) >= 10:
                # 转换为弧度值
                arc_values = range_to_arc_l10_right(position)
                # 映射到 MuJoCo 控制值
                self.ctrl_values[:] = self.map_position_array(arc_values, L10_JOINT_MAP)

            # 存储 velocity 用于状态回显
            if hasattr(msg, 'velocity') and len(msg.velocity) >= 10:
                self.last_state_velocity = [float(x) for x in msg.velocity[:10]]
        except Exception as e:
            self.get_logger().error(f"Error in hand_cb: {e}")

    def hand_setting_cb(self, msg):
        """处理设置命令回调（与 SDK hand_setting_cb 对齐）。

        支持 ``set_speed``、``set_max_torque_limits``、``clear_faults``、
        ``set_electric_current`` 四种命令。仿真模式下大部分命令仅更新
        ``hand_info`` 字典，不影响物理引擎行为。

        Args:
            msg: String 消息，data 字段为 JSON，含 ``setting_cmd`` 和 ``params``
        """
        try:
            data = json.loads(msg.data)
            cmd = data.get("setting_cmd", "")
            params = data.get("params", {})

            if cmd == "set_speed":
                speed = params.get("speed", [])
                if isinstance(speed, list) and len(speed) == 10:
                    self.hand_info["speed"] = [int(s) for s in speed]
                    self.get_logger().info(f"Sim: speed set to {self.hand_info['speed']}")

            elif cmd == "set_max_torque_limits":
                torque = params.get("torque", [])
                if isinstance(torque, list):
                    if len(torque) == 10:
                        self.hand_info["torque"] = [int(t) for t in torque]
                    elif len(torque) < 10:
                        self.hand_info["torque"] = [int(t) for t in torque] + [255] * (10 - len(torque))
                    self.get_logger().info(f"Sim: torque set to {self.hand_info['torque']}")

            elif cmd == "clear_faults":
                self.get_logger().info("Sim: clear_faults (no-op in simulation)")

            elif cmd == "set_electric_current":
                self.get_logger().info("Sim: set_electric_current (no-op in simulation)")

            else:
                self.get_logger().info(f"Sim: unhandled setting_cmd: {cmd}")

        except (json.JSONDecodeError, KeyError) as e:
            self.get_logger().error(f"Error in hand_setting_cb: {e}")

    def map_position_array(self, position, joint_map):
        """将 DOF 弧度数组映射到 20 个 MuJoCo 控制值，应用 mimic 乘数"""
        max_idx = max(joint_map.keys()) + 1
        mapped_array = [0.0] * max_idx

        # 先映射非 mimic 关节
        for target_idx, source_idx in joint_map.items():
            if source_idx < len(position):
                mapped_array[target_idx] = position[source_idx]

        # 应用 mimic 乘数: mimic_joint = primary_joint * multiplier
        for mimic_idx, (primary_idx, multiplier) in MIMIC_JOINTS.items():
            mapped_array[mimic_idx] = mapped_array[primary_idx] * multiplier

        return mapped_array


def main(args=None):
    rclpy.init(args=args)
    node = L10RightMujocoNode()
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
