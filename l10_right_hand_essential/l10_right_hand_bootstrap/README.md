# l10_right_hand_bootstrap

L10 右手系统一键启动包 —— 通过 `TimerAction` 分时启动各组件。

## 概述

`l10_right_hand_bootstrap` 是一个纯 launch 包，不包含任何 Python 节点。它的职责是按正确顺序和时间间隔启动整个系统的所有组件，包括后端、网关、可视化、控制面板。

## 分时启动概念 (TimerAction 延迟)

ROS 2 节点之间通过话题 (topic) 通信，节点可以随时订阅话题，即使发布者尚未启动。但是，某些节点在初始化时需要:

- 后端节点先初始化并开始发布状态话题
- 网关节点订阅后端话题后才能转发状态
- 可视化/面板订阅网关话题后才能显示

如果同时启动所有节点，可能出现:
- 网关在后端初始化完成前订阅，导致丢失初始状态
- 面板在网关就绪前启动，导致显示空白

因此，bootstrap 使用 `TimerAction` 按以下时序分阶段启动:

```
时间轴 (秒)
│
0s ──── 阶段 1: 后端启动
│        ├─ MuJoCo 仿真节点 或 CAN 驱动节点
│        └─ 开始初始化: 加载模型、建立连接
│
3-5s ── 阶段 2: 网关启动
│        ├─ 订阅后端状态话题
│        ├─ 发布初始 DOF → 后端执行初始姿态
│        └─ 开始广播 current/* 和 target/*
│
5-7s ── 阶段 3: 可视化 + 面板启动
│        ├─ hand_viz_node: 订阅网关 DOF → 发布 /joint_states
│        ├─ robot_state_publisher: 订阅 /joint_states → 发布 TF
│        ├─ RViz2: 订阅 TF → 渲染 3D 模型
│        └─ 控制面板: 订阅网关状态 → 显示滑块和骨架
│
▼
系统就绪，等待用户操作
```

### 为什么需要延迟?

| 延迟 | 原因 |
|------|------|
| 后端 → 网关 (3-5s) | 后端需要加载 MuJoCo 模型或建立 CAN 连接 |
| 网关 → 可视化 (2s) | 网关需要先转发一次初始状态，避免面板/RViz 空白 |
| 仿真模式总计 5s | MuJoCo 初始化较快 (3s 后端 + 2s 网关) |
| 真机模式总计 7s | CAN 驱动初始化较慢 (5s 后端 + 2s 网关) |

## 4 种 Launch 变体及使用场景

### 1. sim.launch.py —— 仿真模式完整版

```bash
ros2 launch l10_right_hand_bootstrap sim.launch.py
```

启动组件: MuJoCo 仿真后端 + 网关 + RViz2 可视化 + 控制面板

适用场景: 日常开发调试、手势测试、功能验证。不需要连接真实硬件。

时序: 后端 (0s) → 网关 (3s) → 可视化 + 面板 (5s)

### 2. real.launch.py —— 真机模式完整版

```bash
ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can0 is_touch:=true topic_hz:=60
```

启动组件: CAN 硬件驱动 + 网关 + RViz2 可视化 + 控制面板

适用场景: 连接真实的 L10 右手硬件，需要 CAN 接口和触觉传感器。

时序: 后端 (0s) → 网关 (5s) → 可视化 + 面板 (7s)

特殊机制: 包含 `OnProcessExit` 驱动崩溃容错 (见下文)。

### 3. sim_headless.launch.py —— 仿真无头模式

```bash
ros2 launch l10_right_hand_bootstrap sim_headless.launch.py
```

启动组件: MuJoCo 仿真后端 + 网关 (无可视化，无控制面板)

适用场景: 服务器/容器环境、自动化测试、LLM 控制器、手部追踪等不需要 GUI 的应用。

时序: 后端 (0s) → 网关 (3s)

### 4. real_headless.launch.py —— 真机无头模式

```bash
ros2 launch l10_right_hand_bootstrap real_headless.launch.py can_port:=can0 is_touch:=true topic_hz:=60
```

启动组件: CAN 硬件驱动 + 网关 (无可视化，无控制面板)

适用场景: 真机环境下运行自动化应用 (LLM 控制、手部追踪)，不需要 GUI。

时序: 后端 (0s) → 网关 (5s)

## OnProcessExit 驱动崩溃容错机制

在 `real.launch.py` 和 `real_headless.launch.py` 中，CAN 驱动节点可能因以下原因退出:
- CAN 总线断开
- USB-CAN 适配器拔出
- 驱动程序内部错误

如果不做特殊处理，ROS 2 的默认行为可能会终止整个 launch 会话。bootstrap 使用
`RegisterEventHandler` + `OnProcessExit` 来注册驱动退出事件处理器:

```python
RegisterEventHandler(
    OnProcessExit(
        target_action=driver_node,
        on_exit=[
            LogInfo(msg='L10 驱动节点已退出，其余节点继续运行'),
        ],
    ),
),
```

驱动退出时只打印一条日志，**不影响其他节点**。网关和可视化/面板继续运行，
等待驱动重新连接。这在实际使用中非常有用，因为用户可以:
1. 重新插拔 CAN 适配器
2. 在另一个终端手动启动驱动
3. 系统自动恢复

## 参数传递

`real.launch.py` 和 `real_headless.launch.py` 支持 3 个可选参数:

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `can_port` | `can0` | CAN 接口名称 (如 `can0`、`can1`) |
| `is_touch` | `true` | 是否启用触觉传感器 (`true`/`false`) |
| `topic_hz` | `60` | 控制频率 (Hz)，同时控制网关样条轨迹和驱动发送，建议 30-120 |

使用示例:

```bash
# 使用 can1 接口，不启用触觉传感器，频率 50Hz
ros2 launch l10_right_hand_bootstrap real.launch.py can_port:=can1 is_touch:=false topic_hz:=50
```

`sim.launch.py` 和 `sim_headless.launch.py` 不接受参数，使用固定的 `topic_hz=60` 和 `is_touch=True`。

## 启动时序图

```
sim.launch.py:
  t=0s   [MuJoCo 仿真节点] ───────────────────────────────────────────────►
  t=3s                        [网关节点] ───────────────────────────────────►
  t=5s                                    [RViz2 + robot_state_publisher]
                                          [hand_viz_node + 控制面板] ───────►

real.launch.py:
  t=0s   [CAN 驱动节点] ───────────────────────────────────────────────────►
  t=5s                        [网关节点] ───────────────────────────────────►
  t=7s                                    [RViz2 + robot_state_publisher]
                                          [hand_viz_node + 控制面板] ───────►
                                          (驱动退出时仅打印日志，不终止)

sim_headless.launch.py:
  t=0s   [MuJoCo 仿真节点] ───────────────────────────────────────────────►
  t=3s                        [网关节点] ───────────────────────────────────►

real_headless.launch.py:
  t=0s   [CAN 驱动节点] ───────────────────────────────────────────────────►
  t=5s                        [网关节点] ───────────────────────────────────►
                                          (驱动退出时仅打印日志，不终止)
```

## 依赖说明

bootstrap 包的依赖即整个系统的所有组件:

| 依赖 | 用途 |
|------|------|
| `l10_right_hand_mujoco_sim` | MuJoCo 仿真后端 (sim 模式) |
| `l10_right_hand_driver` | CAN 硬件驱动 (real 模式) |
| `l10_hand_gateway` | 网关节点 (所有模式) |
| `l10_right_hand_viz` | 可视化节点 (完整模式) |
| `l10_hand_control_panel` | 控制面板 (完整模式) |
| `robot_state_publisher` | URDF → TF (可视化模式) |
| `rviz2` | 3D 渲染 (完整模式) |

## 文件清单

```
l10_right_hand_bootstrap/
├── README.md                        # 本文件
├── package.xml                      # ROS 2 包描述
├── setup.py                         # Python 包配置
├── resource/
│   └── l10_right_hand_bootstrap     # ament 资源标记
└── launch/
    ├── sim.launch.py                # 仿真模式完整版
    ├── real.launch.py               # 真机模式完整版
    ├── sim_headless.launch.py       # 仿真无头模式
    └── real_headless.launch.py      # 真机无头模式
```
