# L10 右手核心包

本目录包含 L10 灵巧手控制系统的 8 个核心软件包，提供从底层硬件驱动到上层可视化的完整功能链。

> 这些包是系统运行的必要组件，必须全部构建后才能启动灵巧手控制。

## 依赖关系与构建顺序

```
构建依赖图（箭头表示"被依赖"）:

linker_hand_description  ←───────────── 无依赖（纯模型资产）
        ↑
hand_forward_kinematics  ←───────────── 依赖 linker_hand_description
        ↑         ↑
        │         │
l10_right_hand_mujoco_sim  ←─────────── 依赖 hand_forward_kinematics + linker_hand_description
l10_hand_gateway           ←─────────── 依赖 hand_forward_kinematics
l10_hand_control_panel     ←─────────── 依赖 hand_forward_kinematics + linker_hand_description
l10_right_hand_viz         ←─────────── 依赖 hand_forward_kinematics + linker_hand_description + rviz2
        ↑
l10_right_hand_driver      ←─────────── 无工作空间内部依赖（内嵌 CAN SDK）
        ↑
l10_right_hand_bootstrap   ←─────────── 运行时依赖上述所有包（仅 launch 文件）
```

**必须的构建顺序:**

```bash
# 第一步：先构建基础包
colcon build --packages-select linker_hand_description hand_forward_kinematics

# 第二步：构建其余包（顺序无关）
colcon build --packages-select \
  l10_right_hand_mujoco_sim l10_hand_gateway \
  l10_hand_control_panel l10_right_hand_viz \
  l10_right_hand_driver l10_right_hand_bootstrap
```

或者一次性构建全部：

```bash
colcon build
```

## 包一览

| 包名 | 功能 | 关键依赖 | 主要话题 |
|------|------|---------|---------|
| **linker_hand_description** | URDF/STL/MuJoCo XML 模型资产 | 无 | 无（数据包） |
| **hand_forward_kinematics** | 纯 Python 正运动学库 | linker_hand_description | `/skeleton_body_positions` |
| **l10_right_hand_mujoco_sim** | MuJoCo 仿真后端 | hand_forward_kinematics, mujoco | `/cb_right_hand_state`, `/cb_right_hand_control_cmd` |
| **l10_right_hand_driver** | CAN 总线硬件驱动 | python-can | `/cb_right_hand_state`, `/cb_right_hand_control_cmd` |
| **l10_hand_gateway** | 控制命令反向代理 + FK/IK | hand_forward_kinematics | `/l10_gateway/*` |
| **l10_hand_control_panel** | PySide2 GUI 控制面板 | hand_forward_kinematics, pyside2, mujoco | `/l10_gateway/cmd/*` |
| **l10_right_hand_viz** | RViz2 可视化 | robot_state_publisher, rviz2 | `/joint_states` |
| **l10_right_hand_bootstrap** | 分时启动 launch 文件 | 上述所有包 | 无（仅 launch） |

## 运行时数据流

```
                        ┌─────────────────────────────┐
                        │  后端（二选一，接口相同）      │
                        │  ┌───────────────────────┐  │
                        │  │ l10_right_hand_mujoco  │  │
                        │  │ _sim (仿真)            │  │
                        │  └───────────┬───────────┘  │
                        │  ┌───────────┴───────────┐  │
                        │  │ l10_right_hand_driver  │  │
                        │  │ (CAN 真机)             │  │
                        │  └───────────┬───────────┘  │
                        └──────────────┼──────────────┘
                                       │ /cb_right_hand_state
                                       │ /cb_right_hand_control_cmd
                              ┌────────▼────────┐
                              │ l10_hand_gateway │
                              │ 命令代理 + FK/IK │
                              └────────┬────────┘
                                       │ /l10_gateway/current/*
                                       │ /l10_gateway/target/*
                                       │ /l10_gateway/cmd/*
                    ┌──────────────────┼──────────────────┐
                    │                  │                  │
          ┌─────────▼────────┐ ┌──────▼──────┐ ┌────────▼────────┐
          │ control_panel    │ │ hand_viz    │ │ 应用层节点       │
          │ (GUI 控制面板)    │ │ (RViz2)     │ │ (在 examples/)  │
          └──────────────────┘ └─────────────┘ └─────────────────┘
```

**关键设计:** 后端（仿真/真机）发布完全相同的 topic，通过网关代理后对上层透明切换。

## 常见工作流

### 仅仿真模式

```bash
ros2 launch l10_right_hand_bootstrap sim.launch.py
```

启动 MuJoCo 后端 → 网关 → 控制面板 → RViz2 可视化。

### 仅真机模式

```bash
ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can0 is_touch:=true topic_hz:=30
```

启动 CAN 驱动 → 网关 → 控制面板 → RViz2 可视化。

### 无头后端模式（仅后端 + 网关，无 GUI）

```bash
ros2 launch l10_right_hand_bootstrap sim_headless.launch.py   # 仿真
ros2 launch l10_right_hand_bootstrap real_headless.launch.py   # 真机
```

适合远程服务器部署或与自定义应用层节点配合使用。

## 各包详细文档

| 包名 | 文档链接 |
|------|---------|
| linker_hand_description | [README.md](linker_hand_description/README.md) |
| hand_forward_kinematics | [README.md](hand_forward_kinematics/README.md) |
| l10_right_hand_mujoco_sim | [README.md](l10_right_hand_mujoco_sim/README.md) |
| l10_right_hand_driver | [README.md](l10_right_hand_driver/README.md) |
| l10_hand_gateway | [README.md](l10_hand_gateway/README.md) · [技术设计文档](l10_hand_gateway/REPORT.md) |
| l10_hand_control_panel | [README.md](l10_hand_control_panel/README.md) · [技术设计文档](l10_hand_control_panel/REPORT.md) |
| l10_right_hand_viz | [README.md](l10_right_hand_viz/README.md) |
| l10_right_hand_bootstrap | [README.md](l10_right_hand_bootstrap/README.md) |
