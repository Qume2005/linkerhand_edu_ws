"""回归测试：cv2 Qt 平台插件路径修复。

背景：opencv-python 在 ``import cv2`` 时会把 ``QT_QPA_PLATFORM_PLUGIN_PATH``
覆盖为自带的 ``cv2/qt/plugins``；若该目录为空（插件被整体移到 ``cv2/qt_disabled``，
见 RPS），``cv2.imshow`` 因找不到 xcb 平台插件而 SIGABRT，tracking 窗口打不开。

这些测试锁定修复的正确性，防止「各包依赖冲突」类问题再次出现：
解析到的插件目录必须存在、含 ``libqxcb.so``、且位于 cv2 包内（而非系统 Qt 目录）。
"""

import os

import pytest

from l10_right_hand_tracking.qt_plugin_fix import (
    apply,
    resolve_platform_plugin_dir,
)


def test_resolve_returns_existing_dir():
    """修复必须能定位到一个真实存在的插件目录。"""
    d = resolve_platform_plugin_dir()
    assert d is not None, "未定位到 cv2 qt_disabled 平台插件目录（cv2 GUI 将无法工作）"
    assert os.path.isdir(d), f"解析到的插件目录不存在: {d}"


def test_resolve_returns_dir_containing_xcb_plugin():
    """核心回归断言：插件目录必须含 libqxcb.so，否则 cv2.imshow SIGABRT。"""
    d = resolve_platform_plugin_dir()
    if d is None:
        pytest.skip("本机未安装 cv2 qt_disabled 目录（非典型安装）")
    assert os.path.exists(os.path.join(d, "libqxcb.so")), (
        f"xcb 平台插件缺失于 {d} —— cv2.imshow 将崩溃"
    )


def test_resolve_returns_cv2_owned_dir_not_system():
    """修复必须使用 cv2 自带插件，而非系统 Qt 插件。

    指向系统插件会触发 Qt「二实例冲突」（cv2 自带 Qt 与系统 Qt5 共存），
    这是 RPS 把 cv2 的 Qt 禁用（移到 qt_disabled）的根本原因。
    """
    import cv2

    d = resolve_platform_plugin_dir()
    if d is None:
        pytest.skip("本机未安装 cv2 qt_disabled 目录")
    cv2_root = os.path.abspath(cv2.__path__[0])
    assert os.path.abspath(d).startswith(cv2_root + os.sep), (
        f"插件目录不在 cv2 包内，可能指向系统 Qt 从而引发冲突: {d}"
    )


def test_apply_sets_env_to_valid_plugin_dir(monkeypatch):
    """apply() 必须把 QT_QPA_PLATFORM_PLUGIN_PATH 设为含 libqxcb.so 的目录。"""
    monkeypatch.delenv("QT_QPA_PLATFORM_PLUGIN_PATH", raising=False)
    d = apply()
    if d is None:
        pytest.skip("本机未安装 cv2 qt_disabled 目录")
    assert os.environ["QT_QPA_PLATFORM_PLUGIN_PATH"] == d
    assert os.path.exists(os.path.join(d, "libqxcb.so"))
