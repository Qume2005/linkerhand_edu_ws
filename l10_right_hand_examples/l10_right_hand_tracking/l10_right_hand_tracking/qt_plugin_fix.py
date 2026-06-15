"""cv2 (opencv-python) Qt 平台插件路径修复。

问题
----
``opencv-python`` 在 ``import cv2`` 时会把环境变量 ``QT_QPA_PLATFORM_PLUGIN_PATH``
覆盖为自带的 ``cv2/qt/plugins``。本机该目录为空 —— cv2 的 Qt 平台插件被整体移到了
``cv2/qt_disabled``（这是为了让 RPS 改用系统 Qt5 / PySide2 显示、避免 cv2 自带 Qt
与系统 Qt5 的「二实例冲突」）。

后果：tracking 节点的 ``cv2.imshow`` 在空目录里找不到 xcb 平台插件而 ``SIGABRT``，
跟踪窗口打不开。这与 tracking 代码无关 —— 即便不设置任何环境变量，``cv2.imshow``
同样崩溃。

修复
----
在 ``import cv2`` **之后**，把插件路径指回 cv2 自己的 ``qt_disabled`` 插件目录。这些
插件与 cv2 自带 Qt（5.15.x）同源，不会触发二实例冲突；且本设置仅作用于当前进程，
不影响作为独立进程运行的 RPS。

注意：不能在 ``import cv2`` 之前设置（会被 cv2 覆盖），也不能指向系统 Qt 插件
（会引发 Qt 二实例冲突）。
"""

import os

import cv2


def resolve_platform_plugin_dir() -> str | None:
    """返回 cv2 自带 Qt 平台插件所在目录（``cv2/qt_disabled/plugins/platforms``）。

    Returns:
        目录绝对路径；若该目录不存在则返回 ``None``（非典型安装）。
    """
    candidate = os.path.join(cv2.__path__[0], "qt_disabled", "plugins", "platforms")
    return candidate if os.path.isdir(candidate) else None


def apply() -> str | None:
    """把 ``QT_QPA_PLATFORM_PLUGIN_PATH`` 指向 cv2 自带的插件目录。

    必须在 ``import cv2`` 之后调用，以覆盖 cv2 对该环境变量的写入。
    仅当定位到有效插件目录时才设置。

    Returns:
        实际写入的插件目录；未定位到则返回 ``None``（保持环境变量不变）。
    """
    plugin_dir = resolve_platform_plugin_dir()
    if plugin_dir is not None:
        os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] = plugin_dir
    return plugin_dir
