"""
PySide2 游戏主界面 — 石头剪刀布 GUI。

布局: 左侧摄像头画面 | 右侧控制面板 + 比分 + 结果展示
"""

import time

import cv2
import numpy as np
from PySide2.QtCore import Qt, QTimer, Signal
from PySide2.QtGui import QImage, QPixmap, QFont, QColor, QPalette
from PySide2.QtWidgets import (
    QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QRadioButton, QSizePolicy, QVBoxLayout, QWidget,
)

from l10_right_hand_rock_paper_scissors.audio_player import AudioPlayer
from l10_right_hand_rock_paper_scissors.game_engine import (
    GESTURE_DISPLAY, GESTURE_EMOJI, GameEngine, GameMode,
    GameState, ResponseStrategy,
)
from l10_right_hand_rock_paper_scissors.gesture_detector import GestureDetector


# 结果显示样式
RESULT_STYLES = {
    "human_wins": {"color": "#FFD700", "text": "YOU WIN!",  "bg": "#1a1a2e"},
    "robot_wins": {"color": "#FF4444", "text": "I WIN!",    "bg": "#2e1a1a"},
    "tie":        {"color": "#C0C0C0", "text": "TIE!",      "bg": "#1a2e1a"},
    "timeout":    {"color": "#888888", "text": "TIME OUT!", "bg": "#2e2e1a"},
}


class GameWidget(QWidget):
    """石头剪刀布游戏主界面。"""

    # 向节点发送手势信号
    start_game_signal = Signal()
    send_dof_signal = Signal(list, float)  # (dof_values, duration)

    def __init__(self, engine: GameEngine, detector: GestureDetector,
                 audio: AudioPlayer, parent=None):
        super().__init__(parent)
        self._engine = engine
        self._detector = detector
        self._audio = audio

        self._countdown_timer = QTimer(self)
        self._countdown_timer.setSingleShot(True)
        self._countdown_step = 0
        self._countdown_steps = []

        self._frame_timer = QTimer(self)
        self._frame_timer.timeout.connect(self._update_camera_frame)

        self._gesture_timeout_timer = QTimer(self)
        self._gesture_timeout_timer.setSingleShot(True)
        self._gesture_timeout_timer.timeout.connect(self._on_gesture_timeout)

        self._result_timer = QTimer(self)
        self._result_timer.setSingleShot(True)
        self._result_timer.timeout.connect(self._on_result_done)

        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        self.setWindowTitle("Rock Paper Scissors — LinkerHand")
        self.setMinimumSize(960, 540)

        main_layout = QHBoxLayout(self)

        # === 左侧: 摄像头画面 ===
        left_frame = QFrame()
        left_layout = QVBoxLayout(left_frame)
        left_layout.setContentsMargins(4, 4, 4, 4)

        self._camera_label = QLabel("Waiting for camera...")
        self._camera_label.setMinimumSize(640, 480)
        self._camera_label.setAlignment(Qt.AlignCenter)
        self._camera_label.setStyleSheet(
            "background-color: #000; color: #666; font-size: 18px;")
        left_layout.addWidget(self._camera_label)

        # === 右侧: 控制面板 ===
        right_frame = QFrame()
        right_frame.setMaximumWidth(300)
        right_layout = QVBoxLayout(right_frame)
        right_layout.setContentsMargins(8, 8, 8, 8)

        # 标题
        title = QLabel("Rock Paper Scissors")
        title.setFont(QFont("Arial", 16, QFont.Bold))
        title.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(title)

        # 模式选择
        mode_label = QLabel("Game Mode")
        mode_label.setFont(QFont("Arial", 11, QFont.Bold))
        right_layout.addWidget(mode_label)

        self._mode_competition = QRadioButton("Competition")
        self._mode_response = QRadioButton("Response")
        self._mode_competition.setChecked(True)
        mode_layout = QHBoxLayout()
        mode_layout.addWidget(self._mode_competition)
        mode_layout.addWidget(self._mode_response)
        right_layout.addLayout(mode_layout)

        # 响应策略（仅响应模式可用）
        self._strategy_label = QLabel("Response Strategy")
        self._strategy_label.setFont(QFont("Arial", 11, QFont.Bold))
        right_layout.addWidget(self._strategy_label)

        self._strat_win = QRadioButton("Always Win")
        self._strat_lose = QRadioButton("Always Lose")
        self._strat_tie = QRadioButton("Always Tie")
        self._strat_random = QRadioButton("Random")
        self._strat_random.setChecked(True)
        self._set_strategy_enabled(False)

        strat_grid = QGridLayout()
        strat_grid.addWidget(self._strat_win, 0, 0)
        strat_grid.addWidget(self._strat_lose, 0, 1)
        strat_grid.addWidget(self._strat_tie, 1, 0)
        strat_grid.addWidget(self._strat_random, 1, 1)
        right_layout.addLayout(strat_grid)

        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        right_layout.addWidget(line)

        # 比分板
        score_title = QLabel("Scoreboard")
        score_title.setFont(QFont("Arial", 11, QFont.Bold))
        right_layout.addWidget(score_title)

        self._score_label = QLabel("You: 0  |  Robot: 0  |  Tie: 0")
        self._score_label.setFont(QFont("Arial", 13))
        self._score_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._score_label)

        # 分隔线
        line2 = QFrame()
        line2.setFrameShape(QFrame.HLine)
        right_layout.addWidget(line2)

        # 结果展示
        self._result_label = QLabel("")
        self._result_label.setFont(QFont("Arial", 28, QFont.Bold))
        self._result_label.setAlignment(Qt.AlignCenter)
        self._result_label.setMinimumHeight(100)
        right_layout.addWidget(self._result_label)

        self._detail_label = QLabel("")
        self._detail_label.setFont(QFont("Arial", 14))
        self._detail_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._detail_label)

        # 开始按钮
        self._start_btn = QPushButton("START!")
        self._start_btn.setFont(QFont("Arial", 18, QFont.Bold))
        self._start_btn.setMinimumHeight(50)
        self._start_btn.setStyleSheet(
            "QPushButton { background-color: #4CAF50; color: white; "
            "border-radius: 8px; }"
            "QPushButton:hover { background-color: #45a049; }"
            "QPushButton:pressed { background-color: #3d8b40; }"
            "QPushButton:disabled { background-color: #888; }")
        right_layout.addWidget(self._start_btn)

        # 状态栏
        self._status_label = QLabel("Ready")
        self._status_label.setFont(QFont("Arial", 10))
        self._status_label.setAlignment(Qt.AlignCenter)
        right_layout.addWidget(self._status_label)

        # 组装
        main_layout.addWidget(left_frame, stretch=3)
        main_layout.addWidget(right_frame, stretch=1)

    def _connect_signals(self):
        # UI → 逻辑
        self._start_btn.clicked.connect(self._on_start_clicked)
        self._mode_competition.toggled.connect(self._on_mode_changed)

        # 引擎 → UI
        self._engine.state_changed.connect(self._on_state_changed)
        self._engine.countdown_tick.connect(self._on_countdown_tick)
        self._engine.result_ready.connect(self._on_result_ready)
        self._engine.timeout_detected.connect(self._on_timeout)

    def _set_strategy_enabled(self, enabled: bool):
        for rb in (self._strat_win, self._strat_lose,
                   self._strat_tie, self._strat_random):
            rb.setEnabled(enabled)
        self._strategy_label.setEnabled(enabled)

    def _get_response_strategy(self) -> ResponseStrategy:
        if self._strat_win.isChecked():
            return ResponseStrategy.ALWAYS_WIN
        elif self._strat_lose.isChecked():
            return ResponseStrategy.ALWAYS_LOSE
        elif self._strat_tie.isChecked():
            return ResponseStrategy.ALWAYS_TIE
        return ResponseStrategy.RANDOM

    # === UI 回调 ===

    def _on_start_clicked(self):
        if self._engine.state != GameState.IDLE:
            return
        self._result_label.setText("")
        self._detail_label.setText("")
        self._start_btn.setEnabled(False)
        self.start_game_signal.emit()

    def _on_mode_changed(self, checked: bool):
        if checked:
            self._engine.mode = GameMode.COMPETITION
            self._set_strategy_enabled(False)
        else:
            self._engine.mode = GameMode.RESPONSE
            self._set_strategy_enabled(True)

    # === 引擎回调 ===

    def _on_state_changed(self, state_value: str):
        state = GameState(state_value)
        status_texts = {
            GameState.IDLE: "Ready",
            GameState.COUNTDOWN: "Countdown...",
            GameState.WAITING_GESTURE: "Show your gesture!",
            GameState.JUDGING: "Judging...",
            GameState.RESULT: "",
        }
        self._status_label.setText(status_texts.get(state, ""))

        if state == GameState.IDLE:
            self._start_btn.setEnabled(True)
            self._gesture_timeout_timer.stop()
        elif state == GameState.WAITING_GESTURE:
            timeout = 3000 if self._engine.mode == GameMode.COMPETITION else 5000
            self._gesture_timeout_timer.start(timeout)
            self._detector.start(self._engine.on_gesture_detected)

    def _on_countdown_tick(self, step: str):
        audio_map = {
            "get_ready": "get_ready",
            "rock": "count_rock",
            "scissors": "count_scissors",
            "paper": "count_paper",
        }
        if step in audio_map:
            self._audio.play(audio_map[step])

        display_map = {
            "get_ready": "READY?",
            "rock": "ROCK!",
            "scissors": "SCISSORS!",
            "paper": "PAPER!",
        }
        self._status_label.setText(display_map.get(step, ""))

    def _on_result_ready(self, data: dict):
        self._gesture_timeout_timer.stop()

        result = data["result"]
        human = data["human"]
        robot = data["robot"]
        scores = data["scores"]

        # 更新比分
        self._score_label.setText(
            f"You: {scores['human']}  |  Robot: {scores['robot']}  |  Tie: {scores['tie']}")

        # 结果显示
        style = RESULT_STYLES.get(result, RESULT_STYLES["timeout"])
        self._result_label.setText(style["text"])
        self._result_label.setStyleSheet(
            f"color: {style['color']}; background-color: {style['bg']}; "
            f"border-radius: 12px; padding: 10px;")

        # 详情
        if result != "timeout":
            human_text = f"{GESTURE_EMOJI.get(human, '?')} {GESTURE_DISPLAY.get(human, human)}"
            robot_text = f"{GESTURE_EMOJI.get(robot, '?')} {GESTURE_DISPLAY.get(robot, robot)}"
            self._detail_label.setText(f"You: {human_text}  vs  Robot: {robot_text}")
        else:
            self._detail_label.setText("No gesture detected")

        # 播放结果语音（仅比赛模式）
        if self._engine.mode == GameMode.COMPETITION:
            audio_map = {
                "human_wins": "you_win",
                "robot_wins": "i_win",
                "tie": "tie",
                "timeout": "no_gesture",
            }
            if result in audio_map:
                self._audio.play(audio_map[result])

        # 发送机器人手势到灵巧手
        if robot in ("rock", "paper", "scissors"):
            from l10_right_hand_rock_paper_scissors.poses import GESTURE_POSES
            dof = GESTURE_POSES[robot]
            self.send_dof_signal.emit(dof, 0.4)

        # 延迟回到 IDLE
        timeout_ms = 3000 if self._engine.mode == GameMode.COMPETITION else 2000
        self._result_timer.start(timeout_ms)

    def _on_timeout(self):
        self._audio.play("no_gesture")
        style = RESULT_STYLES["timeout"]
        self._result_label.setText(style["text"])
        self._result_label.setStyleSheet(
            f"color: {style['color']}; background-color: {style['bg']}; "
            f"border-radius: 12px; padding: 10px;")
        self._detail_label.setText("No gesture detected")

    def _on_result_done(self):
        # 比赛模式播放"再来一局？"
        if self._engine.mode == GameMode.COMPETITION:
            self._audio.play("play_again")
        self._engine.set_state(GameState.IDLE)

    def _on_gesture_timeout(self):
        if self._engine.state == GameState.WAITING_GESTURE:
            self._engine.on_gesture_timeout()

    # === 摄像头画面更新 ===

    def start_camera_display(self, fps: int = 30):
        """启动摄像头画面定时刷新。"""
        interval = max(1, int(1000 / fps))
        self._frame_timer.start(interval)

    def stop_camera_display(self):
        """停止摄像头画面刷新。"""
        self._frame_timer.stop()

    def _update_camera_frame(self):
        frame = self._detector.get_frame()
        if frame is None:
            return

        # 如果在倒计时状态，叠加倒计时文字
        if self._engine.state == GameState.COUNTDOWN:
            status_text = self._status_label.text()
            if status_text:
                h, w = frame.shape[:2]
                cv2.putText(frame, status_text, (w // 2 - 120, h // 2),
                            cv2.FONT_HERSHEY_SIMPLEX, 2.0, (0, 255, 255), 4,
                            cv2.LINE_AA)

        # BGR → RGB → QImage
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qimg = QImage(rgb.data, w, h, ch * w, QImage.Format_RGB888)
        pixmap = QPixmap.fromImage(qimg).scaled(
            self._camera_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._camera_label.setPixmap(pixmap)
