"""
灵巧手姿态定义 — 石头剪刀布的三种手势 10-DOF 值。

DOF 顺序: [thumb_bend, thumb_lateral, index_bend, middle_bend,
           ring_bend, little_bend, index_lateral, ring_lateral,
           little_lateral, thumb_rotation]

值域: 0-255
- Bend DOFs: 0=fully bent, 255=fully straight
- Lateral DOFs: 0=touching, 255=spread apart
- thumb_lateral: 0=tucked, 255=spread
- thumb_rotation: 0=toward palm, 255=outward
"""

# 初始/待机姿态（放松微张）
READY_POSE = [255, 200, 255, 255, 255, 255, 180, 180, 180, 41]

# 摇摆预备姿态（倒计时用，握拳晃动）
SHAKE_POSE = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# 石头（握拳）
ROCK_POSE = [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]

# 布（张开手掌）
PAPER_POSE = [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]

# 剪刀（食指 + 中指伸直，其余弯曲）
SCISSORS_POSE = [30, 15, 255, 255, 0, 0, 255, 255, 255, 0]

# 按手势名索引
GESTURE_POSES = {
    "rock":     ROCK_POSE,
    "paper":    PAPER_POSE,
    "scissors": SCISSORS_POSE,
}
