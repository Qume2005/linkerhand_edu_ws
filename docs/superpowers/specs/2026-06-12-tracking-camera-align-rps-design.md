# Tracking 摄像头驱动对齐 RPS — 设计文档

日期: 2026-06-12
状态: 已批准

## 背景与目标

`l10_right_hand_tracking` 的摄像头处理与 `l10_right_hand_rock_paper_scissors` (RPS) 不一致：

- RPS 在 `import cv2` 之前设置 `QT_QPA_PLATFORM_PLUGIN_PATH`（launch 文件 + 节点双重设置），规避 OpenCV 自带 Qt 插件覆盖系统 Qt5 插件导致 xcb 加载失败的依赖冲突；tracking 未设置。
- RPS 用后台线程 `GestureDetector._capture_loop` 异步采集摄像头，主循环轮询最新帧；tracking 在节点 `__init__` 中同步打开摄像头，并用 ROS 定时器里直接 `cap.read()`。
- RPS 在首帧到达前显示「等待摄像头...」且**不崩溃**；tracking 在打不开摄像头时 `raise SystemExit(1)` 直接退出，且无等待提示。

目标：将 tracking 的摄像头驱动对齐 RPS —— 后台采集线程 + Qt 环境变量冲突修复 + 「等待摄像头...」等待态，避免依赖冲突。

## 变更范围

### 1. cv2 Qt 平台插件修复（实机根因，区别于 RPS）

**根因（实测）**：本机 pip 版 `opencv-python` 4.13.0（自带 Qt 5.15.18）在 `import cv2`
时把 `QT_QPA_PLATFORM_PLUGIN_PATH` 覆盖为自带的 `cv2/qt/plugins`，但该目录为空 ——
cv2 的 Qt 平台插件被整体移到了 `cv2/qt_disabled`（这是为了让 RPS 改用系统 Qt5/PySide2
显示、避免 cv2 自带 Qt 与系统 Qt 的二实例冲突）。因此 tracking 的 `cv2.imshow`
找不到 xcb 平台插件而 `SIGABRT`。这与 tracking 改动无关：未加任何环境变量时
`cv2.imshow` 同样崩溃（exit 134）。

> RPS 不受影响、也不需要此修复：RPS 用 PySide2 显示、从不调用 `cv2.imshow`，
> 故 cv2 的 Qt 永不初始化。把 `cv2/qt` 指向**系统**插件行不通——会触发 Qt 二实例
> 冲突（`QObject::moveToThread ... Cannot move to target thread`）。

**修复（仅作用于 tracking 进程）**：在 `hand_tracking_node.py` 的 `import cv2` **之后**，
把插件路径指回 cv2 自己的 `qt_disabled` 插件（与 cv2 自带 Qt 同源、无冲突）：

```python
import cv2
_cv2_plugin_dir = os.path.join(cv2.__path__[0], 'qt_disabled', 'plugins', 'platforms')
if os.path.isdir(_cv2_plugin_dir):
    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = _cv2_plugin_dir
```

必须在 `import cv2` 之后设置（否则被 cv2 覆盖）。launch 层的 `SetEnvironmentVariable`
无效（同样被 cv2 import 覆盖），故**不**在 launch 设置。

### 2. 新增 `CameraCapture` 类（新模块 `camera_capture.py`）
RPS `GestureDetector` 采集模式的去检测版镜像：
- `__init__(camera_id)`: 存 id，`self._cap = None`，**不阻塞打开**。
- `start()`: 启动守护线程 `_capture_loop`。
- `_capture_loop()`: 以**普通**方式打开 `cv2.VideoCapture(camera_id)`（去掉 `CAP_V4L2`/MJPG/640×480，与 RPS 一致）；打开失败仅记日志并 idle（**不崩溃**）；循环 `cap.read()`，加锁存最新帧（`.copy()`），读帧失败 `time.sleep(0.01)`（同 RPS）。
- `get_frame() -> np.ndarray | None`: 返回最新帧副本，首帧前返回 `None`。
- `stop()`: 置停止标志、`join(timeout=2)`、释放 cap。
- `is_opened() -> bool`: 供日志查询。

### 3. `HandTrackingNode` 改造
- `__init__`: 用 `self._capture = CameraCapture(camera_id); self._capture.start()` 替换
  `cv2.VideoCapture(cam_id, cv2.CAP_V4L2)` + MJPG/分辨率 + `raise SystemExit(1)`。
  节点不再因摄像头状态而启动失败。
- `_tick`: `ret, frame = self.cap.read()` → `frame = self._capture.get_frame()`。
  若为 `None`：在空白 640×480 帧上居中绘制「等待摄像头...」并 `cv2.imshow` 后返回；
  否则走原有 检测→映射→发布→渲染 流水线不变。键盘/校准（`cv2.waitKey`）保留于此（cv2 GUI 必须在主线程）。
- `destroy_node`: `self.cap.release()` → `self._capture.stop()`。

## 数据流

```
采集线程(持续) ──最新帧(锁)──▶ _tick 按 publish_hz 轮询 ──▶ 主线程做检测/映射/发布/渲染
```

摄像头异步预热；主循环仅等待并在首帧前显示「等待摄像头...」，与 RPS 行为一致。

## 错误处理

摄像头打开失败不再杀进程；线程记日志并 idle，窗口持续显示「等待摄像头...」。与 RPS 的非致命行为一致。

## 权衡

去掉 MJPG/640×480 以对齐 RPS，但部分摄像头在无 MJPG 时会退化到较慢像素格式。若实机画面卡顿，在 `_capture_loop` 重新加回两个 `.set()` 调用即可（一行级别）。优先对齐 RPS 以保证两个 demo 一致，这是本任务目标。

## 测试

- tracking 目前无测试目录，无既有测试会被破坏。
- `CameraCapture`: 可单测 `get_frame()` 在 `start()`/首帧前返回 `None`。
- 节点构造：因不再阻塞打开摄像头，可在无摄像头环境导入/构造（利于 CI 冒烟测试）。
- 人工验证：`ros2 launch l10_right_hand_tracking hand_tracking_real.launch.py`，先见「等待摄像头...」再进入实时跟踪。
