"""回归测试：HandTrackingNode._init_mediapipe 的 logger.warning 调用契约。

锁定修复：`self.get_logger().warning()` 必须且只须接收 1 个位置参数
（一条已格式化的字符串），而不是多个位置参数。

测试通过 mock rclpy / mediapipe 等 heavy 依赖，直接驱动 `_init_mediapipe`
进入「主路径模型无效，使用备用路径」的分支，然后断言 warning 的调用形式。
"""

import inspect
import sys
import unittest
from unittest.mock import MagicMock, patch


def _install_mocks():
    """在导入 hand_tracking_node 前注入所有外部依赖的 mock。"""
    # rclpy 栈
    rclpy_mock = MagicMock()
    rclpy_mock.node.Node = type('Node', (), {})
    rclpy_mock.qos.QoSProfile = MagicMock
    rclpy_mock.qos.ReliabilityPolicy = type('ReliabilityPolicy', (), {'RELIABLE': 1})
    sys.modules['rclpy'] = rclpy_mock
    sys.modules['rclpy.node'] = rclpy_mock.node
    sys.modules['rclpy.qos'] = rclpy_mock.qos

    # ROS 消息类型
    for pkg in ('geometry_msgs', 'geometry_msgs.msg',
                'sensor_msgs', 'sensor_msgs.msg',
                'std_msgs', 'std_msgs.msg'):
        sys.modules[pkg] = MagicMock()

    # mediapipe task API
    mp_mock = MagicMock()
    mp_mock.__path__ = ['/fake/mediapipe']
    mp_mock.tasks.python.vision.HandLandmarkerOptions = MagicMock
    mp_mock.tasks.python.vision.HandLandmarker.create_from_options = MagicMock(return_value=MagicMock())
    mp_mock.tasks.python.core.base_options.BaseOptions = MagicMock
    for pkg in ('mediapipe', 'mediapipe.tasks', 'mediapipe.tasks.python',
                'mediapipe.tasks.python.vision', 'mediapipe.tasks.python.core',
                'mediapipe.tasks.python.core.base_options'):
        sys.modules[pkg] = mp_mock if pkg == 'mediapipe' else MagicMock()
    # 修正：mediapipe 子模块需要正确的层级
    sys.modules['mediapipe.tasks.python.vision'].HandLandmarker = mp_mock.tasks.python.vision.HandLandmarker
    sys.modules['mediapipe.tasks.python.vision'].HandLandmarkerOptions = mp_mock.tasks.python.vision.HandLandmarkerOptions
    sys.modules['mediapipe.tasks.python.core.base_options'].BaseOptions = mp_mock.tasks.python.core.base_options.BaseOptions

    # 项目内依赖
    sys.modules['hand_forward_kinematics'] = MagicMock()
    sys.modules['hand_forward_kinematics.kinematics'] = MagicMock()
    sys.modules['l10_right_hand_tracking.camera_capture'] = MagicMock()


_install_mocks()

from l10_right_hand_tracking.hand_tracking_node import HandTrackingNode  # noqa: E402


class TestLoggerWarningRegression(unittest.TestCase):
    """验证 _init_mediapipe 在「主模型无效、备用模型有效」时 warning 调用形式。"""

    def _make_node_with_mocked_logger(self):
        """绕过 Node.__init__，直接构造 HandTrackingNode 并注入 mock logger。"""
        node = HandTrackingNode.__new__(HandTrackingNode)
        node._logger = MagicMock()
        node.get_logger = MagicMock(return_value=node._logger)
        return node

    def _trigger_fallback_warning(self, node):
        """通过 patch os/zipfile/urllib 强制进入「主路径无效，使用备用路径」分支。"""
        def fake_isfile(path):
            # 主路径在 /fake/mediapipe 下，备用路径在 ~/.local 下
            return '.local' in path

        def fake_remove(path):
            pass

        def fake_makedirs(path, exist_ok=False):
            pass

        def fake_urlretrieve(url, filename):
            pass

        mock_zip_instance = MagicMock()
        mock_zip_instance.__enter__ = MagicMock(return_value=mock_zip_instance)
        mock_zip_instance.__exit__ = MagicMock(return_value=False)

        with patch('os.path.isfile', side_effect=fake_isfile) as mock_isfile, \
             patch('os.remove', side_effect=fake_remove) as mock_remove, \
             patch('os.makedirs', side_effect=fake_makedirs) as mock_makedirs, \
             patch('zipfile.ZipFile', return_value=mock_zip_instance) as mock_zip, \
             patch('urllib.request.urlretrieve', side_effect=fake_urlretrieve) as mock_retrieve:
            node._init_mediapipe()

    def test_warning_receives_single_formatted_string(self):
        """warning() 必须且只须被调用一次，且传入恰好 1 个字符串参数。"""
        node = self._make_node_with_mocked_logger()
        self._trigger_fallback_warning(node)

        # 断言 warning 被调用
        node._logger.warning.assert_called_once()

        # 断言调用参数：恰好 1 个位置参数，且为字符串
        call_args = node._logger.warning.call_args
        positional_args = call_args[0] if call_args[0] else ()
        keyword_args = call_args[1]

        self.assertEqual(
            len(positional_args), 1,
            f"get_logger().warning() 应接收恰好 1 个位置参数，实际收到 {len(positional_args)} 个: "
            f"{positional_args!r}"
        )
        self.assertIsInstance(
            positional_args[0], str,
            f"warning() 的唯一位置参数应为字符串，实际为 {type(positional_args[0]).__name__}"
        )
        # 不应以 keyword args 形式额外传递消息
        self.assertFalse(keyword_args, "warning() 不应使用额外 keyword 参数传递消息")

    def test_info_and_error_also_use_single_string(self):
        """同一方法体内，info / error 也应遵循单字符串契约（防御性断言）。"""
        node = self._make_node_with_mocked_logger()

        # 构造一个能触发 info 和 error 的极端场景
        def fake_isfile(path):
            return False  # 所有路径都无效，触发下载失败后的 error

        with patch('os.path.isfile', side_effect=fake_isfile), \
             patch('os.remove'), \
             patch('os.makedirs', side_effect=lambda *a, **k: None), \
             patch('zipfile.ZipFile', side_effect=Exception('bad')), \
             patch('urllib.request.urlretrieve', side_effect=Exception('network')):
            with self.assertRaises(Exception):
                node._init_mediapipe()

        # error 路径：应被调用且仅 1 个字符串参数
        node._logger.error.assert_called_once()
        err_args = node._logger.error.call_args[0]
        self.assertEqual(len(err_args), 1)
        self.assertIsInstance(err_args[0], str)

    def test_multi_arg_warning_fails_assertion(self):
        """独立验证：断言逻辑拒绝多参数调用（对应修复前的旧代码）。

        旧代码: self.get_logger().warning("prefix", "message")
        新代码: self.get_logger().warning("prefix: message")
        """
        mock_logger = MagicMock()
        # 模拟旧代码行为：warning("prefix", "message")
        mock_logger.warning('prefix', 'message')

        positional_args = mock_logger.warning.call_args[0]
        # 这正是主回归测试中的核心断言
        with self.assertRaises(AssertionError):
            self.assertEqual(len(positional_args), 1,
                f"旧代码的多参数 warning 调用应被拒绝：实际收到 {len(positional_args)} 个位置参数")


class TestCameraIdParameter(unittest.TestCase):
    """验证 camera_id 参数声明、读取和传递管道。"""

    def test_camera_id_declared_with_default_minus_one(self):
        """HandTrackingNode.__init__ 必须声明 camera_id 参数，默认值 -1（自动扫描）。"""
        source = inspect.getsource(HandTrackingNode.__init__)
        self.assertIn(
            "declare_parameter('camera_id', -1)",
            source,
            "HandTrackingNode.__init__ 应包含 declare_parameter('camera_id', -1)"
        )

    def test_camera_id_read_as_integer(self):
        """camera_id 参数应以 integer_value 形式读取（与 launch 传递的整数一致）。"""
        source = inspect.getsource(HandTrackingNode.__init__)
        self.assertIn(
            "get_parameter_value().integer_value",
            source,
            "camera_id 应以 integer_value 读取，确保与 launch 层传递的整数类型一致"
        )

    def test_camera_id_forwarded_to_camera_capture(self):
        """camera_id 读取后应传递给 CameraCapture。"""
        source = inspect.getsource(HandTrackingNode.__init__)
        self.assertIn(
            "CameraCapture(cam_id)",
            source,
            "camera_id 读取后应传递给 CameraCapture(cam_id)"
        )

    def test_custom_camera_id_value_used_correctly(self):
        """验证非默认 camera_id 值可正确传递给 CameraCapture。

        使用返回 mock 对象的函数模拟 get_parameter 链式调用。
        """
        mock_param_value = MagicMock()
        mock_param_value.integer_value = 2
        # 确保 get_parameter_value() 返回 mock_param_value 自身，而非自动创建子 mock
        mock_param_value.get_parameter_value.return_value = mock_param_value

        def fake_get_parameter(name):
            if name == 'camera_id':
                return mock_param_value
            raise KeyError(name)

        node = HandTrackingNode.__new__(HandTrackingNode)
        node.get_parameter = fake_get_parameter

        # 模拟节点中的 camera_id 读取逻辑
        cam_id = node.get_parameter('camera_id').get_parameter_value().integer_value
        self.assertEqual(cam_id, 2)

        # 验证该值可直接用于 CameraCapture 构造函数
        from l10_right_hand_camera.camera_capture import CameraCapture
        cap = CameraCapture(cam_id)
        self.assertEqual(cap._camera_id, 2)


if __name__ == '__main__':
    unittest.main()
