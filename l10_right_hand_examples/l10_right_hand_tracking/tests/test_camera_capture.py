"""``CameraCapture`` 行为测试。

锁定「与 RPS 对齐」的关键契约：
- 摄像头在后台线程异步采集，主循环通过 ``get_frame()`` 轮询；
- 首帧到来前 ``get_frame()`` 返回 ``None``；
- 摄像头打不开时**不抛异常**（与 RPS 一致），仅由调用方据 ``None`` 判定等待态。

使用不存在的设备号（99）验证「打不开也不崩溃」路径，无需真实摄像头。
"""

import time

from l10_right_hand_camera.camera_capture import CameraCapture

_MISSING_ID = 99  # 本机摄像头通常为 0/1，99 号不存在


def test_get_frame_none_before_start():
    cap = CameraCapture(_MISSING_ID)
    assert cap.get_frame() is None
    assert cap.is_opened() is False


def test_start_is_idempotent():
    cap = CameraCapture(_MISSING_ID)
    cap.start()
    thread1 = cap._thread
    cap.start()  # 重复 start 不应再起线程
    assert cap._thread is thread1
    cap.stop()


def test_missing_camera_does_not_crash():
    """摄像头打不开时：不抛异常、get_frame() 恒为 None、is_opened() 为 False。"""
    cap = CameraCapture(_MISSING_ID)
    cap.start()
    time.sleep(0.5)  # 给后台线程尝试打开的时间
    try:
        assert cap.get_frame() is None
        assert cap.is_opened() is False
    finally:
        cap.stop()


def test_stop_releases_and_is_safe_to_recall():
    cap = CameraCapture(_MISSING_ID)
    cap.start()
    time.sleep(0.3)
    cap.stop()
    cap.stop()  # 重复 stop 不抛异常
    assert cap.get_frame() is None
    assert cap.is_opened() is False
