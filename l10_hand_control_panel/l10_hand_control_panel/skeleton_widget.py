#!/usr/bin/env python3
"""
L10 手部 URDF 模型交互控件
使用 MuJoCo 离屏渲染显示 3D 手模型，支持指尖拖拽控制 DOF
"""

import math
import os
import itertools
import numpy as np

from PySide2.QtCore import Qt, QTimer, QPointF
from PySide2.QtGui import QPainter, QImage, QPen, QBrush, QColor
from PySide2.QtWidgets import QWidget

import mujoco

from hand_forward_kinematics.kinematics import (
    range_to_arc_l10_right,
    expand_to_20_joints,
    arc_to_range_l10_right,
    L10_R_MIN,
    L10_R_MAX,
)
from linker_hand_description import get_urdf_path

# ============================================================================
# 控制点定义: 名称 → MuJoCo body ID + 控制的 DOF
# ============================================================================

CONTROL_POINTS = [
    {"name": "thumb_tip",    "geom_id": 6,  "dofs": [0, 1, 9],     "color": QColor(255, 102, 102, 200)},
    {"name": "index_tip",    "geom_id": 11, "dofs": [2, 6],        "color": QColor(102, 255, 102, 200)},
    {"name": "middle_tip",   "geom_id": 15, "dofs": [3],           "color": QColor(102, 102, 255, 200)},
    {"name": "ring_tip",     "geom_id": 20, "dofs": [4, 7],        "color": QColor(255, 255, 102, 200)},
    {"name": "little_tip",   "geom_id": 25, "dofs": [5, 8],        "color": QColor(255, 102, 255, 200)},
]


class HandModelWidget(QWidget):
    """MuJoCo 离屏渲染的手部模型交互控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.dof_values = [255] * 10
        self.on_dof_changed = None
        self.on_camera_changed = None
        self._suppress_sync = False
        self._dirty = True
        self._camera_echo_guard = None  # 防回声: 最近发布的相机状态

        # ---- MuJoCo 模型 ----
        xml_path = get_urdf_path()
        self._model = mujoco.MjModel.from_xml_path(xml_path)
        self._model.dof_damping[:] = 0.8
        self._data = mujoco.MjData(self._model)
        self._data.qpos[:] = 0
        self._data.qvel[:] = 0

        # ---- 渲染器 ----
        self._render_w, self._render_h = 640, 480
        self._renderer = mujoco.Renderer(self._model, self._render_h, self._render_w)

        # ---- 摄像机 ----
        self._cam = mujoco.MjvCamera()
        mujoco.mjv_defaultFreeCamera(self._model, self._cam)
        self._cam.type = mujoco.mjtCamera.mjCAMERA_FREE
        self._cam.lookat[:] = [0, 0, 0.08]
        self._cam.distance = 0.25
        self._cam.azimuth = -135
        self._cam.elevation = -25

        # ---- 缓存 ----
        self._qimage = None
        self._cp_screen = [QPointF() for _ in CONTROL_POINTS]  # 控制点屏幕坐标

        # ---- 交互状态 ----
        self._drag_cp = None       # 拖拽的控制点索引
        self._drag_offset = None   # 拖拽偏移 (控制点 - 鼠标)
        self._drag_arc = None      # 拖拽期间高精度弧度值
        self._drag_prev_target = None  # 轨迹预测: 上次目标位置
        self._drag_velocity = np.array([0.0, 0.0])  # 轨迹预测: 平滑速度
        self._hover_cp = None      # 悬停的控制点索引
        self._rotating = False     # 右键旋转
        self._rot_last = None

        self.setMinimumSize(300, 400)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

        # 首次渲染
        self._sync_mujoco()
        self._do_render()

        # 渲染定时器 30 FPS
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(33)

    # ==== 公共接口 ====

    def set_dof_values(self, values_10):
        self._suppress_sync = True
        try:
            self.dof_values = [max(0, min(255, int(round(v)))) for v in values_10]
            self._dirty = True
        finally:
            self._suppress_sync = False

    # ==== MuJoCo 同步 ====

    def _sync_mujoco(self):
        """将 DOF 值同步到 MuJoCo qpos"""
        if self._drag_arc is not None:
            # 拖拽期间使用高精度浮点弧度值
            joints_20 = expand_to_20_joints(self._drag_arc)
        else:
            arc = range_to_arc_l10_right(self.dof_values)
            joints_20 = expand_to_20_joints(arc)
        self._data.qpos[:] = joints_20
        self._data.qvel[:] = 0
        mujoco.mj_forward(self._model, self._data)

    def _sync_mujoco_custom(self, arc_10):
        """用给定的 10 DOF 弧度值设置 qpos 并前推"""
        joints_20 = expand_to_20_joints(arc_10)
        self._data.qpos[:] = joints_20
        self._data.qvel[:] = 0
        mujoco.mj_forward(self._model, self._data)

    # ==== 投影 ====

    def _project(self, pos_3d):
        """3D 世界坐标 → 屏幕 QPointF"""
        azim = math.radians(self._cam.azimuth)
        elev = math.radians(self._cam.elevation)
        lookat = np.array(self._cam.lookat)
        dist = self._cam.distance

        ca = math.cos(azim)
        sa = math.sin(azim)
        ce = math.cos(elev)
        se = math.sin(elev)
        forward = np.array([ce * ca, ce * sa, se])
        cam_pos = lookat - dist * forward

        forward = lookat - cam_pos
        forward /= np.linalg.norm(forward)
        world_up = np.array([0.0, 0.0, 1.0])
        right = np.cross(forward, world_up)
        rn = np.linalg.norm(right)
        if rn < 1e-6:
            right = np.array([1.0, 0.0, 0.0])
        else:
            right /= rn
        up = np.cross(right, forward)
        up /= np.linalg.norm(up)

        rel = pos_3d - cam_pos
        x = float(np.dot(rel, right))
        y = float(np.dot(rel, up))
        z = float(np.dot(rel, forward))

        if z < 0.001:
            return None

        fovy = self._model.vis.global_.fovy
        f = self._render_h / (2 * math.tan(math.radians(fovy / 2)))

        sx = self._render_w / 2 + x * f / z
        sy = self._render_h / 2 - y * f / z

        # 缩放到 widget 尺寸
        sx *= self.width() / self._render_w
        sy *= self.height() / self._render_h

        return QPointF(sx, sy)

    def _project_geom(self, geom_id):
        """投影 MuJoCo geom 位置到屏幕"""
        return self._project(self._data.geom_xpos[geom_id])

    def _project_geom_custom(self, geom_id):
        """投影当前 qpos 状态下的 geom 位置 (调用者已 sync)"""
        return self._project(self._data.geom_xpos[geom_id])

    def _update_cp_positions(self):
        """更新所有控制点屏幕坐标"""
        for i, cp in enumerate(CONTROL_POINTS):
            pos = self._project_geom(cp["geom_id"])
            self._cp_screen[i] = pos if pos is not None else QPointF(-100, -100)

    # ==== 渲染 ====

    def _do_render(self):
        """执行 MuJoCo 离屏渲染"""
        self._renderer.update_scene(self._data, camera=self._cam)
        img = self._renderer.render()
        # RGB → BGR for QImage Format_RGB888
        self._qimage = QImage(img.data, self._render_w, self._render_h,
                              3 * self._render_w, QImage.Format_RGB888).copy()
        self._update_cp_positions()

    def _tick(self):
        if self._dirty:
            self._sync_mujoco()
            self._do_render()
            self._dirty = False
            self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)

        # 绘制 MuJoCo 渲染图像
        if self._qimage is not None:
            p.drawImage(self.rect(), self._qimage)
        else:
            p.fillRect(self.rect(), QColor("#2d2d2d"))

        # 绘制控制点
        for i, cp in enumerate(CONTROL_POINTS):
            pos = self._cp_screen[i]
            if pos.x() < 0:
                continue
            r = 10
            if i == self._drag_cp:
                p.setPen(QPen(QColor(255, 255, 255), 2.5))
                p.setBrush(QBrush(cp["color"]))
                p.drawEllipse(pos, r + 4, r + 4)
            elif i == self._hover_cp:
                p.setPen(QPen(QColor(220, 220, 220), 2))
                p.setBrush(QBrush(QColor(cp["color"].red(), cp["color"].green(),
                                          cp["color"].blue(), 220)))
                p.drawEllipse(pos, r + 2, r + 2)
            else:
                p.setPen(QPen(QColor(255, 255, 255, 160), 1.5))
                p.setBrush(QBrush(cp["color"]))
                p.drawEllipse(pos, r, r)

        p.end()

    # ==== 鼠标交互 ====

    def _hit_test(self, screen_pos):
        best_dist, best = 16.0, None
        for i, cp in enumerate(CONTROL_POINTS):
            pos = self._cp_screen[i]
            if pos.x() < 0:
                continue
            d = math.sqrt((screen_pos.x() - pos.x())**2 + (screen_pos.y() - pos.y())**2)
            if d < best_dist:
                best_dist, best = d, i
        return best

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            cp = self._hit_test(event.pos())
            if cp is not None:
                self._drag_cp = cp
                self._drag_offset = QPointF(
                    self._cp_screen[cp].x() - event.pos().x(),
                    self._cp_screen[cp].y() - event.pos().y(),
                )
                self._drag_arc = list(range_to_arc_l10_right(self.dof_values))
                self._drag_prev_target = None
                self._drag_velocity = np.array([0.0, 0.0])
                self.setCursor(Qt.ClosedHandCursor)
                self.update()
        elif event.button() == Qt.RightButton:
            self._rotating = True
            self._rot_last = QPointF(event.pos())
            self.setCursor(Qt.SizeAllCursor)

    def mouseMoveEvent(self, event):
        if self._drag_cp is not None and self._drag_offset is not None:
            target = QPointF(
                event.pos().x() + self._drag_offset.x(),
                event.pos().y() + self._drag_offset.y(),
            )
            self._ik_solve(self._drag_cp, target)
        elif self._rotating and self._rot_last is not None:
            cur = QPointF(event.pos())
            dx = cur.x() - self._rot_last.x()
            dy = cur.y() - self._rot_last.y()
            self._rot_last = cur
            self._rotate_camera(dx, dy)
        else:
            cp = self._hit_test(event.pos())
            if cp != self._hover_cp:
                self._hover_cp = cp
                self.setCursor(Qt.OpenHandCursor if cp is not None else Qt.ArrowCursor)
                self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._drag_cp = None
            self._drag_offset = None
            self._drag_arc = None
            self._drag_prev_target = None
            self._drag_velocity = np.array([0.0, 0.0])
            self.setCursor(Qt.ArrowCursor)
            self.update()
        elif event.button() == Qt.RightButton:
            self._rotating = False
            self._rot_last = None
            self.setCursor(Qt.ArrowCursor)

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        factor = 0.9 if delta > 0 else 1.1
        self._cam.distance = max(0.1, min(1.0, self._cam.distance * factor))
        self._dirty = True
        self._emit_camera_state()

    # ==== 摄像机 ====

    def _compute_camera_normal(self):
        """计算当前相机的投影面法向量 (forward direction)"""
        azim = math.radians(self._cam.azimuth)
        elev = math.radians(self._cam.elevation)
        ce = math.cos(elev)
        se = math.sin(elev)
        ca = math.cos(azim)
        sa = math.sin(azim)
        return [ce * ca, ce * sa, se]

    def _emit_camera_state(self):
        """发布当前相机状态到 on_camera_changed 回调"""
        if self.on_camera_changed:
            normal = self._compute_camera_normal()
            data = [normal[0], normal[1], normal[2], self._cam.distance]
            self._camera_echo_guard = data  # 记录本次发布，用于回声检测
            self.on_camera_changed(data)

    def apply_camera_state(self, camera_data):
        """
        外部设置相机状态 (来自网关广播)
        带回声防护: 如果与最近发布的状态一致则忽略
        """
        if len(camera_data) < 4:
            return
        # 回声检测
        if self._camera_echo_guard is not None:
            diff = sum(abs(a - b) for a, b in zip(camera_data, self._camera_echo_guard))
            if diff < 0.001:
                return
        self._camera_echo_guard = None

        # 从法向量和距离反推 azimuth/elevation
        nx, ny, nz = camera_data[0], camera_data[1], camera_data[2]
        dist = camera_data[3]
        # forward = (ce*ca, ce*sa, se)
        # se = nz → elev = asin(nz)
        nz_clamped = max(-1.0, min(1.0, nz))
        self._cam.elevation = math.degrees(math.asin(nz_clamped))
        ce = math.cos(math.radians(self._cam.elevation))
        if abs(ce) > 1e-6:
            # ca = nx/ce, sa = ny/ce → azimuth = atan2(sa, ca)
            self._cam.azimuth = math.degrees(math.atan2(ny / ce, nx / ce))
        self._cam.distance = max(0.1, min(1.0, dist))
        self._dirty = True

    def _rotate_camera(self, dx, dy):
        # 轴锁定
        if abs(dx) >= abs(dy):
            dy = 0
        else:
            dx = 0
        self._cam.azimuth -= dx * 0.3
        self._cam.elevation -= dy * 0.3
        self._cam.elevation = max(-89, min(89, self._cam.elevation))
        self._dirty = True
        self._emit_camera_state()

    # ==== IK 求解 (解空间轨迹绑定) ====

    def _ik_solve(self, cp_idx, target_screen):
        """根据 DOF 数量分派到对应求解器"""
        if self._suppress_sync:
            return

        # ---- 轨迹预测 ----
        if self._drag_prev_target is not None:
            raw_vel = np.array([
                target_screen.x() - self._drag_prev_target.x(),
                target_screen.y() - self._drag_prev_target.y(),
            ])
            self._drag_velocity = 0.5 * raw_vel + 0.5 * self._drag_velocity
            pred_steps = 1.0
            target_screen = QPointF(
                target_screen.x() + self._drag_velocity[0] * pred_steps,
                target_screen.y() + self._drag_velocity[1] * pred_steps,
            )
        self._drag_prev_target = QPointF(target_screen.x(), target_screen.y())

        cp = CONTROL_POINTS[cp_idx]
        geom_id = cp["geom_id"]
        dofs = cp["dofs"]

        arc = list(self._drag_arc) if self._drag_arc is not None else list(range_to_arc_l10_right(self.dof_values))

        if len(dofs) == 1:
            self._ik_solve_1dof(arc, dofs[0], geom_id, target_screen)
        else:
            self._ik_solve_ndof(arc, dofs, len(dofs), geom_id, target_screen)

        # 保存高精度弧度值
        self._drag_arc = arc

        # 弧度 → 0-255 (仅用于发布)
        new_dof = arc_to_range_l10_right(arc)
        new_dof = [max(0, min(255, int(round(v)))) for v in new_dof]

        self.dof_values = new_dof
        self._dirty = True

        if self.on_dof_changed and not self._suppress_sync:
            self.on_dof_changed(new_dof)

    def _screen_dist_sq(self, screen_a, screen_b):
        """计算两个屏幕点的距离平方"""
        return (screen_a.x() - screen_b.x())**2 + (screen_a.y() - screen_b.y())**2

    def _ik_solve_1dof(self, arc, dof, geom_id, target_screen):
        """1-DOF: 采样 + 黄金分割，搜索弧度范围内屏幕距离最小的解"""
        lo, hi = L10_R_MIN[dof], L10_R_MAX[dof]

        # Phase 1: 均匀采样 20 点
        n_samples = 20
        best_arc = arc[dof]
        best_dist = float('inf')

        for i in range(n_samples + 1):
            t = lo + (hi - lo) * i / n_samples
            arc[dof] = t
            self._sync_mujoco_custom(arc)
            scr = self._project(self._data.geom_xpos[geom_id])
            if scr is None:
                continue
            d = self._screen_dist_sq(scr, target_screen)
            if d < best_dist:
                best_dist = d
                best_arc = t

        # Phase 2: 黄金分割精化 best_arc 邻域
        step = (hi - lo) / n_samples
        a = max(lo, best_arc - step)
        b = min(hi, best_arc + step)
        gr = (math.sqrt(5) + 1) / 2

        for _ in range(12):
            if b - a < 1e-5:
                break
            c = b - (b - a) / gr
            d = a + (b - a) / gr

            arc[dof] = c
            self._sync_mujoco_custom(arc)
            sc = self._project(self._data.geom_xpos[geom_id])
            dc = float('inf') if sc is None else self._screen_dist_sq(sc, target_screen)

            arc[dof] = d
            self._sync_mujoco_custom(arc)
            sd = self._project(self._data.geom_xpos[geom_id])
            dd = float('inf') if sd is None else self._screen_dist_sq(sd, target_screen)

            if dc < dd:
                b = d
            else:
                a = c

        arc[dof] = (a + b) / 2

    def _ik_solve_ndof(self, arc, dofs, n, geom_id, target_screen):
        """Multi-DOF: 网格采样找全局最优起点 + Jacobian 精化"""
        # Phase 1: 网格采样 — 保证找到正确的收敛域
        spa = int(80 ** (1.0 / n))  # 2-DOF: 8(64点), 3-DOF: 4(64点)
        ranges = [np.linspace(L10_R_MIN[dof], L10_R_MAX[dof], spa) for dof in dofs]
        best_dist = float('inf')
        best_combo = tuple(arc[dof] for dof in dofs)

        for combo in itertools.product(*ranges):
            for col, dof in enumerate(dofs):
                arc[dof] = combo[col]
            self._sync_mujoco_custom(arc)
            scr = self._project(self._data.geom_xpos[geom_id])
            if scr is None:
                continue
            d = self._screen_dist_sq(scr, target_screen)
            if d < best_dist:
                best_dist = d
                best_combo = combo

        for col, dof in enumerate(dofs):
            arc[dof] = best_combo[col]

        # Phase 2: 从全局最优起点 Jacobian 精化
        max_iter = 10
        for _ in range(max_iter):
            self._sync_mujoco_custom(arc)
            base_screen = self._project(self._data.geom_xpos[geom_id])
            if base_screen is None:
                return

            err_x = target_screen.x() - base_screen.x()
            err_y = target_screen.y() - base_screen.y()
            if err_x * err_x + err_y * err_y < 1.0:
                break

            J = np.zeros((2, n))
            eps = 0.01
            for col, dof in enumerate(dofs):
                arc_p = list(arc)
                new_val = arc_p[dof] + eps
                clamped = max(L10_R_MIN[dof], min(L10_R_MAX[dof], new_val))
                if abs(clamped - arc_p[dof]) < 1e-9:
                    clamped = max(L10_R_MIN[dof], min(L10_R_MAX[dof], arc_p[dof] - eps))
                if abs(clamped - arc_p[dof]) < 1e-9:
                    continue
                actual_eps = clamped - arc_p[dof]
                arc_p[dof] = clamped
                self._sync_mujoco_custom(arc_p)
                pert_screen = self._project(self._data.geom_xpos[geom_id])
                if pert_screen is not None:
                    J[0, col] = (pert_screen.x() - base_screen.x()) / actual_eps
                    J[1, col] = (pert_screen.y() - base_screen.y()) / actual_eps

            self._sync_mujoco_custom(arc)

            dp = np.array([err_x, err_y])
            jnorm = np.linalg.norm(J)
            lam = max(1.0, 5.0 / (jnorm + 0.01))
            JJT = J @ J.T
            try:
                dq = J.T @ np.linalg.solve(JJT + lam * lam * np.eye(2), dp)
            except np.linalg.LinAlgError:
                break

            for col, dof in enumerate(dofs):
                range_size = L10_R_MAX[dof] - L10_R_MIN[dof]
                max_step = range_size * 0.2
                dq[col] = max(-max_step, min(max_step, dq[col]))
                arc[dof] += dq[col]
                arc[dof] = max(L10_R_MIN[dof], min(L10_R_MAX[dof], arc[dof]))
