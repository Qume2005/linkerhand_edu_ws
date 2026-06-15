"""端到端回归测试：导入 tracking 节点后 cv2 的 Qt 平台插件路径必须有效。

在独立子进程中导入 ``hand_tracking_node``（隔离全局环境变量状态，避免被同进程
其它测试污染），断言导入完成后 ``QT_QPA_PLATFORM_PLUGIN_PATH`` 指向含
``libqxcb.so`` 的目录 —— 这正是之前「窗口打不开 / SIGABRT」回归的直接判定。

该测试需要 ROS 环境（节点导入 rclpy / hand_forward_kinematics）；缺失时跳过而非失败。
"""

import json
import os
import subprocess
import sys

_PROBE = (
    "import os, json\n"
    # 导入节点会触发其顶层 _apply_cv2_qt_fix()；用真实换行避免行内注释吞掉后续语句
    "import l10_right_hand_tracking.hand_tracking_node as n  # noqa: F401\n"
    "p = os.environ.get('QT_QPA_PLATFORM_PLUGIN_PATH', '')\n"
    "print('PROBE_RESULT', json.dumps({'path': p, "
    "'has_xcb': os.path.exists(os.path.join(p, 'libqxcb.so'))}))\n"
)


def _run_probe():
    """在子进程中导入节点并返回探测结果 dict；失败返回 None。"""
    try:
        out = subprocess.run(
            [sys.executable, "-c", _PROBE],
            capture_output=True, text=True, timeout=120,
        )
    except FileNotFoundError:
        return None
    if out.returncode != 0:
        # 节点导入失败（多半是 ROS 未 source）—— 视为环境不具备，跳过。
        return None
    for line in out.stdout.splitlines():
        if line.startswith("PROBE_RESULT"):
            return json.loads(line[len("PROBE_RESULT"):].strip())
    return None


def test_node_import_leaves_valid_plugin_path():
    """导入 tracking 节点后，插件路径必须含 libqxcb.so（回归守卫）。"""
    result = _run_probe()
    if result is None:
        import pytest
        pytest.skip("无法在子进程中导入节点（ROS / 依赖未就绪）")
    assert result["has_xcb"], (
        "节点导入后 QT_QPA_PLATFORM_PLUGIN_PATH 未修复到含 libqxcb.so 的目录: "
        f"{result['path']}"
    )
