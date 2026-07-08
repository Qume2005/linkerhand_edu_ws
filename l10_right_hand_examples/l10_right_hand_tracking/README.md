# L10 灵巧手手势跟踪系统

基于 MediaPipe 的实时手部姿态追踪，将摄像头捕捉的手部动作映射为 L10 灵巧手
的控制命令。支持仿真和真机两种模式。

## 快速开始

```bash
# 构建
cd ~/projects/linkerhand_edu_ws
colcon build --packages-select l10_right_hand_tracking

# 仿真模式
source install/setup.bash
ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py

# 真机模式
ros2 launch l10_right_hand_tracking hand_tracking_real.launch.py
```

> **摄像头自动扫描：** 默认自动扫描可用摄像头（0-9），无需手动指定 `camera_id`。
> 如有多个摄像头，可通过 `camera_id` 参数指定：`camera_id:=2`
```

## 概述

系统通过摄像头捕获用户手部姿态，利用 MediaPipe 提取 21 个手部关键点，
经过坐标变换和弯曲度计算后映射为 10-DOF 关节值，再通过正运动学 (FK)
计算 5 个指尖的 3D 目标位置（控制点），最终通过 Gateway 的 IK 逆运动学
驱动灵巧手跟随用户手势运动。

## MediaPipe 21 关键点到 10-DOF 映射管道

```
摄像头帧
  → MediaPipe HandLandmarker (21 关键点)
  → 右手 x=0.5 轴镜像 (mirror_landmarks_x)
  → 弯曲度计算 (compute_finger_curls, 5 指 curl 值)
  → 原始 DOF 映射 (landmarks_to_raw_dof, 10 DOF)
  → FK 正运动学 (_fk_control_points, 5 指尖 3D 坐标)
  → 校准修正 (可选, _apply_cp_calibration)
  → EMA 平滑 (alpha=0.4)
  → 发布 /l10_gateway/cmd/control_points (PoseArray)
```

### 右手镜像处理

MediaPipe 对摄像头画面的左右手判断基于未镜像的原始帧。当检测到右手时，
需要对关键点沿画面中轴 (x=0.5) 做水平镜像：

```python
def mirror_landmarks_x(landmarks):
    return [(1.0 - lm[0], lm[1], lm[2]) for lm in landmarks]
```

这是因为用户面对摄像头时，右手在画面左侧（已做 cv2.flip 镜像后），
但灵巧手控制的是右手，需要将关键点翻转到正确的方向。

### EMA 平滑

采用指数移动平均 (Exponential Moving Average) 滤波器消除抖动：

```
smooth = alpha * new + (1 - alpha) * prev
```

`alpha=0.4` 在灵敏度和稳定性之间取得平衡。alpha 越大跟踪越灵敏但抖动
越大，越小越平滑但延迟越高。控制点和相机命令均独立做 EMA 平滑。

## 弯曲度 (Curl) 计算

每根手指的弯曲度通过首段和末段向量的夹角余弦来衡量：

```
v1 = PIP - MCP    (首段向量)
v2 = TIP - DIP    (末段向量)
cos_a = dot(v1, v2) / (|v1| * |v2|)
curl = clip((1 - cos_a) / 2, 0, 1)
```

- 伸直：cos_a 接近 1 → curl 接近 0
- 弯曲：cos_a 小于 1 → curl 大于 0

### 拇指 sqrt 放大处理

拇指的解剖结构导致首尾段夹角变化范围天然偏小（curl 值较小），因此对
拇指的 curl 值做开根号放大：

```python
if finger_idx == 0 and curl > 0.0:
    curl = clip(sqrt(curl), 0, 1)
```

这使得拇指的微小弯曲也能产生足够的 DOF 变化。

### 侧摆 DOF 计算

食指、无名指、小指的侧摆值以中指 MCP 的 x 坐标为参考中心：

```python
mcp_span = abs(landmarks[5][0] - landmarks[17][0]) + 1e-6  # 食指MCP到小指MCP的距离
lat_scale = 3.0 / mcp_span  # 归一化系数

# 食指侧摆: 指尖到中指中心的距离
dof[6] = clip(255 * (mid_x - landmarks[8][0]) * lat_scale, 0, 255)
```

拇指侧摆通过拇指尖到食指 MCP 的横向距离计算。

## 校准系统详解

由于 MediaPipe 关键点到 MuJoCo FK 控制点的映射存在系统性误差（手部模型
形状差异、关节长度比例不同等），系统提供了分段线性校准机制。

### 校准流程

1. **进入校准模式** — 按 `C` 键进入，屏幕顶部显示 "CALIBRATION MODE" 横幅
2. **采样** — 在不同手势下按 `Space` 键采样。系统记录：
   - 当前 5 指的 curl 值
   - 每根手指的控制点偏差 (correct - raw)：
     - `raw`: 当前 MediaPipe 映射的控制点
     - `correct`: Gateway 当前 target DOF 经 FK 计算的控制点
3. **完成校准** — 再次按 `C` 键，系统构建分段线性修正模型

### 分段线性校正模型

每根手指独立建立一个 `curl → 3D delta` 的分段线性查找表：

```
curl 值  |  delta (修正向量)
---------+--------------------
  1.0    |  (0, 0, 0)         ← 零锚点：握拳时信任原始映射
  0.7    |  (dx1, dy1, dz1)   ← 采样点
  0.4    |  (dx2, dy2, dz2)   ← 采样点
  0.1    |  (dx3, dy3, dz3)   ← 采样点
```

使用时根据当前 curl 值在相邻采样点之间线性插值，得到修正 delta，
叠加到原始控制点上。

**零锚点约定**：自动在 curl=1（完全握拳）处插入 delta=(0,0,0)，
因为握拳时各指尖收拢，映射误差最小，信任原始值。

## OpenCV 调试窗口

系统启动后会打开一个 OpenCV 窗口（`L10 Hand Tracking`），显示：

- **手部骨架** — 绿色线条连接 21 个关键点
- **指尖高亮** — 5 个指尖用不同颜色的大圆点标注
    - 拇指: 蓝色, 食指: 黄色, 中指: 绿色, 无名指: 青色, 小指: 紫色
- **掌心标记** — 黄色圆圈标注掌心位置
- **手势标签** — 显示检测到的手部类型和映射方向
- **控制点数值** — 每根手指的 curl 值和 3D 控制点坐标
- **校准覆盖层** — 校准模式下显示采样数、当前 delta、操作提示

## 相机空间坐标重建

从 MediaPipe 的归一化 2D 坐标重建 3D 空间坐标，用于计算掌心法向量和
相机控制命令：

### 深度估计 (针孔模型)

```python
# 以手掌长度（手腕到中指 MCP）作为已知参考距离 (默认 8cm)
px_distance = pixel_distance(wrist, middle_mcp)
f = (fx + fy) / 2  # 焦距均值
Z_wrist = (f * palm_length_cm) / px_distance
```

### 3D 坐标重建

```python
for lm in landmarks:
    z = Z_wrist + lm[2] * Z_wrist * 0.3  # MediaPipe z 是相对深度
    x = (lm[0] * w - cx) * z / fx
    y = (lm[1] * h - cy) * z / fy
```

### 掌心法向量计算

从手腕、食指 MCP、中指 MCP、小指 MCP 四点构建掌心坐标系：

```python
Y = normalize(middle_mcp - wrist)           # 掌心纵轴
X_temp = index_mcp - pinky_mcp              # 掌心横轴
X = normalize(X_temp - project(X_temp, Y))  # 去 Y 分量后归一化
normal = cross(X, Y)                        # 掌心法向量
```

坐标轴映射 (真实相机 → MuJoCo)：`nx = -normal[2], ny = normal[0], nz = -normal[1]`

## FK-based 控制点管道

本系统不直接从 MediaPipe 关键点插值控制点位置，而是通过 DOF→FK 管道
间接计算。这样做的好处是：

1. **运动学一致性** — 所有控制点都经过 FK 验证，保证在灵巧手可达空间内
2. **IK 兼容性** — Gateway 的 IK 接收控制点后能精确还原 DOF 值
3. **可校准性** — 校准系统修正的是 DOF→FK 的映射偏差，而不是直接修改坐标

管道详解：
```
landmarks (21 points) → curls (5 values) → raw DOF (10 values)
    → range_to_arc_l10_right (0-255 转弧度)
    → expand_to_20_joints (10 DOF 扩展为 20 MuJoCo 关节)
    → compute_fk (正向运动学)
    → 5 个指尖位置 (FINGERTIP_BODIES: [5, 9, 12, 16, 20])
```

## 常量说明

| 常量 | 值 | 说明 |
|------|-----|------|
| `TIP_INDICES` | `[4, 8, 12, 16, 20]` | 5 个指尖在 MediaPipe 21 关键点中的索引 |
| `PALM_INDICES` | `[0, 5, 9, 13, 17]` | 手腕 + 4 个 MCP 关节索引 |
| `FINGER_JOINTS` | 5x4 矩阵 | 每根手指 4 个关节索引 (根/中/次/尖) |
| `CAMERA_MATRIX` | `[[600,0,320],[0,600,240],[0,0,1]]` | 针孔相机内参 (fx=fy=600, cx=320, cy=240) |
| `FINGERTIP_BODIES` | `[5, 9, 12, 16, 20]` | MuJoCo FK 中 5 个指尖 body 的索引 |
| `OPEN/CLOSED_CP_THUMB` | numpy arrays | 拇指张开/握拳时的控制点参考位置 |
| `_alpha` | `0.4` | EMA 平滑系数 |

## ROS 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `camera_id` | int | -1 | 摄像头设备号，-1=自动扫描 |
| `publish_hz` | int | 30 | 控制点发布频率 (Hz) |

> **自动扫描：** 默认 `camera_id=-1` 时自动遍历 0-9 寻找第一个可用摄像头。
> 如有多个摄像头，可手动指定：`camera_id:=2`

## 话题接口

### 发布

| 话题 | 类型 | 说明 |
|------|------|------|
| `/l10_gateway/cmd/control_points` | `geometry_msgs/PoseArray` | 5 个指尖 3D 目标位置 (IK 输入) |
| `/l10_gateway/cmd/camera` | `std_msgs/Float32MultiArray` | 相机控制 [距离, nx, ny, nz] |

### 订阅

| 话题 | 类型 | 说明 |
|------|------|------|
| `/l10_gateway/current/control_points` | `geometry_msgs/PoseArray` | 当前实际控制点 (校准参考) |
| `/l10_gateway/target/dof` | `sensor_msgs/JointState` | Gateway 目标 DOF (校准采样) |

## 依赖

| 包 | 用途 |
|----|------|
| `mediapipe` | 手部关键点检测 (支持 Task API 和 Legacy API) |
| `opencv-python` | 摄像头采集、调试可视化 |
| `numpy` | 数值计算、向量运算 |
| `hand_forward_kinematics` | DOF→FK 正运动学计算 |

MediaPipe 支持两种后端，优先使用 Task API（更精确），自动回退到 Legacy API。
首次使用 Task API 时会自动下载 `hand_landmarker.task` 模型文件。

## 文件清单

| 文件 | 职责 |
|------|------|
| `hand_tracking_node.py` | ROS 节点主体：摄像头采集、MediaPipe 检测、DOF 映射、FK 管道、校准系统、OpenCV 可视化、ROS 话题发布 |

## 坐标变换细节

### MediaPipe 坐标系

- x: 归一化到 [0, 1]，画面左到右
- y: 归一化到 [0, 1]，画面上到下
- z: 相对深度，手腕处为 0，越远离相机越大（正值在摄像头前方）

### MuJoCo 坐标系

- x: 右方向
- y: 上方向
- z: 前方向（远离手掌）

### 映射链路

```
MediaPipe (x, y, z)          # 归一化 [0,1], y 向下
    → mirror (右手: x = 1-x) # 水平翻转
    → curl/lateral 计算      # 归一化弯曲比/侧摆值
    → DOF (0-255)            # 灵巧手关节值
    → FK (MuJoCo 3D)         # 米制单位, MuJoCo 坐标系
```

## 使用提示

- 保持手部在摄像头画面中央，距离 30-60cm 效果最佳
- 光线充足的环境下追踪效果更好
- 校准时建议采样 3-5 种不同手势（张开、半握、握拳等），覆盖 curl 全范围
- 如果跟踪抖动明显，可降低 `_alpha` 值（如 0.25）增加平滑度
