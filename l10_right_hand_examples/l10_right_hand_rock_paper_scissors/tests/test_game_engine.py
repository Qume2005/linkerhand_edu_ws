"""
Game Engine 单元测试 — 胜负判定、响应策略、BEATS 一致性。
"""

import pytest

from l10_right_hand_rock_paper_scissors.game_engine import (
    BEATS, GESTURES, GameResult, ResponseStrategy, judge, pick_robot_gesture,
)


# === judge() 测试 ===

class TestJudge:
    """胜负判定逻辑。"""

    def test_rock_beats_scissors(self):
        assert judge("rock", "scissors") == GameResult.HUMAN_WINS

    def test_scissors_beats_paper(self):
        assert judge("scissors", "paper") == GameResult.HUMAN_WINS

    def test_paper_beats_rock(self):
        assert judge("paper", "rock") == GameResult.HUMAN_WINS

    def test_rock_loses_to_paper(self):
        assert judge("rock", "paper") == GameResult.ROBOT_WINS

    def test_scissors_loses_to_rock(self):
        assert judge("scissors", "rock") == GameResult.ROBOT_WINS

    def test_paper_loses_to_scissors(self):
        assert judge("paper", "scissors") == GameResult.ROBOT_WINS

    def test_same_gesture_is_tie(self):
        for g in GESTURES:
            assert judge(g, g) == GameResult.TIE

    def test_none_is_timeout(self):
        assert judge("none", "rock") == GameResult.TIMEOUT


# === pick_robot_gesture() 测试 ===

class TestPickRobotGesture:
    """响应策略逻辑。"""

    def test_always_tie(self):
        for g in GESTURES:
            assert pick_robot_gesture(g, ResponseStrategy.ALWAYS_TIE) == g

    def test_always_win(self):
        """Robot ALWAYS_WIN → robot 确实赢了每一局。"""
        for g in GESTURES:
            robot_choice = pick_robot_gesture(g, ResponseStrategy.ALWAYS_WIN)
            assert judge(g, robot_choice) == GameResult.ROBOT_WINS, \
                f"ALWAYS_WIN: human={g}, robot={robot_choice}, expected ROBOT_WINS"

    def test_always_lose(self):
        """Robot ALWAYS_LOSE → robot 确实输了每一局。"""
        for g in GESTURES:
            robot_choice = pick_robot_gesture(g, ResponseStrategy.ALWAYS_LOSE)
            assert judge(g, robot_choice) == GameResult.HUMAN_WINS, \
                f"ALWAYS_LOSE: human={g}, robot={robot_choice}, expected HUMAN_WINS"

    def test_random_returns_valid_gesture(self):
        for _ in range(50):
            result = pick_robot_gesture("rock", ResponseStrategy.RANDOM)
            assert result in GESTURES


# === BEATS 一致性 ===

class TestBeatsConsistency:
    """验证 BEATS 表的自洽性。"""

    def test_beats_has_all_gestures_as_keys(self):
        assert set(BEATS.keys()) == set(GESTURES)

    def test_beats_has_all_gestures_as_values(self):
        assert set(BEATS.values()) == set(GESTURES)

    def test_no_gesture_beats_itself(self):
        for g in GESTURES:
            assert BEATS[g] != g
