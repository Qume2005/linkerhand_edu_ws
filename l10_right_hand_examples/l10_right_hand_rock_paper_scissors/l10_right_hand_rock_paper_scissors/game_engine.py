"""
游戏状态机 — 石头剪刀布的核心逻辑。

负责状态转换、胜负判定、比分统计。
通过 Qt Signal 通知 UI 状态变化。
"""

import random
from collections import deque
from enum import Enum

from PySide2.QtCore import QObject, Signal


class GameState(str, Enum):
    IDLE = "idle"
    COUNTDOWN = "countdown"
    WAITING_GESTURE = "waiting_gesture"
    JUDGING = "judging"
    RESULT = "result"


class GameMode(str, Enum):
    COMPETITION = "competition"
    RESPONSE = "response"


class ResponseStrategy(str, Enum):
    ALWAYS_WIN = "always_win"
    ALWAYS_LOSE = "always_lose"
    ALWAYS_TIE = "always_tie"
    RANDOM = "random"


class GameResult(str, Enum):
    HUMAN_WINS = "human_wins"
    ROBOT_WINS = "robot_wins"
    TIE = "tie"
    TIMEOUT = "timeout"


# 胜负规则: key beats value
BEATS = {
    "rock":     "scissors",
    "scissors": "paper",
    "paper":    "rock",
}

# 被 key beat 的手势 → 用于 always_lose 策略
LOSES_TO = {v: k for k, v in BEATS.items()}

GESTURES = ("rock", "paper", "scissors")

# 手势显示名
GESTURE_DISPLAY = {
    "rock":     "ROCK",
    "paper":    "PAPER",
    "scissors": "SCISSORS",
}

# 手势 emoji
GESTURE_EMOJI = {
    "rock":     "\u270a",   # ✊
    "paper":    "\u270b",   # ✋
    "scissors": "\u270c",   # ✌
}


def judge(human: str, robot: str) -> GameResult:
    """判定一局胜负。

    Args:
        human: 人类手势 ('rock'|'paper'|'scissors'|'none')
        robot: 机器手势 ('rock'|'paper'|'scissors')

    Returns:
        GameResult
    """
    if human == "none":
        return GameResult.TIMEOUT
    if human == robot:
        return GameResult.TIE
    return GameResult.HUMAN_WINS if BEATS[human] == robot else GameResult.ROBOT_WINS


def pick_robot_gesture(human_gesture: str, strategy: ResponseStrategy) -> str:
    """根据策略选择机器人的出招。

    Args:
        human_gesture: 人类出的手势
        strategy: 响应策略

    Returns:
        机器人应该出的手势
    """
    if strategy == ResponseStrategy.ALWAYS_TIE:
        return human_gesture
    elif strategy == ResponseStrategy.ALWAYS_WIN:
        # 机器人要赢 → 出能赢人类的手势 (LOSES_TO[h] 是赢 h 的那个手势)
        return LOSES_TO[human_gesture]
    elif strategy == ResponseStrategy.ALWAYS_LOSE:
        # 机器人要输 → 出被人类赢的手势 (BEATS[h] 是被 h 赢的那个手势)
        return BEATS[human_gesture]
    else:
        return random.choice(GESTURES)


class GameEngine(QObject):
    """石头剪刀布游戏状态机。"""

    # Qt Signals
    state_changed = Signal(str)           # GameState value
    countdown_tick = Signal(str)          # "get_ready" | "rock" | "scissors" | "paper"
    result_ready = Signal(dict)           # {"result", "human", "robot", "scores"}
    timeout_detected = Signal()           # 手势识别超时

    def __init__(self):
        super().__init__()
        self._state = GameState.IDLE
        self._mode = GameMode.COMPETITION
        self._response_strategy = ResponseStrategy.RANDOM

        # 比分
        self._scores = {"human": 0, "robot": 0, "tie": 0}

        # 当前局数据
        self._human_gesture = "none"
        self._robot_gesture = "none"

        # 防抖缓冲
        self._gesture_buffer: deque = deque(maxlen=10)
        self._buffer_lock = False

    @property
    def state(self) -> GameState:
        return self._state

    @property
    def mode(self) -> GameMode:
        return self._mode

    @mode.setter
    def mode(self, value: GameMode):
        self._mode = value

    @property
    def response_strategy(self) -> ResponseStrategy:
        return self._response_strategy

    @response_strategy.setter
    def response_strategy(self, value: ResponseStrategy):
        self._response_strategy = value

    @property
    def scores(self) -> dict:
        return dict(self._scores)

    def set_state(self, state: GameState) -> None:
        """转换游戏状态并通知 UI。"""
        self._state = state
        self.state_changed.emit(state.value)

    def reset_scores(self) -> None:
        """重置比分。"""
        self._scores = {"human": 0, "robot": 0, "tie": 0}

    def start_round(self) -> None:
        """开始新一轮游戏。"""
        self._human_gesture = "none"
        self._robot_gesture = "none"
        self._gesture_buffer.clear()
        self._buffer_lock = False

        if self._mode == GameMode.COMPETITION:
            self._start_competition_countdown()
        else:
            self.set_state(GameState.WAITING_GESTURE)

    def _start_competition_countdown(self) -> None:
        """启动比赛模式倒计时。"""
        self.set_state(GameState.COUNTDOWN)

    def on_countdown_step(self, step: str) -> None:
        """倒计时步骤回调。

        在 countdown 的最后一步（"paper"）时随机选择机器人的出招。
        """
        self.countdown_tick.emit(step)
        if step == "paper":
            self._robot_gesture = random.choice(GESTURES)
            self.set_state(GameState.WAITING_GESTURE)

    def on_gesture_detected(self, gesture: str) -> None:
        """手势识别回调 — 在 WAITING_GESTURE 状态下收集手势。"""
        if self._state != GameState.WAITING_GESTURE:
            return
        if self._buffer_lock:
            return

        self._gesture_buffer.append(gesture)

        # 防抖：需要缓冲区中超过 60% 是同一手势才确认
        if len(self._gesture_buffer) >= 5:
            counts = {}
            for g in self._gesture_buffer:
                counts[g] = counts.get(g, 0) + 1
            dominant = max(counts, key=counts.get)
            if counts[dominant] >= len(self._gesture_buffer) * 0.6:
                self._confirm_gesture(dominant)

    def on_gesture_timeout(self) -> None:
        """手势识别超时回调。"""
        if self._state != GameState.WAITING_GESTURE:
            return
        self.timeout_detected.emit()
        self.set_state(GameState.IDLE)

    def _confirm_gesture(self, gesture: str) -> None:
        """确认人类手势并进入判定阶段。"""
        self._buffer_lock = True
        self._human_gesture = gesture
        self.set_state(GameState.JUDGING)

        if self._mode == GameMode.RESPONSE:
            self._robot_gesture = pick_robot_gesture(
                gesture, self._response_strategy)

        result = judge(self._human_gesture, self._robot_gesture)

        # 更新比分
        if result == GameResult.HUMAN_WINS:
            self._scores["human"] += 1
        elif result == GameResult.ROBOT_WINS:
            self._scores["robot"] += 1
        elif result == GameResult.TIE:
            self._scores["tie"] += 1

        self.set_state(GameState.RESULT)
        self.result_ready.emit({
            "result": result.value,
            "human": self._human_gesture,
            "robot": self._robot_gesture,
            "scores": dict(self._scores),
        })

    @property
    def human_gesture(self) -> str:
        return self._human_gesture

    @property
    def robot_gesture(self) -> str:
        return self._robot_gesture
