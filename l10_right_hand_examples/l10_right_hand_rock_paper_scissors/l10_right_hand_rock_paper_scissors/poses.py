"""
灵巧手姿态定义 — 石头剪刀布手势，从共享配置重导出。

姿态值的单一数据源在 linker_hand_description.gesture_presets 模块。
本模块保持原有导出名称不变，确保所有消费方无需修改导入路径。
"""

from linker_hand_description.gesture_presets import (
    READY_POSE,
    ROCK_POSE,
    PAPER_POSE,
    SCISSORS_POSE,
    SHAKE_POSE,
)

# 按手势名索引
GESTURE_POSES = {
    "rock":     ROCK_POSE,
    "paper":    PAPER_POSE,
    "scissors": SCISSORS_POSE,
}
