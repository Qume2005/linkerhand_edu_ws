# L10 右手应用示例包

本目录包含 2 个可选的应用层软件包，展示如何利用核心包提供的网关接口实现高级控制功能。

> **前提条件:** 这些包依赖核心包（`l10_right_hand_essential/`）已构建并运行。它们通过网关的 `/l10_gateway/*` 话题与系统交互，不直接与后端通信。

## 包一览

| 包名 | 功能 | 额外依赖 | 运行命令 |
|------|------|---------|---------|
| **l10_right_hand_llm** | 自然语言手势控制（LLM 驱动） | openai / anthropic, PySide2 | `ros2 launch l10_right_hand_llm llm_control.launch.py` |
| **l10_right_hand_tracking** | 摄像头手部追踪控制 | mediapipe, opencv-python, numpy | `ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py` |

## 与网关架构的集成

两个应用包都通过网关的标准化话题接口工作：

```
l10_right_hand_llm
  发布 → /l10_gateway/cmd/dof (JointState, 10 DOF)
  订阅 ← /l10_gateway/current/dof (当前实际 DOF)
  订阅 ← /l10_gateway/target/dof (目标 DOF)

l10_right_hand_tracking
  发布 → /l10_gateway/cmd/control_points (PoseArray, 5 指尖)
  发布 → /l10_gateway/cmd/camera (Float32MultiArray, 相机状态)
  订阅 ← /l10_gateway/current/control_points (当前控制点)
  订阅 ← /l10_gateway/target/dof (目标 DOF，用于校准)
```

**注意:** 两个包不能同时运行（会互相争夺控制权）。选择其中一个启动即可。

## 快速开始

### LLM 手势控制

```bash
# 构建核心包 + LLM 包
colcon build --packages-select l10_right_hand_llm
source install/setup.bash

# 仿真模式（包含完整的 bootstrap 启动）
ros2 launch l10_right_hand_llm llm_control.launch.py

# 真机模式
ros2 launch l10_right_hand_llm llm_control_real.launch.py can_port:=can0
```

首次启动会弹出设置对话框，配置 API Key 后即可用自然语言控制手势。

### 手部追踪控制

```bash
# 构建核心包 + tracking 包
colcon build --packages-select l10_right_hand_tracking
source install/setup.bash

# 仿真模式（自动扫描摄像头）
ros2 launch l10_right_hand_tracking hand_tracking_sim.launch.py

# 真机模式（自动扫描摄像头）
ros2 launch l10_right_hand_tracking hand_tracking_real.launch.py
```

需要 USB 摄像头。启动后按 `C` 键进入校准模式改善追踪精度。

## 各包详细文档

| 包名 | 文档链接 |
|------|---------|
| l10_right_hand_llm | [README.md](l10_right_hand_llm/README.md) |
| l10_right_hand_tracking | [README.md](l10_right_hand_tracking/README.md) |
