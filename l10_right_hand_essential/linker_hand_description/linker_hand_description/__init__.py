"""
linker_hand_description — LinkerHand 灵巧手模型描述包

本包为 LinkerHand 系列灵巧手提供统一的模型文件访问接口，包含以下资产：

- **MuJoCo XML 模型文件** (``.xml``)：用于物理仿真，由 MuJoCo 后端节点和 FK 库直接加载
- **URDF 模型文件** (``.urdf``)：用于 RViz2 可视化，由 robot_state_publisher 加载
- **STL 网格文件**：手指各连杆的三维网格，被 XML/URDF 以相对路径引用

当前主要服务于 **L10 右手**，同时包含 L6/L7/L20/L21 等其他型号的资产文件。

典型用法::

    from linker_hand_description import get_urdf_path

    # 获取 L10 右手 MuJoCo XML 的绝对路径（供 mujoco.MjModel.from_xml_path 使用）
    xml_path = get_urdf_path()

    # 获取其他文件
    urdf_path = get_urdf_path("linker_hand_l10_right.urdf")

目录结构::

    linker_hand_description/
    ├── __init__.py          (本文件，提供 4 个路径辅助函数)
    └── urdf/
        ├── L10/
        │   └── linker_hand_l10_right/
        │       ├── linker_hand_l10_right.xml    (MuJoCo XML)
        │       ├── linker_hand_l10_right.urdf   (URDF)
        │       └── *.STL                        (连杆网格)
        ├── L20/ ...
        ├── L21/ ...
        ├── L6/ ...
        └── L7/ ...
"""

import os


def get_urdf_path(filename="linker_hand_l10_right.xml"):
    """返回 L10 右手 MuJoCo XML 文件的绝对路径。

    默认返回 MuJoCo XML 文件路径。也可通过 ``filename`` 参数获取同目录下
    的其他文件（如 URDF 文件）。

    Args:
        filename: 目标文件名，默认 ``"linker_hand_l10_right.xml"``

    Returns:
        str: 所请求文件的绝对路径
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right", filename
    )


def get_urdf_dir():
    """返回 L10 右手模型目录（包含 XML/URDF/STL）的绝对路径。

    Returns:
        str: 模型目录的绝对路径，例如
             ``".../linker_hand_description/urdf/L10/linker_hand_l10_right"``
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right"
    )


def get_model_path(filename="linker_hand_l10_right.urdf"):
    """返回 L10 右手 URDF/模型文件的绝对路径。

    默认返回 URDF 文件路径（供 RViz2 / robot_state_publisher 使用）。
    与 :func:`get_urdf_path` 功能相同，仅默认文件名不同。

    Args:
        filename: 目标文件名，默认 ``"linker_hand_l10_right.urdf"``

    Returns:
        str: 所请求文件的绝对路径
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right", filename
    )


def get_model_dir():
    """返回 L10 右手模型目录的绝对路径。

    与 :func:`get_urdf_dir` 完全相同，提供另一种语义化命名。

    Returns:
        str: 模型目录的绝对路径
    """
    return os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "urdf", "L10", "linker_hand_l10_right"
    )
