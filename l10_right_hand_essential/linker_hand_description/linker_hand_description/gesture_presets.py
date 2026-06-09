"""
L10 10-DOF 灵巧手共享手势预设。

本模块是所有包的手势 DOF 值的**单一数据源 (Single Source of Truth)**。
修改手势预设只需编辑本文件，所有消费方自动同步。

DOF 顺序 (index 0-9):

  ======  ===============  ===========
  索引     名称              含义
  ======  ===============  ===========
  0       thumb_bend       拇指弯曲
  1       thumb_lateral    拇指侧摆
  2       index_bend       食指弯曲
  3       middle_bend      中指弯曲
  4       ring_bend        无名指弯曲
  5       little_bend      小指弯曲
  6       index_lateral    食指侧摆
  7       ring_lateral     无名指侧摆
  8       little_lateral   小指侧摆
  9       thumb_rotation   拇指旋转
  ======  ===============  ===========

值域: 0-255

  - Bend:     0 = 完全弯曲,  255 = 完全伸直
  - Lateral:  0 = 并拢,      255 = 展开
  - Rotation: 0 = 对掌,      255 = 外旋

所有值以 ``tuple`` 存储（不可变），使用方需 ``list()`` 转换。
"""

from __future__ import annotations


# DOF 名称（规范顺序）
DOF_ORDER: tuple[str, ...] = (
    "thumb_bend",
    "thumb_lateral",
    "index_bend",
    "middle_bend",
    "ring_bend",
    "little_bend",
    "index_lateral",
    "ring_lateral",
    "little_lateral",
    "thumb_rotation",
)

# 通用手势预设
GESTURE_PRESETS: dict[str, tuple[int, ...]] = {
    "open":      (255, 255, 255, 255, 255, 255, 255, 255, 255, 255),
    "fist":      (122, 145,   0,   0,   0,   0,   0,   0,   0,  92),
    "ok":        (108,  56, 118, 255, 255, 255, 255, 255, 255, 234),
    "pinch":     (108,  56, 118,   0,   0,   0, 132,   0,   0, 234),
    "point":     (116, 142, 255,   0,   0,   0,  49,  36,  81,  50),
    "peace":     ( 30,  15, 255, 255,   0,   0, 255, 255, 255,   0),
    "thumbs_up": (255, 255,   0,   0,   0,   0,   0,   0,   0,   0),
}

# 游戏专用姿态
READY_POSE:    tuple[int, ...] = (255, 200, 255, 255, 255, 255, 180, 180, 180,  41)
ROCK_POSE:     tuple[int, ...] = (122, 145,   0,   0,   0,   0,   0,   0,   0,  92)
PAPER_POSE:    tuple[int, ...] = (255, 255, 255, 255, 255, 255, 255, 255, 255, 255)
SCISSORS_POSE: tuple[int, ...] = ( 30,  15, 255, 255,   0,   0, 255, 255, 255,   0)
SHAKE_POSE:    tuple[int, ...] = (122, 145,   0,   0,   0,   0,   0,   0,   0,  92)
