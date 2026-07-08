"""
运行时冒烟测试 — 验证所有模块能正确导入和实例化。

这些测试覆盖单元测试无法触及的初始化路径：
- MediaPipe API 检测和 detector 初始化
- AudioPlayer 初始化
- 模块间依赖关系
- 节点入口函数可调用性
- Qt 平台插件路径修复
"""

import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
os.environ.setdefault('QT_QPA_PLATFORM_PLUGIN_PATH',
                       '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms')

import pytest


class TestModuleImport:
    """验证所有模块能成功导入。"""

    def test_import_poses(self):
        from l10_right_hand_rock_paper_scissors.poses import (
            GESTURE_POSES, READY_POSE, ROCK_POSE, PAPER_POSE, SCISSORS_POSE,
        )
        assert set(GESTURE_POSES.keys()) == {"rock", "paper", "scissors"}
        assert len(READY_POSE) == 10
        for name, pose in GESTURE_POSES.items():
            assert len(pose) == 10, f"{name} 姿态应为 10-DOF"
            assert all(0 <= v <= 255 for v in pose), f"{name} 姿态值应在 0-255"

    def test_import_game_engine(self):
        from l10_right_hand_rock_paper_scissors.game_engine import (
            GameEngine, GameMode, GameState, GameResult, ResponseStrategy,
            judge, pick_robot_gesture, BEATS, GESTURES,
        )
        assert len(GESTURES) == 3
        assert len(BEATS) == 3

    def test_import_audio_player(self):
        from l10_right_hand_rock_paper_scissors.audio_player import (
            AudioPlayer, AUDIO_FILES,
        )
        assert len(AUDIO_FILES) == 9  # 9 个音频条目

    def test_import_gesture_detector(self):
        from l10_right_hand_rock_paper_scissors.gesture_detector import (
            GestureDetector, GESTURE_ROCK, GESTURE_PAPER, GESTURE_SCISSORS,
            GESTURE_NONE, _USE_LEGACY_API,
        )
        assert _USE_LEGACY_API is not None, "MediaPipe 应该可用"

    def test_import_game_widget(self):
        from l10_right_hand_rock_paper_scissors.game_widget import GameWidget
        assert GameWidget is not None

    def test_import_node(self):
        from l10_right_hand_rock_paper_scissors.rock_paper_scissors_node import (
            RockPaperScissorsNode, main,
        )
        assert callable(main)


class TestDetectorInit:
    """验证 GestureDetector 能正确初始化。"""

    def test_detector_instantiates(self):
        from l10_right_hand_rock_paper_scissors.gesture_detector import (
            GestureDetector, _USE_LEGACY_API,
        )
        # 不需要摄像头，只验证 __init__ 不抛异常
        detector = GestureDetector()
        assert detector is not None
        assert detector.get_gesture() == "none"

    def test_detector_with_explicit_camera_id(self):
        """显式传入 camera_id=1 应正常初始化（不触发自动扫描）。"""
        from l10_right_hand_rock_paper_scissors.gesture_detector import (
            GestureDetector, _USE_LEGACY_API,
        )
        detector = GestureDetector(camera_id=1)
        assert detector is not None
        assert detector.get_gesture() == "none"
        assert detector._camera_id == 1

    def test_detector_classify_is_static(self):
        from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector
        # _classify 是 staticmethod，可以不实例化直接调用
        assert isinstance(GestureDetector.__dict__["_classify"], staticmethod)


class TestAudioPlayerInit:
    """验证 AudioPlayer 能正确初始化。"""

    def test_player_instantiates(self):
        import tempfile
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        # 使用空目录避免加载实际音频
        with tempfile.TemporaryDirectory() as tmpdir:
            player = AudioPlayer(sounds_dir=tmpdir)
            assert player is not None
            assert not player.available  # 空目录，无音频

    def test_player_play_no_audio_no_crash(self):
        import tempfile
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        with tempfile.TemporaryDirectory() as tmpdir:
            player = AudioPlayer(sounds_dir=tmpdir)
            player.init()
            # 播放不存在的音频不应崩溃
            player.play("nonexistent")
            assert not player.is_playing()


class TestGameEngineInit:
    """验证 GameEngine 能正确初始化（需要 Qt app）。"""

    @pytest.fixture
    def app(self):
        from PySide2.QtWidgets import QApplication
        instance = QApplication.instance()
        if instance is None:
            return QApplication([])
        return instance

    def test_engine_instantiates(self, app):
        from l10_right_hand_rock_paper_scissors.game_engine import GameEngine
        engine = GameEngine()
        assert engine.state.value == "idle"
        assert engine.scores == {"human": 0, "robot": 0, "tie": 0}


class TestPosesValues:
    """验证姿态值合理性。"""

    def test_rock_is_fist(self):
        from l10_right_hand_rock_paper_scissors.poses import ROCK_POSE
        # 石头：食指~小指弯曲 DOF 应该是低值（接近 0），拇指有一定弯曲以包裹拳头
        fist_bent = [2, 3, 4, 5]   # index_bend, middle, ring, little — 完全弯曲
        for i in fist_bent:
            assert ROCK_POSE[i] < 50, f"Rock 姿态 DOF[{i}]={ROCK_POSE[i]} 应接近 0"
        # 拇指弯曲（DOF0）和侧摆（DOF1）应为握拳包裹位，不是 0 但也不伸直
        assert 50 <= ROCK_POSE[0] <= 200, f"Rock 姿态 DOF[0]={ROCK_POSE[0]} 拇指应有适度弯曲"

    def test_paper_is_open(self):
        from l10_right_hand_rock_paper_scissors.poses import PAPER_POSE
        # 布：所有弯曲 DOF 应该是高值（接近 255）
        bend_indices = [0, 2, 3, 4, 5]
        for i in bend_indices:
            assert PAPER_POSE[i] > 200, f"Paper 姿态 DOF[{i}]={PAPER_POSE[i]} 应接近 255"

    def test_scissors_index_middle_extended(self):
        from l10_right_hand_rock_paper_scissors.poses import SCISSORS_POSE
        # 剪刀：index(2) 和 middle(3) 弯曲度高值（伸直）
        assert SCISSORS_POSE[2] > 200, "Scissors index_bend 应伸直"
        assert SCISSORS_POSE[3] > 200, "Scissors middle_bend 应伸直"
        # ring(4) 和 little(5) 弯曲度低值（弯曲）
        assert SCISSORS_POSE[4] < 50, "Scissors ring_bend 应弯曲"
        assert SCISSORS_POSE[5] < 50, "Scissors little_bend 应弯曲"

    def test_ready_pose_all_valid(self):
        from l10_right_hand_rock_paper_scissors.poses import READY_POSE
        assert len(READY_POSE) == 10
        assert all(0 <= v <= 255 for v in READY_POSE)
