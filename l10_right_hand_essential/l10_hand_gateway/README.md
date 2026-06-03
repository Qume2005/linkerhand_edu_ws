# l10_hand_gateway

L10 右手网关节点 —— 控制话题反向代理 + 正运动学计算服务。

> 详见 [技术设计文档](REPORT.md)

## 概述

`l10_hand_gateway` 是整个系统的中枢节点，位于后端（仿真/真机驱动）和前端（控制面板、可视化、应用）之间。它的核心职责是：

1. **反向代理**：后端和前端完全解耦，前端只与网关通信，不直接操作后端
2. **正/逆运动学**：将 DOF 值转换为骨架 (21 个位姿) 和控制点 (5 个指尖位置)，以及反向转换
3. **命令格式转换**：支持 5 种不同格式的命令输入，统一转换为 DOF 后转发给后端

## 网关反向代理模式

```
后端 (仿真/真机)                     前端 (面板/可视化/应用)
┌─────────────┐                   ┌──────────────────┐
│ 发布:        │                   │ 订阅:             │
│ /cb_right_  │  ──► 网关 ──►    │ /l10_gateway/     │
│ hand_state  │      代理         │ current/*         │
│             │                   │                    │
│ 订阅:        │  ◄── 网关 ◄──    │ 发布:             │
│ /cb_right_  │      转发         │ /l10_gateway/     │
│ hand_       │                   │ cmd/*              │
│ control_cmd │                   └──────────────────┘
└─────────────┘
```

网关作为"中间人"，使后端可以在仿真 (MuJoCo) 和真机 (CAN 驱动) 之间无缝切换，而前端代码完全不需要改动。

## 5 种命令格式 → DOF 转换

| 命令话题 | 消息类型 | 转换方式 | 说明 |
|----------|----------|----------|------|
| `/l10_gateway/cmd/dof` | JointState (10) | 直接设置 | 直接指定 10 DOF 值，无转换 |
| `/l10_gateway/cmd/skeleton` | PoseArray (21) | 逆 FK | 21 个全局四元数 → 提取关节旋转 → 折叠为 10 DOF |
| `/l10_gateway/cmd/control_points` | PoseArray (5) | IK | 5 个指尖目标位置 → 网格采样 + Jacobian 精化 → 10 DOF |
| `/l10_gateway/cmd/control_points_diff` | PoseArray (5) | 当前 CP + 差分 → IK | 在当前控制点基础上叠加差分，再做 IK |
| `/l10_gateway/cmd/camera` | Float32MultiArray | 直接存储 | 设置相机距离和法向量，用于 IK 的深度抑制 |
| `/l10_gateway/cmd/camera_diff` | Float32MultiArray | 四元数旋转差分 | 通过四元数旋转更新相机法向量 |

## 广播话题列表 (10 个)

网关持续广播以下话题，供所有前端节点订阅：

| 话题 | 消息类型 | 频率 | 说明 |
|------|----------|------|------|
| `/l10_gateway/current/dof` | JointState (10) | 跟随后端 | 当前实际位姿的 10 DOF 值 (0-255) |
| `/l10_gateway/current/skeleton` | PoseArray (21) | 跟随后端 | 当前位姿的 21 个 body 全局位姿 |
| `/l10_gateway/current/control_points` | PoseArray (5) | 跟随后端 | 当前位姿的 5 个指尖 3D 位置 |
| `/l10_gateway/target/dof` | JointState (10) | 跟随命令 | 目标位姿的 10 DOF 值 |
| `/l10_gateway/target/skeleton` | PoseArray (21) | 跟随命令 | 目标位姿的 21 个 body 全局位姿 |
| `/l10_gateway/target/control_points` | PoseArray (5) | 跟随命令 | 目标位姿的 5 个指尖 3D 位置 |
| `/l10_gateway/camera` | Float32MultiArray (4) | 跟随命令 | 相机状态 [distance, nx, ny, nz] |
| `/l10_gateway/sensor/force` | Float32MultiArray | 跟随后端 | 力传感器数据 (透传) |
| `/l10_gateway/sensor/matrix_touch` | String (JSON) | 跟随后端 | 触觉矩阵数据 (透传) |
| `/l10_gateway/sensor/matrix_touch_mass` | String (JSON) | 跟随后端 | 触觉质量数据 (透传) |

## IK 求解器详解

IK 求解器位于 `ik_solver.py`，用于将 5 个指尖目标位置转换为 10 DOF 值。采用 **两阶段求解** 策略：

### 阶段 1: 网格采样 (全局搜索)

对每个手指的 DOF 空间进行均匀网格采样，确保找到全局最优的起始点：

- **1-DOF 手指** (中指): 21 个均匀采样点
- **2-DOF 手指** (食指、无名指、小指): 每轴 ~9 个采样点，共 ~81 个组合
- **3-DOF 手指** (拇指): 每轴 ~4 个采样点，共 ~64 个组合

采样密度通过 `spa = int(80 ** (1.0 / n))` 自适应计算，保证总采样量约 80 次左右。

### 阶段 2: Jacobian 精化 (局部优化)

在全局最优起点上，使用**阻尼最小二乘法** (Damped Least Squares / Levenberg-Marquardt) 进行迭代精化：

1. 计算数值 Jacobian 矩阵 J (3xN)，表示每个 DOF 变化对指尖位置的影响
2. 求解关节增量: `dq = J^T (JJ^T + λ²I)^{-1} dp`
3. 自适应阻尼因子 λ，Jacobian 范数越大 → 阻尼越大 → 步长越小
4. 单步限幅为关节范围的 20%，防止过冲
5. 最多迭代 10 次

### 相机深度抑制

当提供相机法向量时，IK 误差函数会抑制沿视线方向的深度分量至 20% 权重。这是因为从相机只能获取 2D 投影信息，深度方向不可靠。

## Debounce 机制 (delta < 3 抑制)

网关在将命令转发给后端时，会与上次转发的 DOF 进行比较。如果所有 DOF 的变化量均小于 3，则**跳过转发**。这有效避免了：

- 频繁发布微小变化导致 CAN 总线拥堵
- 仿真后端处理不必要的更新
- IK 求解过程中间状态的抖动

## 相机状态管理

网关维护一个相机状态 `[distance, nx, ny, nz]`，用于 IK 求解时的深度抑制。支持两种更新方式：

1. **直接设置** (`/l10_gateway/cmd/camera`): 完全替换相机状态
2. **差分更新** (`/l10_gateway/cmd/camera_diff`): 通过四元数旋转增量更新法向量

差分更新只传输 4 个浮点数 `[delta_distance, qx, qy, qz]`，其中 `qw` 通过 `sqrt(1 - qx² - qy² - qz²)` 恢复，节省带宽。

## 全局速度限制

网关内置全局速度限制，通过控制面板滑块实时调节。速度限制作用于整个处理管道中的轨迹规划阶段。

### 架构

速度限制分为两个独立模块：

- **SpeedLimiter** (`speed_limiter.py`)：纯速度映射层，将 0-100% 百分比映射为 `max_speed` (units/s)。100% = 不限速，50% = 120 units/s，0% = 冻结。
- **MotionPlanner** (`motion_planner.py`)：五次样条（min-jerk）轨迹生成器。消费 `max_speed`，为 10 DOF 生成平滑的点到点运动轨迹。

### 五次样条插值

采用零初速/零终速五次多项式 `s(τ) = 10τ³ − 15τ⁴ + 6τ⁵`，具有以下特性：

- 无抖动、无过调（半隐式 Euler 积分误差的根源被消除）
- 中途目标变化时从当前 (position, velocity) 平滑重规划
- 轨迹时长 T = 1.875 × |Δ| / max_speed，保证峰值速度不超过 max_speed

### 拇指碰撞避让路径

当拇指弯曲目标 (DOF0) 存在碰撞风险时，MotionPlanner 内部的 `_ThumbPathPlanner` 执行分阶段路径规划：

1. **Phase 1（避让）**：DOF1/DOF9 向安全中间值移动，DOF0 保持不变
2. **Phase 2（弯曲）**：Phase 1 完成后，DOF0 向目标移动

安全中间值通过搜索碰撞查找表找到：在 DOF1/DOF9 采样网格上寻找允许目标 DOF0 的最近安全点。

### ROS 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `topic_hz` | int | `60` | 网关控制频率 (Hz)，同时控制样条轨迹推进和命令转发频率 |
| `collision_guard.enabled` | bool | `true` | 启用/禁用碰撞防护 |

## 碰撞防护

网关内置基于正运动学 (FK) 预计算查找表的指间碰撞防护，在命令转发给后端之前自动修正危险 DOF 组合。

### 碰撞对

| 碰撞对 | 碰撞机理 | 受限 DOF |
|--------|----------|----------|
| 拇指 vs 食指/中指/无名指/小指 | 拇指 3 DOF 组合使拇指体扫到弯曲的四指 | DOF0 (弯曲), DOF1 (侧摆), DOF9 (对指) |
| 小指 vs 无名指 | 无名指外展过大 (DOF7 高) + 小指未展开 (DOF8 低) | DOF7, DOF8 |

其他相邻四指对 (食指-中指, 中指-无名指) 因机械结构保证不碰撞，不做限制。

### 两条规则

**规则 A — ThumbRule**：对每根四指，预计算 `(DOF1, DOF9, 该指弯曲度) → DOF0 安全下限` 的查找表。运行时分别查 4 根手指的表，取最严格的 DOF0 限制。若仅靠伸直拇指 (DOF0 ≥ 252) 仍无法避免碰撞，则额外将 DOF9 向 255 (不对指) 方向推送。

**规则 B — LateralRule**：预计算 `(DOF7, DOF8) → 是否碰撞` 的布尔矩阵。碰撞时将 DOF7 降低或 DOF8 升高到最近的非碰撞点。

### 查找表生成

查找表由 `scripts/fk_collision_analysis.py` 离线生成，使用 FK + 手指体半径 (从 STL 网格提取) 做二分搜索找碰撞边界：

```bash
# 生成默认分辨率 (拇指 16, 侧摆 32)
python3 scripts/fk_collision_analysis.py

# 自定义分辨率 (更高 = 更精确，但生成更慢)
python3 scripts/fk_collision_analysis.py --thumb-res 20 --lateral-res 48

# 只分析拇指 vs 食指
python3 scripts/fk_collision_analysis.py --finger index
```

输出文件为 `l10_hand_gateway/collision_tables.json`，打包时随 `package_data` 一起安装。

### 查询策略

为避免采样间隙漏检碰撞，查询时对目标点 **±1 邻域** 做扩展检查：
- ThumbRule：在 `(DOF1, DOF9, finger_flex)` 三维空间检查 3×3×3 = 27 个邻域点
- LateralRule：在 `(DOF7, DOF8)` 二维空间检查 3×3 = 9 个邻域点

### ROS 参数

| 参数 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `collision_guard.enabled` | bool | `true` | 启用/禁用碰撞防护 |
| `tactile_guard` (YAML) | - | 见下方 | 触觉防护独立配置文件 |

禁用碰撞防护后网关不加载查找表，命令直接透传。若 `collision_tables.json` 不存在，碰撞防护自动禁用并输出警告日志。

触觉防护通过独立配置文件 `config/tactile_guard.yaml` 管理，不使用 ROS 参数，修改后重启节点即生效。

### 工作流程

```
前端命令 (DOF/Skeleton/CP) → 格式转换 → DOF
                                         ↓
                                   全局速度限制 (SpeedLimiter)
                                         ↓
                                   五次样条轨迹规划 (MotionPlanner)
                                         ↓
                                   碰撞防护修正 (ThumbRule + LateralRule)
                                         ↓
                                   触觉防护过滤 (冻结/回退)
                                         ↓
                                   safe_dof → debounce → 转发后端
```

碰撞防护在所有命令回调中统一执行 (`_apply_collision_guard`)，在 debounce 和转发之前。

## 触觉紧急停止

网关内置触觉紧急停止模块，当力传感器检测到手指压力异常时，冻结或回退对应手指的弯曲 DOF，防止夹伤或损坏硬件。

### 触发力源

使用 `/cb_right_hand_matrix_touch` 话题，计算每根手指 12x6 压力矩阵的单格最大值作为触发依据。每根手指独立检测。阈值直接对应单格压力值，便于直观调参。

### 配置文件

触觉防护参数通过 `config/tactile_guard.yaml` 配置：

```yaml
# 是否启用触觉防护
enabled: true

# 触发阈值 — 力矩阵单格最大值 (0-255)
# 0.1 = 矩阵任意一格非零即触发
threshold: 0.1

# 回退步数 (0=仅冻结, >0=向伸直方向回退 N 单位后冻结)
retreat_units: 0.0

# 冻结持续时间 (秒)
freeze_duration: 5.0
```

修改后重启节点生效。

### 手指→DOF 映射

| 手指 | 弯曲 DOF (冻结目标) | 侧摆 DOF (不受影响) |
|------|---------------------|---------------------|
| 拇指 | DOF0 | DOF1, DOF9 |
| 食指 | DOF2 | DOF6 |
| 中指 | DOF3 | - |
| 无名指 | DOF4 | DOF7 |
| 小指 | DOF5 | DOF8 |

冻结只锁定弯曲 DOF，侧摆不受影响。

### 行为模式

- **retreat_units = 0 (默认)**：纯冻结 — 手指弯曲 DOF 锁定在触发时的值，不允许继续弯曲，但允许伸直
- **retreat_units > 0**：冻结 + 回退 — 手指弯曲 DOF 向伸直方向移动指定步数后冻结

### 自动解除

- **力下降**：法向力降到阈值 80% 以下时自动解除
- **超时**：冻结超过 `freeze_duration` 后自动解除，若压力仍超阈值则立即重新冻结（无冷却期）
- **手动重置**：通过代码调用 `reset()` 解除所有冻结

## 性能特征

- **单次 IK 求解**: ~2-5ms (1-DOF) / ~5-20ms (3-DOF)，取决于采样密度和 Jacobian 迭代次数
- **FK 计算**: < 1ms (纯 Python，无 MuJoCo 依赖)
- **碰撞防护**: < 0.5ms (查找表查询，无 FK 计算)
- **Debounce**: 每 3 个 DOF 单位过滤一次无效更新
- **内存占用**: 低，查找表 ~45KB

## 测试

```bash
# 速度映射单元测试
python3 -m pytest tests/test_speed_limiter.py -v

# 五次样条轨迹规划测试
python3 -m pytest tests/test_motion_planner.py -v

# 碰撞查询测试
python3 -m pytest tests/test_query_dof0_limit.py -v

# 拇指避让路径规划测试
python3 -m pytest tests/test_thumb_path_planner.py -v

# 碰撞防护单元测试 (真实查找表)
python3 -m pytest tests/test_collision_guard.py -v

# 触觉防护单元测试
python3 -m pytest tests/test_tactile_guard.py -v

# 全量测试
python3 -m pytest tests/ -v --ignore=tests/test_gateway_integration.py
```

速度映射测试 (20 个)：百分比映射、round-trip、属性读写、常量导出。

五次样条测试 (36 个)：透传/冻结模式、平滑启动、无过调、钟形速度曲线、精确到达、snap 机制、重规划、边界钳位、dt 限制、reset、DOF 独立性。

碰撞查询测试 (17 个)：mock 查找表验证、邻域搜索、多指综合、与 check() 一致性验证。

拇指避让测试 (10 个)：Phase 1/Phase 2 过渡、DOF0 保持/释放、平滑过渡、不可避让回退。

碰撞防护测试 (16 个)：ThumbRule 弯曲限制/对指回退、LateralRule 侧摆修正、JointRuleGuard 组合、输入校验。

触觉防护测试 (36 个)：冻结行为 (5 指)、回退行为、超时解除、力下降解除、手动重置、边界条件、矩阵解析 (6 个)。

## 依赖说明

| 依赖 | 用途 |
|------|------|
| `hand_forward_kinematics` | FK/IK 计算核心 (纯 Python) |
| `rclpy` | ROS 2 节点框架 |
| `sensor_msgs` | JointState 消息 |
| `geometry_msgs` | PoseArray, Pose 消息 |
| `std_msgs` | Float32MultiArray, String 消息 |
| `numpy` | 线性代数运算 |

## 文件清单

```
l10_hand_gateway/
├── README.md                        # 本文件
├── REPORT.md                        # 技术设计文档
├── package.xml                      # ROS 2 包描述
├── setup.py                         # Python 包配置
├── config/
│   └── tactile_guard.yaml           # 触觉防护配置 (独立文件，修改后重启生效)
├── resource/
│   └── l10_hand_gateway             # ament 资源标记
├── scripts/
│   └── fk_collision_analysis.py     # 碰撞查找表生成工具
├── tests/
│   ├── test_speed_limiter.py        # 速度映射单元测试
│   ├── test_motion_planner.py       # 五次样条轨迹规划测试
│   ├── test_query_dof0_limit.py     # 碰撞查询测试
│   ├── test_thumb_path_planner.py   # 拇指避让路径规划测试
│   ├── test_collision_guard.py      # 碰撞防护单元测试
│   ├── test_tactile_guard.py        # 触觉防护单元测试
│   └── test_gateway_integration.py  # 集成测试 (FK + 真实查找表)
└── l10_hand_gateway/
    ├── __init__.py
    ├── gateway_node.py              # 网关节点 — 反向代理 + 命令分发 + 安全防护
    ├── speed_limiter.py             # 速度映射 — 百分比 ↔ max_speed
    ├── motion_planner.py            # 五次样条轨迹 + 拇指避让路径
    ├── collision_guard.py           # 碰撞防护 — ThumbRule + LateralRule
    ├── collision_tables.json        # 预计算碰撞查找表
    ├── tactile_guard.py             # 触觉紧急停止 — 冻结/回退
    └── ik_solver.py                 # IK 求解器 — 网格采样 + Jacobian 精化
```
