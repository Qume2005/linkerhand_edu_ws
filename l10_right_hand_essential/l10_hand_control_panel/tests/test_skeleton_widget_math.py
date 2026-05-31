#!/usr/bin/env python3
"""skeleton_widget.py 纯数学函数测试。

通过直接提取方法逻辑测试核心数学函数，不依赖 HandModelWidget 实例化：
- camera 法向量计算 (_compute_camera_normal)
- camera 状态往返 (apply_camera_state)
- 回声防护逻辑
- DOF 值钳制 (set_dof_values)
"""

import math
import os
import sys
import unittest
from unittest.mock import MagicMock

# ── 全部 mock: PySide2 + MuJoCo + FK + linker_hand_description ──
for mod_name in [
    'PySide2', 'PySide2.QtCore', 'PySide2.QtGui', 'PySide2.QtWidgets',
    'mujoco',
    'hand_forward_kinematics', 'hand_forward_kinematics.kinematics',
    'linker_hand_description',
]:
    sys.modules.setdefault(mod_name, MagicMock())

from l10_hand_control_panel.skeleton_widget import HandModelWidget


def _compute_camera_normal(cam):
    """从 skeleton_widget 提取的 _compute_camera_normal 逻辑。"""
    azim = math.radians(cam.azimuth)
    elev = math.radians(cam.elevation)
    ce = math.cos(elev)
    se = math.sin(elev)
    ca = math.cos(azim)
    sa = math.sin(azim)
    return [ce * ca, ce * sa, se]


def _apply_camera_state(cam, camera_data, echo_guard):
    """从 skeleton_widget 提取的 apply_camera_state 逻辑。

    Returns updated (azimuth, elevation, distance, new_echo_guard).
    """
    if len(camera_data) < 4:
        return cam.azimuth, cam.elevation, cam.distance, echo_guard

    # 回声检测
    if echo_guard is not None:
        diff = sum(abs(a - b) for a, b in zip(camera_data, echo_guard))
        if diff < 0.001:
            return cam.azimuth, cam.elevation, cam.distance, echo_guard

    dist = camera_data[0]
    nx, ny, nz = camera_data[1], camera_data[2], camera_data[3]
    nz_clamped = max(-1.0, min(1.0, nz))
    elevation = math.degrees(math.asin(nz_clamped))
    ce = math.cos(math.radians(elevation))
    if abs(ce) > 1e-6:
        azimuth = math.degrees(math.atan2(ny / ce, nx / ce))
    else:
        azimuth = cam.azimuth
    distance = max(0.1, min(1.0, dist))

    cam.azimuth = azimuth
    cam.elevation = elevation
    cam.distance = distance
    return azimuth, elevation, distance, None


def _set_dof_values(dof_values, values_10):
    """从 skeleton_widget 提取的 set_dof_values 逻辑。"""
    return [max(0, min(255, int(round(v)))) for v in values_10]


def _emit_camera_state(cam, on_camera_changed):
    """从 skeleton_widget 提取的 _emit_camera_state 逻辑。

    Returns (camera_data, echo_guard).
    """
    normal = _compute_camera_normal(cam)
    data = [cam.distance, normal[0], normal[1], normal[2]]
    return data, data


class _Cam:
    """简单的相机状态容器。"""
    def __init__(self, azimuth=-185.0, elevation=-25.0, distance=0.45, lookat=None):
        self.azimuth = azimuth
        self.elevation = elevation
        self.distance = distance
        self.lookat = lookat or [0, 0, 0.08]


# ══════════════════════════════════════════════════════════════════════
# 1. Camera Normal 计算
# ══════════════════════════════════════════════════════════════════════


class TestComputeCameraNormal(unittest.TestCase):
    """_compute_camera_normal: azimuth/elevation → forward 向量。

    公式: forward = [cos(elev)*cos(azim), cos(elev)*sin(azim), sin(elev)]
    """

    def test_zero_azimuth_zero_elevation(self):
        n = _compute_camera_normal(_Cam(azimuth=0, elevation=0))
        self.assertAlmostEqual(n[0], 1.0, places=5)
        self.assertAlmostEqual(n[1], 0.0, places=5)
        self.assertAlmostEqual(n[2], 0.0, places=5)

    def test_90_azimuth_zero_elevation(self):
        n = _compute_camera_normal(_Cam(azimuth=90, elevation=0))
        self.assertAlmostEqual(n[0], 0.0, places=5)
        self.assertAlmostEqual(n[1], 1.0, places=5)
        self.assertAlmostEqual(n[2], 0.0, places=5)

    def test_zero_azimuth_90_elevation(self):
        n = _compute_camera_normal(_Cam(azimuth=0, elevation=90))
        self.assertAlmostEqual(n[0], 0.0, places=5)
        self.assertAlmostEqual(n[1], 0.0, places=5)
        self.assertAlmostEqual(n[2], 1.0, places=5)

    def test_negative_elevation(self):
        n = _compute_camera_normal(_Cam(azimuth=0, elevation=-25))
        self.assertLess(n[2], 0.0, "z component should be negative for negative elevation")

    def test_result_is_unit_vector(self):
        """对任意角度，结果模长近似为 1。"""
        for az, el in [(-185, -25), (0, 0), (45, 45), (90, -30), (180, 60)]:
            n = _compute_camera_normal(_Cam(azimuth=az, elevation=el))
            mag = math.sqrt(n[0]**2 + n[1]**2 + n[2]**2)
            self.assertAlmostEqual(mag, 1.0, places=10,
                                   msg=f"az={az}, el={el}: |n|={mag}")


# ══════════════════════════════════════════════════════════════════════
# 2. Camera 状态往返
# ══════════════════════════════════════════════════════════════════════


class TestCameraStateRoundTrip(unittest.TestCase):
    """normal → [distance, nx, ny, nz] → apply_camera_state → 新 normal ≈ 原 normal"""

    def _roundtrip(self, azimuth, elevation, distance):
        cam = _Cam(azimuth=azimuth, elevation=elevation, distance=distance)
        n_orig = _compute_camera_normal(cam)
        camera_data = [distance, n_orig[0], n_orig[1], n_orig[2]]
        _apply_camera_state(cam, camera_data, echo_guard=None)
        n_new = _compute_camera_normal(cam)
        return n_orig, n_new, cam

    def test_roundtrip_default_camera(self):
        n_orig, n_new, cam = self._roundtrip(-185, -25, 0.45)
        for i in range(3):
            self.assertAlmostEqual(n_orig[i], n_new[i], places=4,
                                   msg=f"component {i}")

    def test_roundtrip_front_view(self):
        n_orig, n_new, cam = self._roundtrip(0, 0, 0.5)
        for i in range(3):
            self.assertAlmostEqual(n_orig[i], n_new[i], places=4)

    def test_roundtrip_side_view(self):
        n_orig, n_new, cam = self._roundtrip(90, 0, 0.4)
        for i in range(3):
            self.assertAlmostEqual(n_orig[i], n_new[i], places=4)

    def test_distance_preserved(self):
        _, _, cam = self._roundtrip(-185, -25, 0.45)
        self.assertAlmostEqual(cam.distance, 0.45, places=4)


# ══════════════════════════════════════════════════════════════════════
# 3. 回声防护
# ══════════════════════════════════════════════════════════════════════


class TestCameraEchoGuard(unittest.TestCase):
    """回声防护: _emit_camera_state 记录发布状态 → apply_camera_state 检测回声。"""

    def test_echo_guard_blocks_same_state(self):
        cam = _Cam(azimuth=0, elevation=0, distance=0.5)
        # 模拟 _emit_camera_state
        data, echo_guard = _emit_camera_state(cam, None)
        self.assertIsNotNone(echo_guard)
        # 用相同数据 apply — 应被忽略
        az_before, el_before = cam.azimuth, cam.elevation
        _apply_camera_state(cam, data, echo_guard)
        self.assertEqual(cam.azimuth, az_before)
        self.assertEqual(cam.elevation, el_before)

    def test_echo_guard_allows_different_state(self):
        cam = _Cam(azimuth=0, elevation=0, distance=0.5)
        data, echo_guard = _emit_camera_state(cam, None)
        # 用不同数据 apply
        _apply_camera_state(cam, [0.3, 0.0, 0.0, 1.0], echo_guard)
        # elevation 应该改变 (接近 90)
        self.assertGreater(abs(cam.elevation), 45)

    def test_short_data_ignored(self):
        cam = _Cam(azimuth=0, elevation=0, distance=0.5)
        _apply_camera_state(cam, [0.5, 0.0], None)
        self.assertEqual(cam.azimuth, 0)
        self.assertEqual(cam.elevation, 0)

    def test_echo_guard_cleared_after_accept(self):
        cam = _Cam(azimuth=0, elevation=0, distance=0.5)
        data, echo_guard = _emit_camera_state(cam, None)
        self.assertIsNotNone(echo_guard)
        _, _, _, new_guard = _apply_camera_state(cam, [0.3, 0.0, 0.0, 1.0], echo_guard)
        self.assertIsNone(new_guard)


# ══════════════════════════════════════════════════════════════════════
# 4. DOF 值钳制
# ══════════════════════════════════════════════════════════════════════


class TestSetDofValuesClamping(unittest.TestCase):
    """set_dof_values 将输入钳制到 [0, 255] 并四舍五入为 int。"""

    def test_negative_clamped_to_zero(self):
        result = _set_dof_values([255] * 10, [-1] * 10)
        self.assertEqual(result, [0] * 10)

    def test_over_255_clamped(self):
        result = _set_dof_values([0] * 10, [256] * 10)
        self.assertEqual(result, [255] * 10)

    def test_float_rounded_to_int(self):
        result = _set_dof_values([0] * 10, [127.6] * 10)
        self.assertEqual(result, [128] * 10)

    def test_mixed_boundary(self):
        result = _set_dof_values([0] * 10,
                                 [0, 255, -1, 256, 127.6, 0.4, -100, 300, 128, 64])
        self.assertEqual(result, [0, 255, 0, 255, 128, 0, 0, 255, 128, 64])

    def test_normal_values_pass_through(self):
        values = [0, 64, 128, 192, 255, 10, 20, 30, 40, 50]
        result = _set_dof_values([0] * 10, values)
        self.assertEqual(result, values)


if __name__ == '__main__':
    unittest.main()
