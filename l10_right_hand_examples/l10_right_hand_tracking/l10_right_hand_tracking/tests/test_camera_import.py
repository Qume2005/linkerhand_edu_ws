"""验证 CameraCapture 从共享包 l10_right_hand_camera 正确导入。"""

import unittest


class TestCameraImportFromSharedPackage(unittest.TestCase):
    """tracking 包应从 l10_right_hand_camera 导入 CameraCapture。"""

    def test_import_camera_capture_from_shared_package(self):
        """从共享包导入 CameraCapture 应成功。"""
        from l10_right_hand_camera.camera_capture import CameraCapture
        assert CameraCapture is not None

    def test_import_find_available_camera_from_shared_package(self):
        """从共享包导入 find_available_camera 应成功。"""
        from l10_right_hand_camera.camera_capture import find_available_camera
        assert callable(find_available_camera)


if __name__ == '__main__':
    unittest.main()
