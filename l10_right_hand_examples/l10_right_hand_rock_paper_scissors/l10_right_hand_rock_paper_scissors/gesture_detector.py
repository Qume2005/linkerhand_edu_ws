"""
手势识别模块 — 基于 MediaPipe 的石头剪刀布手势检测。

核心判定逻辑移植自 references/RockPaperScissor_RightHand.py 的 classify_gesture()。

兼容 MediaPipe 两个 API：
- Legacy API (mp.solutions.hands): 旧版 mediapipe
- Task API (mediapipe.tasks.python.vision): 新版 mediapipe >= 0.10
"""

import logging
import os
import threading
import time
import urllib.request
import zipfile

import cv2
import numpy as np

from l10_right_hand_camera.camera_capture import find_available_camera

logger = logging.getLogger(__name__)

# 手势标签
GESTURE_ROCK = "rock"
GESTURE_PAPER = "paper"
GESTURE_SCISSORS = "scissors"
GESTURE_NONE = "none"

# 检测可用的 MediaPipe API
_USE_LEGACY_API: bool | None = None

try:
    import mediapipe as mp
    _mp_hands = mp.solutions.hands
    _mp_drawing = mp.solutions.drawing_utils
    _mp_connections = mp.solutions.hands_connections
    _USE_LEGACY_API = True
    logger.debug("MediaPipe Legacy API (mp.solutions) 可用")
except AttributeError:
    try:
        import mediapipe as mp
        from mediapipe.tasks.python.vision import HandLandmarker
        from mediapipe.tasks.python.core.base_options import BaseOptions
        _USE_LEGACY_API = False
        logger.debug("MediaPipe Task API 可用")
    except (ImportError, AttributeError):
        _USE_LEGACY_API = None
        logger.error("MediaPipe 不可用，手势识别将无法工作")


class GestureDetector:
    """摄像头 + MediaPipe 石头剪刀布手势识别。

    自动检测系统安装的 MediaPipe 版本，优先使用 Legacy API，
    不可用时降级到 Task API。

    camera_id=-1（默认）时自动扫描 0-9 寻找第一个可用摄像头。
    """

    def __init__(self, camera_id: int = -1):
        if _USE_LEGACY_API is None:
            raise RuntimeError(
                "MediaPipe 不可用，请安装: pip install mediapipe")

        if camera_id == -1:
            camera_id = find_available_camera()
        self._camera_id = camera_id
        self._cap: cv2.VideoCapture | None = None

        if _USE_LEGACY_API:
            self._hands = _mp_hands.Hands(
                static_image_mode=False,
                max_num_hands=1,
                min_detection_confidence=0.6,
                min_tracking_confidence=0.5,
            )
        else:
            # Task API: 模型路径和 API 参照 tracking 例程
            model_path = os.path.join(
                os.path.expanduser("~"), ".local", "share", "mediapipe",
                "tasks", "hand_landmarker.task")
            alternate_model_path = os.path.join(
                mp.__path__[0], "tasks", "hand_landmarker.task")
            os.makedirs(os.path.dirname(model_path), exist_ok=True)
            os.makedirs(os.path.dirname(alternate_model_path), exist_ok=True)

            def _is_valid_model(path: str) -> bool:
                """Check if the .task file is a valid zip archive."""
                if not os.path.isfile(path):
                    return False
                try:
                    with zipfile.ZipFile(path, 'r'):
                        return True
                except zipfile.BadZipFile:
                    return False

            if not _is_valid_model(model_path):
                if os.path.isfile(model_path):
                    os.remove(model_path)
                logger.info("下载 HandLandmarker 模型...")
                download_ok = False
                try:
                    urllib.request.urlretrieve(
                        'https://storage.googleapis.com/mediapipe-models/'
                        'hand_landmarker/hand_landmarker/float16/1/'
                        'hand_landmarker.task', model_path)
                    download_ok = True
                    logger.info("模型下载成功: %s", model_path)
                except Exception as e:
                    logger.error("模型下载失败（网络不可用？）: %s" % e)
                    # 不在此处 raise → 继续到下方最终校验，给出更清晰的错误信息

            if not _is_valid_model(model_path):
                if _is_valid_model(alternate_model_path):
                    logger.warning("主路径模型无效，使用备用路径: %s",
                                   alternate_model_path)
                    model_path = alternate_model_path
                else:
                    raise RuntimeError(
                        "HandLandmarker 模型无效，主路径与备用路径均不可用。\n"
                        "可能原因：\n"
                        "  1. ISO 构建时未正确捆绑模型文件\n"
                        "  2. 网络不可用且模型文件缺失\n"
                        "解决方案：\n"
                        "  - 连接网络后重启程序（将自动下载模型）\n"
                        "  - 或手动将 hand_landmarker.task 放置到以下任一路径：\n"
                        f"    {model_path}\n"
                        f"    {alternate_model_path}"
                    )

            base_options = BaseOptions(model_asset_path=model_path)
            options = mp.tasks.vision.HandLandmarkerOptions(
                base_options=base_options,
                num_hands=1,
                min_hand_detection_confidence=0.6,
                min_hand_presence_confidence=0.5,
                min_tracking_confidence=0.5,
            )
            self._task_detector = HandLandmarker.create_from_options(options)

        self._callback = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self._latest_frame: np.ndarray | None = None
        self._latest_gesture: str = GESTURE_NONE

    def start(self, callback) -> None:
        """启动摄像头采集线程。

        Args:
            callback: 识别回调函数，签名 callback(gesture: str)
        """
        if self._running:
            return

        self._callback = callback
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("手势识别已启动 (camera_id=%d, api=%s)",
                     self._camera_id,
                     "legacy" if _USE_LEGACY_API else "task")

    def stop(self) -> None:
        """停止摄像头采集。"""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None

        if self._cap is not None and self._cap.isOpened():
            self._cap.release()
            self._cap = None
        logger.info("手势识别已停止")

    def get_frame(self) -> np.ndarray | None:
        """获取当前帧（带手势标注），供 UI 显示。"""
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def get_gesture(self) -> str:
        """获取当前识别到的手势。"""
        with self._lock:
            return self._latest_gesture

    def _capture_loop(self) -> None:
        """摄像头采集循环（在独立线程中运行）。"""
        if self._camera_id == -1:
            logger.error("无可用摄像头，采集线程退出")
            self._running = False
            return

        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
            logger.error("无法打开摄像头 (camera_id=%d)", self._camera_id)
            self._running = False
            return

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue

            # 镜像翻转（右手友好）
            frame = cv2.flip(frame, 1)
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

            if _USE_LEGACY_API:
                gesture = self._process_legacy(frame, frame_rgb)
            else:
                gesture = self._process_task(frame, frame_rgb)

            # 在画面上标注手势
            if gesture != GESTURE_NONE:
                label = {"rock": "ROCK", "paper": "PAPER",
                         "scissors": "SCISSORS"}.get(gesture, "")
                cv2.putText(frame, label, (10, 50),
                            cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 255, 0), 3,
                            cv2.LINE_AA)

            with self._lock:
                self._latest_frame = frame
                self._latest_gesture = gesture

            if self._callback is not None and gesture != GESTURE_NONE:
                try:
                    self._callback(gesture)
                except Exception:
                    logger.debug("手势回调异常", exc_info=True)

        if self._cap is not None:
            self._cap.release()

    def _process_legacy(self, frame: np.ndarray, frame_rgb: np.ndarray) -> str:
        """使用 Legacy API 处理一帧。"""
        results = self._hands.process(frame_rgb)
        gesture = GESTURE_NONE

        if results.multi_hand_landmarks:
            for hand_landmarks in results.multi_hand_landmarks:
                _mp_drawing.draw_landmarks(
                    frame, hand_landmarks, _mp_hands.HAND_CONNECTIONS)
                gesture = self._classify(hand_landmarks)

        return gesture

    def _process_task(self, frame: np.ndarray, frame_rgb: np.ndarray) -> str:
        """使用 Task API 处理一帧。"""
        import mediapipe as _mp
        mp_image = _mp.Image(image_format=_mp.ImageFormat.SRGB, data=frame_rgb)
        results = self._task_detector.detect(mp_image)
        gesture = GESTURE_NONE

        if results.hand_landmarks:
            for hand_landmarks in results.hand_landmarks:
                # Task API 返回 list[NormalizedLandmark]，需要包装为 _Landmarks 适配 _classify
                landmarks_obj = _LandmarkWrapper(hand_landmarks)
                gesture = self._classify(landmarks_obj)

                # 简易绘制关键点
                h, w = frame.shape[:2]
                for lm in hand_landmarks:
                    cx, cy = int(lm.x * w), int(lm.y * h)
                    cv2.circle(frame, (cx, cy), 3, (0, 255, 0), -1)

        return gesture

    @staticmethod
    def _classify(landmarks) -> str:
        """基于参考文件的 classify_gesture()，返回手势名称。

        判定逻辑：
        - Rock:     4 根手指 tip-to-wrist < pip-to-wrist（全部弯曲）
        - Paper:    4 根手指 tip-to-wrist > pip-to-wrist（全部伸直）
        - Scissors: index+middle 伸直, ring+little 弯曲, index-middle spread > 0.06
        """
        def _distance(a, b) -> float:
            return ((a.x - b.x) ** 2 + (a.y - b.y) ** 2) ** 0.5

        lm = landmarks.landmark

        # 各手指 tip-to-wrist 距离
        d_tip = {
            "index":  _distance(lm[8],  lm[0]),
            "middle": _distance(lm[12], lm[0]),
            "ring":   _distance(lm[16], lm[0]),
            "little": _distance(lm[20], lm[0]),
        }

        # 各手指 pip-to-wrist 距离（用于判断是否伸直）
        d_pip = {
            "index":  _distance(lm[6],  lm[0]),
            "middle": _distance(lm[10], lm[0]),
            "ring":   _distance(lm[14], lm[0]),
            "little": _distance(lm[18], lm[0]),
        }

        # 各手指是否伸直
        extended = {f: d_tip[f] > d_pip[f] for f in d_tip}

        # index-middle 分开度（剪刀特有）
        spread = _distance(lm[8], lm[12])

        # 优先判定剪刀（需要 index+middle 伸直且分开）
        if (extended["index"] and extended["middle"]
                and not extended["ring"] and not extended["little"]
                and spread > 0.06):
            return GESTURE_SCISSORS

        # 布：全部伸直
        if all(extended.values()):
            return GESTURE_PAPER

        # 石头：全部弯曲
        if not any(extended.values()):
            return GESTURE_ROCK

        return GESTURE_NONE


class _LandmarkWrapper:
    """将 Task API 的 list[NormalizedLandmark] 包装为兼容 _classify 的对象。"""

    def __init__(self, landmarks_list):
        self.landmark = landmarks_list