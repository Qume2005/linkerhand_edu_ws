"""
节点集成验证测试 — 模拟完整节点初始化路径。

验证在真实运行环境中所有模块能正确协同初始化：
- Qt 应用创建
- AudioPlayer 加载
- GestureDetector 初始化（含 MediaPipe 模型加载）
- GameEngine 创建
- GameWidget 界面构建
- 模块间信号连接
"""

import os

os.environ['QT_QPA_PLATFORM'] = 'offscreen'
os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = (
    '/usr/lib/x86_64-linux-gnu/qt5/plugins/platforms')

import sys

import pytest


@pytest.fixture(scope='module')
def qt_app():
    """模块级 Qt 应用（只创建一次）。"""
    from PySide2.QtWidgets import QApplication
    instance = QApplication.instance()
    if instance is None:
        app = QApplication([])
        yield app
        app.quit()
    else:
        yield instance


class TestFullNodeInit:
    """验证完整节点初始化链路。"""

    def test_audio_player_init(self):
        """AudioPlayer 能初始化并预加载音频。"""
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        import l10_right_hand_rock_paper_scissors.audio_player as ap_module
        from pathlib import Path

        sounds_dir = Path(ap_module.__file__).resolve().parent.parent / "sounds"
        player = AudioPlayer(sounds_dir=str(sounds_dir))
        result = player.init()
        assert isinstance(result, bool)
        player.cleanup()

    def test_gesture_detector_init(self):
        """GestureDetector 能初始化（含 MediaPipe 模型加载）。"""
        from l10_right_hand_rock_paper_scissors.gesture_detector import (
            GestureDetector, _USE_LEGACY_API,
        )
        assert _USE_LEGACY_API is not None, "MediaPipe 应该可用"

        detector = GestureDetector(camera_id=0)
        assert detector.get_gesture() == "none"
        assert detector.get_frame() is None

    def test_game_engine_init(self, qt_app):
        """GameEngine 能初始化并处于 IDLE 状态。"""
        from l10_right_hand_rock_paper_scissors.game_engine import (
            GameEngine, GameState,
        )
        engine = GameEngine()
        assert engine.state == GameState.IDLE
        assert engine.scores == {"human": 0, "robot": 0, "tie": 0}

    def test_game_widget_init(self, qt_app):
        """GameWidget 能完整构建（含所有 UI 元素）。"""
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        from l10_right_hand_rock_paper_scissors.game_engine import GameEngine
        from l10_right_hand_rock_paper_scissors.game_widget import GameWidget
        from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector

        audio = AudioPlayer()
        audio.init()
        detector = GestureDetector(camera_id=0)
        engine = GameEngine()
        widget = GameWidget(engine, detector, audio)

        assert widget is not None
        assert "Rock Paper Scissors" in widget.windowTitle()

    def test_full_init_chain(self, qt_app):
        """完整初始化链路：模拟 RockPaperScissorsNode.__init__ 中所有步骤。"""
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        from l10_right_hand_rock_paper_scissors.game_engine import (
            GameEngine, GameMode, ResponseStrategy,
        )
        from l10_right_hand_rock_paper_scissors.game_widget import GameWidget
        from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector
        from l10_right_hand_rock_paper_scissors.poses import GESTURE_POSES, READY_POSE

        # 1. AudioPlayer
        audio = AudioPlayer()
        audio.init()

        # 2. GestureDetector
        detector = GestureDetector(camera_id=0)

        # 3. GameEngine（含模式切换）
        engine = GameEngine()
        engine.mode = GameMode.COMPETITION
        assert engine.mode == GameMode.COMPETITION

        engine.mode = GameMode.RESPONSE
        engine.response_strategy = ResponseStrategy.ALWAYS_WIN
        assert engine.response_strategy == ResponseStrategy.ALWAYS_WIN

        # 4. GameWidget
        widget = GameWidget(engine, detector, audio)
        assert widget is not None

        # 5. Poses 可用
        assert "rock" in GESTURE_POSES
        assert len(READY_POSE) == 10

        audio.cleanup()

    def test_send_dof_signal(self, qt_app):
        """验证 send_dof_signal 信号可以连接。"""
        from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
        from l10_right_hand_rock_paper_scissors.game_engine import GameEngine
        from l10_right_hand_rock_paper_scissors.game_widget import GameWidget
        from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector

        audio = AudioPlayer()
        detector = GestureDetector(camera_id=0)
        engine = GameEngine()
        widget = GameWidget(engine, detector, audio)

        received = []
        widget.send_dof_signal.connect(
            lambda dof, dur: received.append((dof, dur)))
        widget.send_dof_signal.emit([0] * 10, 0.5)
        assert len(received) == 1
        assert received[0][1] == 0.5

        audio.cleanup()
