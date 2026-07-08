"""CameraCapture 摄像头 ID 与自动扫描单元测试。

覆盖:
- 默认 camera_id=-1（自动扫描）
- 显式 camera_id >= 0 不触发扫描
- find_available_camera 扫描逻辑
- 缺失摄像头不崩溃
- start/stop 生命周期
"""

import time
from unittest.mock import patch, MagicMock

import pytest

from l10_right_hand_camera.camera_capture import CameraCapture, find_available_camera


# ---- find_available_camera ----

class TestFindAvailableCamera:
    """自动扫描可用摄像头。"""

    def test_scan_finds_first_available(self):
        """0 可用时返回 0。"""
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [True, False, False]

        with patch('cv2.VideoCapture', return_value=mock_cap) as mock_vc:
            result = find_available_camera(max_index=10)
            assert result == 0
            assert mock_vc.call_count == 1

    def test_scan_skips_unavailable(self):
        """0 不可用、1 可用时返回 1。"""
        mock_cap = MagicMock()
        mock_cap.isOpened.side_effect = [False, True, False]

        with patch('cv2.VideoCapture', return_value=mock_cap) as mock_vc:
            result = find_available_camera(max_index=10)
            assert result == 1
            assert mock_vc.call_count == 2

    def test_scan_returns_minus_one_when_none_available(self):
        """全部不可用时返回 -1。"""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch('cv2.VideoCapture', return_value=mock_cap) as mock_vc:
            result = find_available_camera(max_index=3)
            assert result == -1
            assert mock_vc.call_count == 3

    def test_scan_releases_each_capture(self):
        """每次尝试后都 release，不泄漏。"""
        mock_cap = MagicMock()
        mock_cap.isOpened.return_value = False

        with patch('cv2.VideoCapture', return_value=mock_cap):
            find_available_camera(max_index=3)
            assert mock_cap.release.call_count == 3


# ---- CameraCapture 默认值 ----

class TestCameraIdDefault:
    """默认 camera_id 为 -1（自动扫描）。"""

    def test_default_is_minus_one(self):
        with patch('l10_right_hand_camera.camera_capture.find_available_camera', return_value=-1):
            cap = CameraCapture()
        assert cap._camera_id == -1

    def test_explicit_minus_one(self):
        with patch('l10_right_hand_camera.camera_capture.find_available_camera', return_value=-1):
            cap = CameraCapture(camera_id=-1)
        assert cap._camera_id == -1


class TestCameraIdExplicit:
    """显式指定 camera_id 不触发扫描。"""

    def test_camera_id_0(self):
        cap = CameraCapture(camera_id=0)
        assert cap._camera_id == 0

    def test_camera_id_2(self):
        cap = CameraCapture(camera_id=2)
        assert cap._camera_id == 2


# ---- 生命周期 ----

class TestCameraCaptureLifecycle:
    """start/stop/get_frame 生命周期。"""

    def test_get_frame_none_before_start(self):
        cap = CameraCapture(99)
        assert cap.get_frame() is None
        assert cap.is_opened() is False

    def test_start_is_idempotent(self):
        cap = CameraCapture(99)
        cap.start()
        thread1 = cap._thread
        cap.start()
        assert cap._thread is thread1
        cap.stop()

    def test_missing_camera_does_not_crash(self):
        """camera_id=99 不崩溃，get_frame() 恒为 None。"""
        cap = CameraCapture(99)
        cap.start()
        time.sleep(0.5)
        try:
            assert cap.get_frame() is None
            assert cap.is_opened() is False
        finally:
            cap.stop()

    def test_stop_releases_and_is_safe_to_recall(self):
        cap = CameraCapture(99)
        cap.start()
        time.sleep(0.3)
        cap.stop()
        cap.stop()
        assert cap.get_frame() is None
        assert cap.is_opened() is False
