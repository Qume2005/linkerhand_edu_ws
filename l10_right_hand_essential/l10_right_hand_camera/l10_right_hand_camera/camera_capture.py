"""摄像头后台采集模块 —— 共享包（被 tracking 和 RPS 共用）。

在独立守护线程中持续读取摄像头帧并缓存「最新帧」，供主循环轮询。
打开/读帧失败时不抛异常，仅记日志，调用方通过 ``get_frame()`` 返回 ``None``
判定「等待摄像头」状态。

自动扫描: ``camera_id=-1``（默认）时自动遍历 0-9 寻找第一个可用的摄像头。
"""

import logging
import threading
import time

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def find_available_camera(max_index: int = 10) -> int:
    """扫描可用的摄像头设备。

    依次尝试 ``cv2.VideoCapture(i)``，返回第一个 ``isOpened()`` 为 True 的索引。
    适合用户不确定摄像头编号时自动发现设备。

    Args:
        max_index: 最大扫描索引（不含），默认扫描 0-9。

    Returns:
        第一个能成功打开的摄像头索引；全部失败返回 -1。
    """
    for i in range(max_index):
        cap = cv2.VideoCapture(i)
        if cap.isOpened():
            cap.release()
            logger.info("找到可用摄像头: /dev/video%d", i)
            return i
        cap.release()
    logger.warning("未找到可用摄像头（扫描范围 0-%d）", max_index - 1)
    return -1


class CameraCapture:
    """后台线程摄像头采集器。

    用法::

        cap = CameraCapture()            # 自动扫描
        cap = CameraCapture(camera_id=2)  # 指定设备
        cap.start()
        frame = cap.get_frame()   # None 表示摄像头尚未就绪
        ...
        cap.stop()
    """

    def __init__(self, camera_id: int = -1):
        """初始化摄像头采集器。

        Args:
            camera_id: 摄像头设备号。传入 -1（默认）时自动扫描 0-9 寻找
                第一个可用摄像头；传入 >=0 时直接使用指定设备。
        """
        if camera_id == -1:
            self._camera_id = find_available_camera()
        else:
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
        if self._camera_id == -1:
            logger.error("无可用摄像头，采集线程退出")
            self._running = False
            return

        self._cap = cv2.VideoCapture(self._camera_id)
        if not self._cap.isOpened():
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
