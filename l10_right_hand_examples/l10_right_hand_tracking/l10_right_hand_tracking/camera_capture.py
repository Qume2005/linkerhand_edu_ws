"""摄像头后台采集模块 —— 镜像 RPS (GestureDetector) 的采集模式。

在独立守护线程中持续读取摄像头帧并缓存「最新帧」，供主循环（ROS 定时器）
轮询。打开/读帧失败时不抛异常，仅记日志（与 RPS 行为一致），调用方通过
``get_frame()`` 返回 ``None`` 判定「等待摄像头」状态。

驱动方式与 RPS 对齐：使用普通 ``cv2.VideoCapture(camera_id)``，不显式指定
V4L2 后端、MJPG 或分辨率，规避 OpenCV 自带 Qt 插件与系统 Qt5 的依赖冲突。
"""

import logging
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


class CameraCapture:
    """后台线程摄像头采集器。

    用法::

        cap = CameraCapture(camera_id=0)
        cap.start()
        frame = cap.get_frame()   # None 表示摄像头尚未就绪
        ...
        cap.stop()
    """

    def __init__(self, camera_id: int = 0):
        self._camera_id = camera_id
        self._cap: cv2.VideoCapture | None = None
        self._latest_frame: np.ndarray | None = None
        self._lock = threading.Lock()
        self._running = False
        self._thread: threading.Thread | None = None
        self._opened = False

    def start(self) -> None:
        """启动后台采集线程。"""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()
        logger.info("摄像头采集线程已启动 (camera_id=%d)", self._camera_id)

    def stop(self) -> None:
        """停止采集并释放摄像头。"""
        self._running = False
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._cap is not None and self._cap.isOpened():
            self._cap.release()
            self._cap = None
        self._opened = False
        logger.info("摄像头采集已停止")

    def get_frame(self) -> np.ndarray | None:
        """返回最新帧副本；摄像头尚未就绪时返回 ``None``。"""
        with self._lock:
            return self._latest_frame.copy() if self._latest_frame is not None else None

    def is_opened(self) -> bool:
        """摄像头是否已成功打开。"""
        return self._opened

    def _capture_loop(self) -> None:
        """后台采集循环（守护线程）。"""
        # 与 RPS 对齐：普通方式打开，不指定 V4L2/MJPG/分辨率
        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
            # 不崩溃：仅记日志，调用方通过 get_frame()==None 显示等待画面
            logger.error("无法打开摄像头 (camera_id=%d)", self._camera_id)
            self._running = False
            return
        self._opened = True

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                time.sleep(0.01)
                continue
            with self._lock:
                self._latest_frame = frame

        if self._cap is not None:
            self._cap.release()
            self._cap = None
        self._opened = False
