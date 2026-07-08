# l10_right_hand_rock_paper_scissors

LinkerHand L10 灵巧手石头剪刀布互动游戏。通过摄像头识别人类手势，控制灵巧手出招，配合语音播报和 PySide2 GUI 提供完整游戏体验。

## 功能

### 比赛模式
1. 点击 **开始!** 开始
2. 语音倒计时「准备！石头！剪刀！布！」
3. 人和机器同时出招（机器随机选择）
4. 摄像头识别人的手势（石头/剪刀/布）
5. 判定输赢，语音播报结果（你赢了! / 我赢了! / 平局!）
6. 超时未识别到手势时语音提示「没看清！」
7. 语音询问「再来一局？」，可继续游戏

### 响应模式
1. 点击 **开始!** 开始
2. 人先出手势
3. 机器根据策略响应（常赢/常输/打平/随机）
4. 仅 UI 显示结果，无语音

## 依赖安装

```bash
pip install pygame edge-tts mediapipe opencv-python PySide2
```

### 已知问题：OpenCV Qt 插件冲突

OpenCV (`opencv-python`) 自带的 Qt 插件会与系统 Qt5 (PySide2) 冲突，导致节点启动时报 `qt.qpa.plugin: Could not load the Qt platform plugin "xcb"` 错误。

解决方法：禁用 OpenCV 自带的 Qt 插件目录（我们只用 OpenCV 做图像处理，不需要它的 GUI 功能）：

```bash
mv ~/.local/lib/python3.12/site-packages/cv2/qt ~/.local/lib/python3.12/site-packages/cv2/qt_disabled
```

或者安装 headless 版本的 OpenCV（不含 Qt）：

```bash
pip uninstall opencv-python && pip install opencv-python-headless
```

## 音频生成

首次运行前需要生成语音文件（使用 `uv` 管理依赖，无需手动安装 edge-tts）：

```bash
cd l10_right_hand_rock_paper_scissors/sounds
uv run --python /usr/bin/python3 generate_audio.py
```

生成的音频文件（中英混合 + AAA 格斗游戏热血风格）：

| 文件 | 内容 | 风格 |
|------|------|------|
| `count_rock.wav` | 石头！ | 中文女声，清脆有力 |
| `count_scissors.wav` | 剪刀！ | 中文女声，清脆有力 |
| `count_paper.wav` | 布！ | 中文女声，爆发力 |
| `get_ready.wav` | 准备！ | 中文女声，蓄力感 |
| `you_win.wav` | YOU WIN! | 英文男声，史诗格斗播报 |
| `i_win.wav` | I WIN! | 英文男声，反派感 |
| `tie.wav` | TIE! | 英文男声，有力干脆 |
| `no_gesture.wav` | 没看清！ | 中文女声，俏皮无奈 |
| `play_again.wav` | 再来一局？ | 中文女声，轻松俏皮 |

## 快速启动

### 仿真模式
```bash
# 构建
cd ~/projects/linkerhand_edu_ws
colcon build --packages-select l10_right_hand_rock_paper_scissors
source install/setup.bash

# 启动
ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_sim.launch.py
```

### 真机模式
```bash
ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_real.launch.py
```

## 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `camera_id` | `-1` | 摄像头编号，-1=自动扫描 |

> **摄像头自动扫描：** 默认自动扫描可用摄像头（0-9），无需手动指定 `camera_id`。
> 如有多个摄像头，可通过参数指定：`camera_id:=2`

```bash
ros2 launch l10_right_hand_rock_paper_scissors rock_paper_scissors_sim.launch.py camera_id:=1
```

## 项目结构

```
l10_right_hand_rock_paper_scissors/
├── setup.cfg                         # setuptools 脚本安装路径配置
├── launch/                           # ROS 2 launch 文件
│   ├── rock_paper_scissors_sim.launch.py
│   └── rock_paper_scissors_real.launch.py
├── sounds/                           # 音频文件
│   ├── generate_audio.py             # edge-tts 生成脚本（uv 单文件依赖）
│   └── *.wav                         # 生成的音频
├── l10_right_hand_rock_paper_scissors/
│   ├── rock_paper_scissors_node.py   # ROS 节点 + Qt 主入口
│   ├── gesture_detector.py           # MediaPipe 手势识别（兼容 Legacy/Task API）
│   ├── game_engine.py                # 游戏状态机 + 胜负判定
│   ├── game_widget.py                # PySide2 游戏 UI
│   ├── audio_player.py               # pygame.mixer 音频播放
│   └── poses.py                      # 手部 10-DOF 姿态定义
└── tests/                            # 测试（40 个）
    ├── test_game_engine.py           # 胜负判定 + 策略 + 一致性
    ├── test_gesture_detector.py      # 手势分类静态方法
    ├── test_runtime_smoke.py         # 模块导入 + 实例化冒烟测试
    └── test_node_init.py             # 完整节点初始化链路集成测试
```

## 测试

```bash
source install/setup.bash
python3 -m pytest l10_right_hand_rock_paper_scissors/tests/ -v
```

40 个测试覆盖：
- 游戏引擎逻辑（胜负判定、响应策略、BEATS 一致性）
- 手势分类（rock/paper/scissors/none）
- 所有模块导入与实例化
- 完整节点初始化链路（AudioPlayer + GestureDetector + GameEngine + GameWidget）
- 信号连接
- 姿态值合理性

## 游戏玩法

1. 启动后会打开游戏窗口，左侧显示摄像头画面
2. 选择游戏模式（比赛/响应）
3. 点击 **开始!** 开始游戏
4. 在摄像头前展示手势：
   - **石头**: 握拳
   - **剪刀**: 伸出食指和中指
   - **布**: 张开手掌
5. 比赛模式下享受语音播报的格斗游戏体验！
