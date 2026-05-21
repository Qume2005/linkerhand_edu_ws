"""
摄像头手势跟踪 → L10 灵巧手控制点 + 相机控制
MediaPipe 21 关键点 → 5 指尖 3D 目标 → /l10_gateway/cmd/control_points (IK)
                   → 手掌法平面 + 距离 → /l10_gateway/cmd/camera
右手沿画面中轴镜像, 左手不翻转
"""
import cv2
import math
import numpy as np

try:
    import mediapipe as mp
    from mediapipe.tasks.python.vision import HandLandmarker
    from mediapipe.tasks.python.core.base_options import BaseOptions
    USE_TASK_API = True
except (ImportError, AttributeError):
    try:
        import mediapipe as mp
        mp_hands = mp.solutions.hands
        USE_TASK_API = False
    except (ImportError, AttributeError):
        USE_TASK_API = None

import rclpy
from rclpy.node import Node
from rclpy.qos import QoSProfile, ReliabilityPolicy
from geometry_msgs.msg import PoseArray, Pose
from sensor_msgs.msg import JointState
from std_msgs.msg import Float32MultiArray

from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    expand_to_20_joints,
    compute_fk,
)


# MediaPipe 指尖索引 → MuJoCo 控制点顺序
# 控制点顺序: [thumb, index, middle, ring, little]
TIP_INDICES = [4, 8, 12, 16, 20]
PALM_INDICES = [0, 5, 9, 13, 17]  # 手腕 + 4 MCP

# MediaPipe 每根手指的 4 个关节索引: [根, 中, 次, 尖]
FINGER_JOINTS = [
    [1, 2, 3, 4],      # thumb:  CMC, MCP, IP,  TIP
    [5, 6, 7, 8],      # index:  MCP, PIP, DIP, TIP
    [9, 10, 11, 12],   # middle: MCP, PIP, DIP, TIP
    [13, 14, 15, 16],  # ring:   MCP, PIP, DIP, TIP
    [17, 18, 19, 20],  # little: MCP, PIP, DIP, TIP
]


# 相机内参
CAMERA_MATRIX = np.array([[600, 0, 320], [0, 600, 240], [0, 0, 1]], dtype=np.float32)


# ---------------------------------------------------------------------------
# 几何工具
# ---------------------------------------------------------------------------

def estimate_depth(landmarks, w, h, palm_length_cm=8.0):
    wrist = landmarks[0]
    middle_mcp = landmarks[9]
    px = np.sqrt(((middle_mcp[0] - wrist[0]) * w) ** 2 +
                 ((middle_mcp[1] - wrist[1]) * h) ** 2) + 1e-6
    f = (CAMERA_MATRIX[0, 0] + CAMERA_MATRIX[1, 1]) / 2
    return (f * palm_length_cm) / px


def landmarks_to_3d(landmarks, w, h, palm_length_cm=8.0):
    Z_wrist = estimate_depth(landmarks, w, h, palm_length_cm)
    fx, fy = CAMERA_MATRIX[0, 0], CAMERA_MATRIX[1, 1]
    cx, cy = CAMERA_MATRIX[0, 2], CAMERA_MATRIX[1, 2]
    pts = []
    for lm in landmarks:
        z = Z_wrist + lm[2] * Z_wrist * 0.3
        x = (lm[0] * w - cx) * z / fx
        y = (lm[1] * h - cy) * z / fy
        pts.append(np.array([x, y, z]))
    return pts


FINGERTIP_BODIES = [5, 9, 12, 16, 20]


def _fk_control_points(dof_10):
    """10 DOF (0-255) → 5 个指尖 3D 控制点"""
    arc = range_to_arc_l10_right(dof_10)
    joints_20 = expand_to_20_joints(arc)
    positions, _ = compute_fk(joints_20)
    return [positions[bi].copy() for bi in FINGERTIP_BODIES]


def compute_camera_cmd(pts_3d):
    """从 3D 手部关键点计算 MuJoCo 相机控制命令。

    通过手腕、食指 MCP、中指 MCP、小指 MCP 四个点构建掌心坐标系：
    - Y 轴：手腕 → 中指 MCP 方向
    - X 轴：食指 MCP → 小指 MCP 方向（投影到 Y 的法平面后归一化）
    - 法向量：X × Y 得到掌心法向量

    坐标轴映射 (真实相机 → MuJoCo): nx=-normal[2], ny=normal[0], nz=-normal[1]

    Args:
        pts_3d: 21 个 3D 关键点 (numpy 数组列表)

    Returns:
        [distance, nx, ny, nz] 浮点数列表
    """
    wrist = pts_3d[0]
    index_mcp = pts_3d[5]
    middle_mcp = pts_3d[9]
    pinky_mcp = pts_3d[17]

    palm_y = middle_mcp - wrist
    palm_y = palm_y / (np.linalg.norm(palm_y) + 1e-8)
    x_temp = index_mcp - pinky_mcp
    palm_x = x_temp - np.dot(x_temp, palm_y) * palm_y
    palm_x = palm_x / (np.linalg.norm(palm_x) + 1e-8)
    normal = np.cross(palm_x, palm_y)
    normal = normal / (np.linalg.norm(normal) + 1e-8)

    # 坐标轴映射: 真实相机 → MuJoCo
    nx, ny, nz = -normal[2], normal[0], -normal[1]

    # 距离: 按手掌像素尺寸自适应
    dist = float(np.clip(np.linalg.norm(wrist) / 100.0, 0.2, 0.8))
    return [dist, float(nx), float(ny), float(nz)]


def mirror_landmarks_x(landmarks):
    """沿画面中轴 (x=0.5) 水平镜像"""
    return [(1.0 - lm[0], lm[1], lm[2]) for lm in landmarks]


def compute_finger_curls(landmarks):
    """
    从 MediaPipe 关键点计算每根手指的弯曲比

    用首段和末段向量的夹角余弦衡量弯曲:
      伸直 → cos ≈ 1 → curl ≈ 0
      弯曲 → cos < 1 → curl > 0
    """
    lm = [np.array(p) for p in landmarks]
    curls = []
    for finger_idx, joints in enumerate(FINGER_JOINTS):
        v1 = lm[joints[1]][:2] - lm[joints[0]][:2]  # 首段: e.g. MCP→PIP
        v2 = lm[joints[3]][:2] - lm[joints[2]][:2]  # 末段: e.g. DIP→TIP
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
        curls.append(float(np.clip((1.0 - cos_a) / 2.0, 0.0, 1.0)))
    return curls


def landmarks_to_raw_dof(landmarks):
    """从 MediaPipe 21 关键点计算 10 DOF 原始映射值（未经校准修正）。

    弯曲 DOF (0,2,3,4,5): 由各手指的 curl 值反转为 0-255 范围
        curl=0 (伸直) → 255, curl=1 (弯曲) → 0

    侧摆 DOF (6,7,8): 以中指 MCP 的 x 坐标为参考中心，
        各指尖到中心的距离归一化后映射到 0-255

    拇指侧摆 DOF (1): 拇指尖到食指 MCP 的横向距离

    拇指旋转 DOF (9): 固定值 41.0（无可靠映射源）
    """
    curls = compute_finger_curls(landmarks)
    dof = [0.0] * 10
    # 弯曲 DOF
    dof[0] = 255.0 * (1.0 - curls[0])   # thumb bend
    dof[2] = 255.0 * (1.0 - curls[1])   # index bend
    dof[3] = 255.0 * (1.0 - curls[2])   # middle bend
    dof[4] = 255.0 * (1.0 - curls[3])   # ring bend
    dof[5] = 255.0 * (1.0 - curls[4])   # little bend

    # 侧摆 DOF (归一化 by MCP 跨度)
    mid_x = landmarks[12][0]
    mcp_span = abs(landmarks[5][0] - landmarks[17][0]) + 1e-6
    lat_scale = 3.0 / mcp_span
    dof[6] = float(np.clip(255.0 * (mid_x - landmarks[8][0]) * lat_scale, 0, 255))
    dof[7] = float(np.clip(255.0 * (landmarks[16][0] - mid_x) * lat_scale, 0, 255))
    dof[8] = float(np.clip(255.0 * (landmarks[20][0] - mid_x) * lat_scale, 0, 255))

    # 拇指侧摆: 拇指尖到食指 MCP 的横向距离
    thumb_dx = landmarks[5][0] - landmarks[4][0]  # spread 时 > 0
    dof[1] = float(np.clip(255.0 * thumb_dx / mcp_span * 1.5, 0, 255))

    # 拇指旋转: 从 CMC→MCP 与掌心方向的夹角估算 opposition 程度
    cmc = np.array(landmarks[1][:2])
    thumb_mcp = np.array(landmarks[2][:2])
    wrist = np.array(landmarks[0][:2])
    mid_mcp = np.array(landmarks[9][:2])
    thumb_dir = thumb_mcp - cmc
    palm_dir = mid_mcp - wrist
    cos_angle = np.dot(thumb_dir, palm_dir) / (np.linalg.norm(thumb_dir) * np.linalg.norm(palm_dir) + 1e-8)
    # cos_angle ≈ 1 → 拇指与掌心同向 (侧展, 低 roll)
    # cos_angle ≈ -1 → 拇指与掌心反向 (对掌, 高 roll)
    opposition = float(np.clip((1.0 - cos_angle) / 2.0, 0.0, 1.0))
    # DIRECT[9]=-1: DOF=0→max_roll, DOF=255→no_roll
    # opposition 高 → roll 大 → DOF 小
    dof[9] = float(np.clip(255.0 * (1.0 - opposition), 0.0, 255.0))
    return dof


def landmarks_to_control_points(landmarks, current_cp, frame_w, frame_h):
    """
    MediaPipe 21 关键点 → 5 个 MuJoCo 控制点 (3D meters)
    全部 5 指通过 DOF→FK 计算 (包括拇指)
    """
    dof = landmarks_to_raw_dof(landmarks)
    return _fk_control_points(dof)


# ---------------------------------------------------------------------------
# 校准系统
# ---------------------------------------------------------------------------


def _extract_features(landmarks):
    """提取 5 维 curl 特征 (校准用)"""
    return compute_finger_curls(landmarks)


def _build_cp_calibration(samples):
    """从校准样本构建 per-finger 控制点分段线性修正模型（全部 5 指）。

    模型原理
    --------
    对每根手指独立建立一个 curl → 3D delta 的分段线性查找表。
    使用时根据当前手指的 curl 值查表插值，得到应施加的 3D 偏移修正量。

    零锚点约定: 自动在 curl=1 处插入 delta=(0,0,0)，
    表示完全握拳时信任原始 DOF→FK 映射，不做修正。

    Args:
        samples: 校准采样列表，每项含:
            - "curls": 5 个手指的弯曲比
            - "cp_delta": 5 个手指的 3D 偏移量 [dx, dy, dz]

    Returns:
        5 个分段线性表的列表（每根手指一个），
        每个表为 (curl, np.array([dx,dy,dz])) 的有序列表，
        或 None（如果无样本）
    """
    if not samples:
        return None

    models = []
    for fi in range(5):  # 全部 5 根手指
        # 零锚点: curl=1 → delta=0 (握拳时信任原始映射)
        pairs = [(1.0, np.zeros(3))]
        for s in samples:
            pairs.append((s['curls'][fi], np.array(s['cp_delta'][fi])))
        pairs.sort(key=lambda p: p[0])
        # 去重
        deduped = [pairs[0]]
        for p in pairs[1:]:
            if abs(p[0] - deduped[-1][0]) < 1e-8:
                deduped[-1] = p
            else:
                deduped.append(p)
        models.append(deduped)

    return models


def _apply_cp_calibration(raw_cp, curls, models):
    """对全部 5 根手指应用分段线性控制点修正。

    根据每根手指的 curl 值在对应的分段线性表中查找修正向量 delta，
    然后将 delta 叠加到原始控制点上。curl 值超出表范围时使用最近端点值。

    Args:
        raw_cp: 5 个原始控制点 (numpy array 列表, 每个 shape=(3,))
        curls: 5 个手指的弯曲比
        models: 5 个分段线性表（由 _build_cp_calibration 生成）

    Returns:
        5 个修正后的控制点 (numpy array 列表)
    """
    corrected = [cp.copy() for cp in raw_cp]
    for fi in range(5):
        curl = curls[fi]
        pairs = models[fi]

        if curl <= pairs[0][0]:
            delta = pairs[0][1]
        elif curl >= pairs[-1][0]:
            delta = pairs[-1][1]
        else:
            delta = np.zeros(3)
            for j in range(len(pairs) - 1):
                if pairs[j][0] <= curl <= pairs[j + 1][0]:
                    c0, d0 = pairs[j]
                    c1, d1 = pairs[j + 1]
                    t = (curl - c0) / (c1 - c0 + 1e-12)
                    delta = d0 + t * (d1 - d0)
                    break

        corrected[fi] = corrected[fi] + delta

    return corrected


# ---------------------------------------------------------------------------
# 可视化
# ---------------------------------------------------------------------------

def draw_tracking(img, landmarks, handedness, targets, curls):
    h, w = img.shape[:2]
    connections = [
        (0, 1), (1, 2), (2, 3), (3, 4),
        (0, 5), (5, 6), (6, 7), (7, 8),
        (0, 9), (9, 10), (10, 11), (11, 12),
        (0, 13), (13, 14), (14, 15), (15, 16),
        (0, 17), (17, 18), (18, 19), (19, 20),
        (5, 9), (9, 13), (13, 17),
    ]
    colors = [(255, 0, 0), (0, 255, 255), (0, 255, 0), (255, 255, 0), (255, 0, 255)]
    names = ['Thumb', 'Index', 'Middle', 'Ring', 'Little']

    for s, e in connections:
        p1 = (int(landmarks[s][0] * w), int(landmarks[s][1] * h))
        p2 = (int(landmarks[e][0] * w), int(landmarks[e][1] * h))
        cv2.line(img, p1, p2, (0, 255, 0), 2)

    for i, lm in enumerate(landmarks):
        x, y = int(lm[0] * w), int(lm[1] * h)
        color = colors[TIP_INDICES.index(i)] if i in TIP_INDICES else (0, 255, 0)
        r = 8 if i in TIP_INDICES else 4
        cv2.circle(img, (x, y), r, color, -1)

    # 掌心
    palm = np.mean([np.array(landmarks[i][:2]) for i in PALM_INDICES], axis=0)
    cv2.circle(img, (int(palm[0] * w), int(palm[1] * h)), 10, (0, 255, 255), 2)

    # 标签
    label = f"{handedness} hand -> L10 Right"
    cv2.putText(img, label, (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 0), 2)

    # 控制点信息 + 弯曲比
    if targets:
        for i, (name, t, c, cr) in enumerate(zip(names, targets, colors, curls)):
            text = f"CP{i} {name}: curl={cr:.2f} [{t[0]:.3f}, {t[1]:.3f}, {t[2]:.3f}]"
            cv2.putText(img, text, (10, 55 + i * 20),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.4, c, 1)


# ---------------------------------------------------------------------------
# ROS2 节点
# ---------------------------------------------------------------------------

class HandTrackingNode(Node):
    """手势跟踪 ROS 节点 —— 摄像头实时捕捉手部姿态并映射为灵巧手控制命令。

    核心管道
    --------
    摄像头帧 → MediaPipe 手部关键点检测 → 右手 x 轴镜像 →
    弯曲度/侧摆计算 → 10-DOF 映射 → FK 正运动学 → 5 指尖控制点 →
    EMA 平滑 → 发布到 /l10_gateway/cmd/control_points

    同时通过掌心法向量计算相机控制命令，发布到 /l10_gateway/cmd/camera。

    校准系统
    --------
    支持分段线性校正模型，通过 OpenCV 窗口的键盘交互进行校准：
    - ``C`` 键：进入/完成校准模式
    - ``Space`` 键：在校准模式下采样当前手势的映射偏差

    ROS 参数
    --------
    - ``camera_id`` (int, 默认 0): 摄像头设备号
    - ``publish_hz`` (int, 默认 30): 发布频率 (Hz)

    话题接口
    --------
    发布:
    - /l10_gateway/cmd/control_points (PoseArray) — 5 个指尖 3D 目标位置
    - /l10_gateway/cmd/camera (Float32MultiArray) — 相机 [距离, nx, ny, nz]

    订阅:
    - /l10_gateway/current/control_points (PoseArray) — 当前实际控制点
    - /l10_gateway/target/dof (JointState) — 校准采样用
    """

    def __init__(self):
        super().__init__('hand_tracking_node')

        self.declare_parameter('camera_id', 0)
        self.declare_parameter('publish_hz', 30)
        cam_id = self.get_parameter('camera_id').get_parameter_value().integer_value
        hz = self.get_parameter('publish_hz').get_parameter_value().integer_value

        if USE_TASK_API is None:
            self.get_logger().error('MediaPipe 未安装, 请运行: pip install mediapipe')
            raise SystemExit(1)

        self._init_mediapipe()

        self.cap = cv2.VideoCapture(cam_id, cv2.CAP_V4L2)
        if not self.cap.isOpened():
            self.get_logger().error(f'无法打开摄像头 (camera_id={cam_id})')
            raise SystemExit(1)
        self.cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter_fourcc(*'MJPG'))
        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

        qos = QoSProfile(depth=10, reliability=ReliabilityPolicy.RELIABLE)

        # 发布
        self.pub_cp = self.create_publisher(
            PoseArray, '/l10_gateway/cmd/control_points', qos)
        self.pub_camera = self.create_publisher(
            Float32MultiArray, '/l10_gateway/cmd/camera', qos)

        # 订阅当前状态
        self._current_cp = None
        self.create_subscription(
            PoseArray, '/l10_gateway/current/control_points', self._cp_cb, qos)

        # 订阅 gateway target DOF (校准采样用)
        self._gateway_target_dof = None
        self.create_subscription(
            JointState, '/l10_gateway/target/dof', self._dof_cb, qos)

        # 校准
        self._cal_mode = False
        self._cal_samples = []
        self._cal_cp_models = None  # per-finger CP 修正模型

        # 平滑
        self._smooth_cp = None
        self._smooth_cam = None
        self._alpha = 0.4

        self.timer = self.create_timer(1.0 / hz, self._tick)
        self.get_logger().info(
            f'Hand tracking started (camera={cam_id}, hz={hz}, '
            f'mode=control_points, API={"Task" if USE_TASK_API else "Legacy"})')

    def _init_mediapipe(self):
        if USE_TASK_API:
            model_path = f'{mp.__path__[0]}/tasks/hand_landmarker.task'
            import os
            if not os.path.exists(model_path):
                self.get_logger().info('下载 HandLandmarker 模型...')
                import urllib.request
                urllib.request.urlretrieve(
                    'https://storage.googleapis.com/mediapipe-models/'
                    'hand_landmarker/hand_landmarker/float16/1/'
                    'hand_landmarker.task', model_path)
            base_options = BaseOptions(model_asset_path=model_path)
            options = mp.tasks.vision.HandLandmarkerOptions(
                base_options=base_options, num_hands=1,
                min_hand_detection_confidence=0.5,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self.detector = HandLandmarker.create_from_options(options)
        else:
            self.hands = mp.solutions.hands.Hands(
                static_image_mode=False, max_num_hands=1,
                min_detection_confidence=0.7, min_tracking_confidence=0.5,
                model_complexity=1)

    def _cp_cb(self, msg):
        if len(msg.poses) >= 5:
            self._current_cp = [
                np.array([p.position.x, p.position.y, p.position.z])
                for p in msg.poses[:5]
            ]

    def _dof_cb(self, msg):
        """订阅 gateway target DOF (校准采样用)"""
        if len(msg.position) >= 10:
            self._gateway_target_dof = [float(v) for v in msg.position[:10]]

    def _tick(self):
        """定时器回调 —— 每帧执行一次完整的检测-映射-发布-渲染流水线。

        流水线步骤:
        1. 读取摄像头帧并水平镜像（自拍视角）
        2. MediaPipe 手部关键点检测
        3. 处理 OpenCV 窗口键盘输入（校准控制）
        4. 若无检测结果则显示提示并返回
        5. 右手关键点沿 x=0.5 轴镜像
        6. 计算各手指弯曲比 (curls)
        7. 通过 landmarks→DOF→FK 管道计算 5 个指尖控制点
        8. 若有校准模型，对控制点施加分段线性修正
        9. EMA 平滑（alpha=0.4）
        10. 发布控制点和相机命令到 ROS 话题
        11. 渲染 OpenCV 调试窗口
        """
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.flip(frame, 1)  # 镜像（自拍视角）
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._detect_full(rgb)

        # ---- 键盘交互处理 ----
        key = cv2.waitKey(1) & 0xFF
        if key == ord('c') or key == ord('C'):
            # C 键: 切换校准模式（进入/完成并构建模型）
            if self._cal_mode:
                if self._cal_samples:
                    self._cal_cp_models = _build_cp_calibration(self._cal_samples)
                    if self._cal_cp_models:
                        self.get_logger().info(
                            f'Calibration: {len(self._cal_samples)} samples -> '
                            f'CP correction models built')
                    else:
                        self.get_logger().warn('Calibration failed')
                self._cal_mode = False
            else:
                self._cal_mode = True
                self._cal_samples = []
                self.get_logger().info('Entered calibration mode')
        elif key == ord(' ') and self._cal_mode:
            # Space 键: 在校准模式下采样当前手势
            # 记录 curl 值和 CP 差分 (gateway正确值 - 原始映射值) 用于构建修正表
            if result is not None:
                landmarks = result["landmarks"]
                if result["handedness"] == "Right":
                    landmarks = mirror_landmarks_x(landmarks)
                curls = compute_finger_curls(landmarks)
                if self._gateway_target_dof is not None:
                    raw_cp = landmarks_to_control_points(
                        landmarks, self._current_cp, 640, 480)
                    correct_cp = _fk_control_points(self._gateway_target_dof)
                    # 计算全部 5 指的 3D delta（正确值 - 原始值）
                    cp_delta = [
                        (correct_cp[fi] - raw_cp[fi]).tolist()
                        for fi in range(5)
                    ]
                    self._cal_samples.append({
                        'curls': curls,
                        'cp_delta': cp_delta,
                    })
                    dy_str = ', '.join(f'{cp_delta[fi][1]:+.4f}' for fi in range(5))
                    self.get_logger().info(
                        f'Sample {len(self._cal_samples)}: '
                        f'curls=[{curls[0]:.2f},{curls[1]:.2f},{curls[2]:.2f},'
                        f'{curls[3]:.2f},{curls[4]:.2f}] dY=[{dy_str}]')
                else:
                    self.get_logger().warn('No gateway target DOF yet - wait for gateway')
            else:
                self.get_logger().warn('No hand detected - cannot sample')

        # ---- 无手部检测时显示提示 ----
        if result is None:
            cv2.putText(frame, "No hand detected", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            if self._cal_mode:
                self._draw_cal_overlay(frame)
            cv2.imshow('L10 Hand Tracking', frame)
            return

        # ---- 关键点提取与镜像 ----
        landmarks = result["landmarks"]
        handedness = result["handedness"]
        fh, fw = frame.shape[:2]

        # 右手沿画面中轴 (x=0.5) 水平镜像，使屏幕左右与真实方向对应
        if handedness == "Right":
            landmarks = mirror_landmarks_x(landmarks)

        # ---- 弯曲度计算 ----
        curls = compute_finger_curls(landmarks)

        # ---- 控制点计算: landmarks → DOF → FK → control_points ----
        # 有校准模型时: raw_CP + 分段线性修正 delta
        # 无校准模型时: 直接使用原始 DOF→FK 映射
        if self._cal_cp_models:
            raw_cp = landmarks_to_control_points(
                landmarks, self._current_cp, fw, fh)
            targets = _apply_cp_calibration(raw_cp, curls, self._cal_cp_models)
        else:
            targets = landmarks_to_control_points(
                landmarks, self._current_cp, fw, fh)

        # ---- 调试日志: 每 30 帧输出一次 curl/lateral/CP_Y 数值 ----
        if not hasattr(self, '_dbg_cnt'):
            self._dbg_cnt = 0
        self._dbg_cnt += 1
        if self._dbg_cnt % 30 == 0:
            mid_x = landmarks[12][0]
            mcp_span = abs(landmarks[5][0] - landmarks[17][0]) + 1e-6
            lat_s = 3.0 / mcp_span
            lat_idx = min(255.0, max(0.0, 255.0 * (mid_x - landmarks[8][0]) * lat_s))
            lat_rng = min(255.0, max(0.0, 255.0 * (landmarks[16][0] - mid_x) * lat_s))
            lat_lit = min(255.0, max(0.0, 255.0 * (landmarks[20][0] - mid_x) * lat_s))
            self.get_logger().info(
                f"curl=[{curls[0]:.2f},{curls[1]:.2f},{curls[2]:.2f},{curls[3]:.2f},{curls[4]:.2f}] "
                f"lat=[{lat_idx:.0f},{lat_rng:.0f},{lat_lit:.0f}] "
                f"CP_Y=[{targets[0][1]:.3f},{targets[1][1]:.3f},{targets[2][1]:.3f},{targets[3][1]:.3f},{targets[4][1]:.3f}]")

        # ---- EMA 指数移动平均平滑 (alpha=0.4) ----
        # 公式: smooth = alpha * new + (1 - alpha) * prev
        # alpha 越大跟踪越灵敏但越抖动，越小越平滑但延迟越大
        if self._smooth_cp is None:
            self._smooth_cp = [t.copy() for t in targets]
        else:
            for i in range(5):
                self._smooth_cp[i] = (
                    self._alpha * targets[i] + (1 - self._alpha) * self._smooth_cp[i])

        # ---- 发布控制点 (校准模式下暂停发布) ----
        if not self._cal_mode:
            cp_msg = PoseArray()
            cp_msg.header.stamp = self.get_clock().now().to_msg()
            cp_msg.header.frame_id = "world"
            for pt in self._smooth_cp:
                p = Pose()
                p.position.x = float(pt[0])
                p.position.y = float(pt[1])
                p.position.z = float(pt[2])
                p.orientation.w = 1.0
                cp_msg.poses.append(p)
            self.pub_cp.publish(cp_msg)

        # ---- 计算并发布相机命令 (校准模式下暂停发布) ----
        if not self._cal_mode:
            pts_3d = landmarks_to_3d(
                [np.array(lm) for lm in landmarks], fw, fh)
            camera = compute_camera_cmd(pts_3d)
            # 相机命令同样做 EMA 平滑
            if self._smooth_cam is None:
                self._smooth_cam = camera[:]
            else:
                self._smooth_cam = [
                    self._alpha * c + (1 - self._alpha) * s
                    for c, s in zip(camera, self._smooth_cam)]
            cam_msg = Float32MultiArray()
            cam_msg.data = self._smooth_cam
            self.pub_camera.publish(cam_msg)

        # ---- OpenCV 可视化渲染 ----
        # 用未镜像的原始 landmarks 绘制（因为 frame 已经做了水平翻转）
        draw_tracking(frame, result["landmarks"], handedness, self._smooth_cp, curls)
        if self._cal_mode:
            self._draw_cal_overlay(frame, landmarks)
        cv2.imshow('L10 Hand Tracking', frame)

    def _draw_cal_overlay(self, img, landmarks=None):
        """校准模式 UI 叠加"""
        h, w = img.shape[:2]

        # 横幅
        cv2.rectangle(img, (0, 0), (w, 50), (0, 0, 180), -1)
        cv2.putText(img, "CALIBRATION MODE", (10, 35),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2)

        # 操作提示
        y = 65
        cv2.putText(img, "C=finish&save  SPACE=sample", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 20
        cv2.putText(img, f"Samples: {len(self._cal_samples)}", (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (200, 200, 200), 1)
        y += 20

        # gateway DOF + 当前 CP delta
        if self._gateway_target_dof is not None and landmarks:
            gw_dof = self._gateway_target_dof
            raw_cp = landmarks_to_control_points(landmarks, None, 640, 480)
            correct_cp = _fk_control_points(gw_dof)
            curl_str = ', '.join(f'{v:.2f}' for v in compute_finger_curls(landmarks))
            cv2.putText(img, f"curl: [{curl_str}]", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)
            y += 16
            for fi, name in enumerate(['Thb', 'Idx', 'Mid', 'Rng', 'Lit']):
                d = correct_cp[fi] - raw_cp[fi]
                cv2.putText(img, f"{name} dY={d[1]:+.4f} dZ={d[2]:+.4f}", (10, y),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.3, (0, 200, 200), 1)
                y += 14
        elif landmarks:
            curl_str = ', '.join(f'{v:.2f}' for v in compute_finger_curls(landmarks))
            cv2.putText(img, f"curl: [{curl_str}]", (10, y),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.35, (180, 180, 180), 1)

    def _detect_full(self, rgb):
        if USE_TASK_API:
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
            results = self.detector.detect(mp_image)
            if not results.hand_landmarks:
                return None
            lm = [(l.x, l.y, l.z) for l in results.hand_landmarks[0]]
            hand_label = "Right"
            if results.handedness:
                hand_label = results.handedness[0][0].category_name
            return {"landmarks": lm, "handedness": hand_label}
        else:
            results = self.hands.process(rgb)
            if not results.multi_hand_landmarks:
                return None
            lm = [(l.x, l.y, l.z) for l in results.multi_hand_landmarks[0].landmark]
            hand_label = "Right"
            if results.multi_handedness:
                hand_label = results.multi_handedness[0].classification[0].label
            return {"landmarks": lm, "handedness": hand_label}

    def destroy_node(self):
        if hasattr(self, 'cap') and self.cap.isOpened():
            self.cap.release()
        if USE_TASK_API and hasattr(self, 'detector'):
            self.detector.close()
        elif hasattr(self, 'hands'):
            self.hands.close()
        cv2.destroyAllWindows()
        super().destroy_node()


def main(args=None):
    rclpy.init(args=args)
    node = HandTrackingNode()
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
