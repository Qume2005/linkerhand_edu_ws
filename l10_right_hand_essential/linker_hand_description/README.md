# linker_hand_description

LinkerHand 灵巧手模型描述包 -- 提供 URDF、STL 网格和 MuJoCo XML 模型文件的统一访问接口。

## 功能概述

本包是整个 LinkerHand 工作空间的**模型资产中心**，不包含任何 ROS 节点或业务逻辑，仅通过 4 个 Python 辅助函数向外暴露模型文件的绝对路径。所有需要加载手部模型的组件（仿真节点、FK 库、可视化节点等）都通过本包定位文件。

### 模型文件类型

| 文件类型 | 用途 | 使用者 |
|---------|------|--------|
| `.xml` (MuJoCo XML) | 物理仿真引擎的模型定义 | `l10_right_hand_mujoco_sim`、`hand_forward_kinematics` |
| `.urdf` | ROS 机器人模型描述 | `l10_right_hand_viz`（通过 robot_state_publisher） |
| `.STL` | 连杆三维网格 | 被 XML/URDF 以相对路径引用 |

### 支持的型号

当前 `urdf/` 目录下包含以下型号的资产文件：

- **L10**：10 自由度灵巧手（主力型号，本工作空间核心支持对象）
- **L20**：20 自由度型号
- **L21**：21 自由度型号
- **L6**：6 自由度入门型号
- **L7**：7 自由度型号

每个型号下按左手/右手分别组织目录。

## API 参考

本包提供 4 个路径辅助函数，全部位于 `linker_hand_description` 模块的 `__init__.py` 中：

### `get_urdf_path(filename="linker_hand_l10_right.xml")`

返回 L10 右手模型目录下指定文件的绝对路径。默认返回 MuJoCo XML 文件。

```python
from linker_hand_description import get_urdf_path

# 获取 MuJoCo XML（供 mujoco.MjModel.from_xml_path 使用）
xml_path = get_urdf_path()  # .../urdf/L10/linker_hand_l10_right/linker_hand_l10_right.xml

# 获取 URDF 文件
urdf_path = get_urdf_path("linker_hand_l10_right.urdf")
```

**参数：**
- `filename` (str): 目标文件名，默认 `"linker_hand_l10_right.xml"`

**返回：** `str` -- 文件的绝对路径

### `get_urdf_dir()`

返回 L10 右手模型目录的绝对路径（不包含文件名）。

```python
from linker_hand_description import get_urdf_dir

model_dir = get_urdf_dir()  # .../urdf/L10/linker_hand_l10_right/
```

**返回：** `str` -- 模型目录的绝对路径

### `get_model_path(filename="linker_hand_l10_right.urdf")`

与 `get_urdf_path` 功能完全相同，仅默认文件名不同（默认返回 URDF 而非 XML）。主要用于 RViz2 可视化场景。

```python
from linker_hand_description import get_model_path

urdf = get_model_path()  # 默认返回 .urdf 文件
```

**参数：**
- `filename` (str): 目标文件名，默认 `"linker_hand_l10_right.urdf"`

**返回：** `str` -- 文件的绝对路径

### `get_model_dir()`

与 `get_urdf_dir` 完全相同，提供另一种语义化命名。

**返回：** `str` -- 模型目录的绝对路径

## 目录结构

```
linker_hand_description/
├── __init__.py                     # 模块入口，提供 4 个路径辅助函数
├── package.xml                     # ROS2 包描述 (ament_python)
├── setup.py                        # 构建配置，收集 STL/URDF/XML 到 share 目录
├── resource/
│   └── linker_hand_description     # ament 资源标记文件
└── linker_hand_description/
    ├── __init__.py                 # 路径辅助函数实现
    └── urdf/
        ├── L10/
        │   └── linker_hand_l10_right/
        │       ├── linker_hand_l10_right.xml    # MuJoCo 模型定义
        │       ├── linker_hand_l10_right.urdf   # URDF 模型定义
        │       └── meshes/                      # STL 网格文件目录
        │           ├── hand_base_link.STL       # 手掌基座
        │           ├── thumb_*.STL              # 拇指 5 个连杆
        │           ├── index_*.STL              # 食指 4 个连杆
        │           ├── middle_*.STL             # 中指 3 个连杆
        │           ├── ring_*.STL               # 无名指 4 个连杆
        │           └── pinky_*.STL              # 小指 4 个连杆
        ├── L20/ ...                             # L20 型号资产
        ├── L21/ ...                             # L21 型号资产
        ├── L6/ ...                              # L6 型号资产
        └── L7/ ...                              # L7 型号资产
```

## 依赖

本包**无任何外部运行时依赖**，仅使用 Python 标准库 `os` 模块。

构建依赖：`rclpy`（仅用于 ROS2 包索引注册，路径函数本身不需要 ROS）。

## 构建与安装

```bash
# 在工作空间根目录下
colcon build --packages-select linker_hand_description

# 构建后 source
source install/setup.bash
```

构建时 `setup.py` 会将 `urdf/L10/linker_hand_l10_right/` 下的 `.STL`、`.urdf`、`.xml` 文件安装到 `share/linker_hand_description/urdf/L10/linker_hand_l10_right/`，确保 ROS2 运行时能正确定位模型文件。

## 文件清单

| 文件 | 说明 |
|------|------|
| `linker_hand_description/__init__.py` | 4 个路径辅助函数 |
| `setup.py` | 构建配置 |
| `package.xml` | ROS2 包元数据 |
| `urdf/L10/linker_hand_l10_right/*.xml` | L10 右手 MuJoCo 模型 |
| `urdf/L10/linker_hand_l10_right/*.urdf` | L10 右手 URDF 模型 |
| `urdf/L10/linker_hand_l10_right/*.STL` | L10 右手连杆网格 (约 30 个) |
