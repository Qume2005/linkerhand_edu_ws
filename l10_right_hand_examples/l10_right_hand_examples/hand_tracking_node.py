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
from std_msgs.msg import Float32MultiArray


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

# MuJoCo FK 预计算 — DOF=255 → 最小弯曲角 → 手指伸直 (OPEN)
OPEN_CP = [
    np.array([ 0.076898,  0.078129, -0.012645]),  # thumb
    np.array([-0.015782,  0.047445,  0.201153]),  # index
    np.array([-0.017768,  0.009260,  0.210050]),  # middle
    np.array([-0.015782, -0.019550,  0.205110]),  # ring
    np.array([-0.013782, -0.048284,  0.198894]),  # little
]

# MuJoCo FK 预计算 — DOF=0 → 最大弯曲角 → 手指蜷缩 (CLOSED)
CLOSED_CP = [
    np.array([ 0.061497, -0.025504,  0.127239]),  # thumb
    np.array([ 0.043035,  0.028260,  0.134520]),  # index
    np.array([ 0.041050,  0.009260,  0.139515]),  # middle
    np.array([ 0.043035, -0.009740,  0.134520]),  # ring
    np.array([ 0.045035, -0.028740,  0.129520]),  # little
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


def compute_camera_cmd(pts_3d):
    """手掌法向量 + 距离 → MuJoCo 相机 [distance, nx, ny, nz]"""
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
    for joints in FINGER_JOINTS:
        v1 = lm[joints[1]][:2] - lm[joints[0]][:2]  # 首段: e.g. MCP→PIP
        v2 = lm[joints[3]][:2] - lm[joints[2]][:2]  # 末段: e.g. DIP→TIP
        cos_a = np.dot(v1, v2) / (np.linalg.norm(v1) * np.linalg.norm(v2) + 1e-8)
        curls.append(float(np.clip((1.0 - cos_a) / 2.0, 0.0, 1.0)))
    return curls


def landmarks_to_control_points(landmarks, current_cp, frame_w, frame_h):
    """
    MediaPipe 21 关键点 → 5 个 MuJoCo 控制点 (3D meters)

    映射逻辑:
    1. 计算每根手指的弯曲比 (0=伸直, 1=蜷缩)
    2. 在 OPEN_CP (伸直) 和 CLOSED_CP (蜷缩) 之间线性插值
    3. IK solver 自动将插值位置转换为 DOF
    """
    curls = compute_finger_curls(landmarks)

    targets = []
    for i in range(5):
        target = OPEN_CP[i] * (1.0 - curls[i]) + CLOSED_CP[i] * curls[i]
        targets.append(target)

    return targets


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

        self.cap = cv2.VideoCapture(cam_id)
        if not self.cap.isOpened():
            self.get_logger().error(f'无法打开摄像头 (camera_id={cam_id})')
            raise SystemExit(1)
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

    def _tick(self):
        ret, frame = self.cap.read()
        if not ret:
            return

        frame = cv2.flip(frame, 1)  # 镜像
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        result = self._detect_full(rgb)

        if result is None:
            cv2.putText(frame, "No hand detected", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            cv2.imshow('L10 Hand Tracking', frame)
            cv2.waitKey(1)
            return

        landmarks = result["landmarks"]
        handedness = result["handedness"]
        fh, fw = frame.shape[:2]

        # 右手沿画面中轴镜像
        if handedness == "Right":
            landmarks = mirror_landmarks_x(landmarks)

        # 1. 控制点
        targets = landmarks_to_control_points(
            landmarks, self._current_cp, fw, fh)
        curls = compute_finger_curls(landmarks)

        # EMA 平滑
        if self._smooth_cp is None:
            self._smooth_cp = [t.copy() for t in targets]
        else:
            for i in range(5):
                self._smooth_cp[i] = (
                    self._alpha * targets[i] + (1 - self._alpha) * self._smooth_cp[i])

        # 发布控制点
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

        # 2. 相机
        pts_3d = landmarks_to_3d(
            [np.array(lm) for lm in landmarks], fw, fh)
        camera = compute_camera_cmd(pts_3d)
        if self._smooth_cam is None:
            self._smooth_cam = camera[:]
        else:
            self._smooth_cam = [
                self._alpha * c + (1 - self._alpha) * s
                for c, s in zip(camera, self._smooth_cam)]
        cam_msg = Float32MultiArray()
        cam_msg.data = self._smooth_cam
        self.pub_camera.publish(cam_msg)

        # 3. 可视化 (用原始 landmarks)
        draw_tracking(frame, result["landmarks"], handedness, self._smooth_cp, curls)
        cv2.imshow('L10 Hand Tracking', frame)
        cv2.waitKey(1)

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
        rclpy.shutdown()


if __name__ == '__main__':
    main()
