# L10 灵巧手 LLM 控制系统

通过自然语言对话控制 L10 灵巧手，支持仿真和真机两种模式。

## 快速开始

### 本机运行

```bash
# 构建
cd ~/projects/linkerhand_edu_ws
colcon build --packages-select l10_right_hand_llm

# 仿真模式
source install/setup.bash
ros2 launch l10_right_hand_llm llm_control.launch.py

# 真机模式
ros2 launch l10_right_hand_llm llm_control_real.launch.py
```

首次启动会弹出设置对话框，填入 API Key 后即可使用。

### Docker 运行

```bash
# 构建镜像
docker build -t l10-llm-control .

# 仿真模式 (挂载配置文件，复用宿主机 API Key)
xhost +local:
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control

# 真机模式
xhost +local:
docker run -it --rm \
  --network=host \
  --device=/dev/can0 \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control \
  ros2 launch l10_right_hand_llm llm_control_real.launch.py
```

容器内置 fcitx5 中文拼音输入法，启动时自动运行。首次使用需右键点击系统托盘输入法图标添加「拼音」输入法。

`-v $(pwd)/llm_settings.json:/ws/llm_settings.json` 把宿主机工作目录下的配置文件映射进容器，这样容器直接复用已配置好的 API Key，不用重新设置。需要从工作空间目录下运行命令。

如果 GUI 无法启动（`could not connect to display`），加 `--net=host`：

```bash
xhost +local:
docker run -it --rm \
  --net=host \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  l10-llm-control
```

### Docker MuJoCo 渲染问题

Docker 下 MuJoCo OpenGL 渲染可能出现花屏或崩溃，按显卡情况选择：

```bash
# NVIDIA 显卡 — GPU 直通（需要 nvidia-container-toolkit）
xhost +local:
docker run -it --rm \
  --gpus all \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control

# 无 NVIDIA / 软件渲染
xhost +local:
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -e LIBGL_ALWAYS_SOFTWARE=1 \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control
```

## API 设置

点击右上角 **设置** 按钮，配置：

| 字段 | 说明 |
|------|------|
| Provider | OpenAI 或 Anthropic |
| API Key | 你的 API 密钥 |
| Base URL | API 地址（可填代理/中转地址） |
| Model | 模型名称 |

配置保存在工作目录的 `llm_settings.json`。

默认配置：
- OpenAI: `base_url=https://api.openai.com/v1`, `model=gpt-4o`
- Anthropic: `base_url=https://api.anthropic.com`, `model=claude-sonnet-4-20250514`

## 工具说明

模型有 3 个工具可用：

### 1. set_hand_dof — 单个手势

设置手的 10 个关节值（0-255），用于单个静态手势。

```
用户: "握拳"
用户: "比个耶"
用户: "竖大拇指"
```

可选参数 `duration` 控制过渡时长（秒），默认 0.618 秒。

### 2. queue_hand_actions — 动作队列

编排一组连续动作，用于多步动画。

```
用户: "从1数到5"
用户: "挥手"
用户: "石头剪刀布"
用户: "无名指画圆"
```

每个步骤包含：
- 10 个 DOF 值
- `duration` — 过渡时长（默认 0.618s）
- `pause` — 保持时长（默认 0s）

支持 `loop=true` 循环播放，直到新命令打断。

### 3. vector_calc — 向量计算器

用数学表达式生成 DOF 值序列，避免手算。

```
表达式: round(227 + 28 * cos(2 * pi * x / 8))
输入:   [0, 1, 2, 3, 4, 5, 6, 7]
输出:   [255, 247, 227, 207, 199, 207, 227, 247]
```

支持 `sin`, `cos`, `tan`, `sqrt`, `abs`, `round`, `pi`, `e` 等。执行环境为受限沙箱，禁止访问 `__builtins__`，防止注入风险。

## DOF 对照表

10 个自由度，值范围 0-255：

| DOF | 名称 | 0 | 255 |
|-----|------|---|-----|
| 0 | thumb_bend | 拇指弯曲 | 拇指伸直 |
| 1 | thumb_lateral | 拇指贴掌心 | 拇指外展 |
| 2 | index_bend | 食指弯曲 | 食指伸直 |
| 3 | middle_bend | 中指弯曲 | 中指伸直 |
| 4 | ring_bend | 无名指弯曲 | 无名指伸直 |
| 5 | little_bend | 小指弯曲 | 小指伸直 |
| 6 | index_lateral | 食指并拢 | 食指张开 |
| 7 | ring_lateral | 无名指并拢 | 无名指张开 |
| 8 | little_lateral | 小指并拢 | 小指张开 |
| 9 | thumb_rotation | 拇指向掌心旋 | 拇指向外旋 |

## 预设手势

> 值来源于共享配置 `linker_hand_description.gesture_presets`，下表仅作参考。

| 手势 | DOF 值 |
|------|--------|
| 张开手 | `[255,255,255,255,255,255,255,255,255,255]` |
| 握拳 | `[122,145,0,0,0,0,0,0,0,92]` |
| 比耶 | `[96,48,255,255,0,0,255,255,255,89]` |
| 指向 | `[116,142,255,0,0,0,49,36,81,50]` |
| OK | `[108,56,118,255,255,255,255,255,255,234]` |
| 捏取 | `[108,56,118,0,0,0,132,0,0,234]` |
| 竖大拇指 | `[255,255,0,0,0,0,0,0,0,255]` |

## 插值与过渡

所有动作都有平滑过渡（smoothstep 缓入缓出），不会瞬间跳变：
- 默认过渡 0.618 秒
- AI 可通过 `duration` 参数调整速度
- 新命令会自动打断正在执行的动画

## 键盘快捷键

| 快捷键 | 功能 |
|--------|------|
| Enter | 发送消息 |
| Ctrl+C | 退出程序 |

## 故障排除

| 问题 | 解决方案 |
|------|----------|
| "请先配置 API Key" | 点击设置按钮，填入 API Key |
| 连接超时 | 检查 Base URL 是否可达，或配置代理 |
| Docker `could not connect to display` | 运行 `xhost +local:`，并加上 `-v $HOME/.Xauthority:/root/.Xauthority:ro`，必要时加 `--net=host` |
| Docker 找不到 CAN 设备 | 确认设备路径，加 `--device=/dev/can0` |

---

## 技术深潜

以下各节深入解析系统的技术实现细节，适合开发者阅读。

### 流式 API 处理

LLM 响应采用流式 (streaming) 传输，实现 ChatGPT 风格的逐字显示效果。

**OpenAI 流式处理**：通过 `openai` SDK 的 `stream=True` 参数开启。每个 chunk 包含一个 `delta` 对象，可能携带文本片段 (`delta.content`) 或工具调用增量 (`delta.tool_calls`)。工具调用需要累积拼接：

```python
# 每个 chunk 的 tool_calls delta 包含:
# - id: 仅在首个 chunk 出现
# - function.name: 仅在首个 chunk 出现
# - function.arguments: 每个 chunk 追加一段字符串
# 最终拼接完成后 json.loads() 解析为完整参数
```

**Anthropic 流式处理**：使用 `anthropic` SDK 的 context manager 模式 (`with client.messages.stream(...) as stream`)。通过 `stream.text_stream` 迭代器获取文本片段，完成后调用 `stream.get_final_message()` 获取包含完整 tool_use block 的最终消息。

两种 API 的流式输出通过 `on_text_chunk` 和 `on_done` 两个回调统一抽象，上层代码无需关心底层差异。

### Qt + ROS 事件循环集成

本程序同时运行两个事件循环：

1. **Qt 事件循环** (`app.exec_()`) — GUI 主线程阻塞在这里
2. **ROS 2 spin 循环** — 在 daemon 线程中以 `rclpy.spin_once(timeout=0.01)` 轮询

ROS 线程以 10ms 超时轮询，确保回调及时执行而不阻塞 GUI。两者通过 `shutdown_event` (threading.Event) 协调退出。

### socketpair 信号处理模式

在 `app.exec_()` 阻塞期间，Python 的信号处理器无法被触发（因为 SIGINT 会被 Qt 的事件循环截获）。解决方案使用 Unix socketpair：

```
SIGINT 到来
    ↓
signal.set_wakeup_fd() 将信号编号写入 socketpair 的写端
    ↓
QSocketNotifier 监听 socketpair 的读端
    ↓
在 Qt 主线程中调用 _on_signal() 回调
    ↓
设置 shutdown_event + 关闭窗口 → 触发优雅退出
```

关键步骤：
- `socket.socketpair()` 创建一对互联的 Unix socket
- 写入端设为非阻塞（`setblocking(False)`），避免 signal handler 死锁
- `signal.set_wakeup_fd()` 注册写入端：POSIX 信号到来时 Python 自动写入信号编号
- `QSocketNotifier` 监听读取端，收到通知后在 Qt 主线程调用回调
- Python 信号处理器设为空 lambda（仅做唤醒，实际逻辑在 Qt 回调中完成）

### smoothstep 插值算法

手部运动使用 Hermite smoothstep 曲线实现缓入缓出过渡：

```
progress = t * t * (3.0 - 2.0 * t)
```

其中 `t` 从 0 线性变化到 1。该曲线特性：
- `t=0` 时 progress=0（起始位置）
- `t=1` 时 progress=1（目标位置）
- `t=0.5` 时 progress=0.5（中点）
- 在端点处一阶导数为零（速度从 0 开始、到 0 结束）

插值频率 50Hz（INTERP_HZ），默认过渡时长 0.618 秒（约 31 步）。队列模式下使用单调时钟 (`time.monotonic`) 驱动定时，避免 `sleep()` 累积误差导致动画节奏漂移。

### tool_definition schema 设计

系统为 LLM 定义了三个工具，同时维护 OpenAI 和 Anthropic 两种 JSON Schema 格式：

| 工具 | 用途 | 关键参数 |
|------|------|----------|
| `set_hand_dof` | 单次手势 | 10 个 DOF (0-255) + duration |
| `queue_hand_actions` | 多步动画 | actions 数组 (DOF+duration+pause) + loop |
| `vector_calc` | 数学计算 | expression (含变量 x) + vector |

系统提示模板 (`SYSTEM_PROMPT_TEMPLATE`) 动态注入当前手部 DOF 状态，帮助 LLM 理解手部位置。用户消息前通过 `build_user_context()` 插入三列对比表（LLM 上次发布 | 当前目标 | 实际硬件值），让 LLM 感知外部干预和硬件状态。

### conversation manager 模式

`ConversationManager` 管理 multi-turn 对话的消息历史，屏蔽 provider 差异：

- 消息格式化委托给 `LLMClientBase.format_assistant_msg()` 和 `format_tool_result()`
- OpenAI 格式：`{"role": "tool", "tool_call_id": "...", "content": "..."}`
- Anthropic 格式：`{"role": "user", "content": [{"type": "tool_result", "tool_use_id": "..."}]}`
- 运行时切换 provider 不需要重置对话历史

### 文件清单

| 模块 | 路径 | 职责 |
|------|------|------|
| `llm_control_node.py` | ROS 节点 + Qt 入口 | 发布 DOF 命令、smoothstep 插值、动作队列、双事件循环 |
| `llm_client.py` | API 抽象层 | 基类 + OpenAI/Anthropic 子类 + 工厂函数，统一消息格式 |
| `conversation.py` | 对话管理 | multi-turn 消息历史，provider-agnostic 格式化 |
| `chat_widget.py` | GUI 聊天窗口 | PySide2 UI、流式渲染、工具调用处理、信号桥接 |
| `settings_dialog.py` | 设置对话框 | API 配置编辑与持久化 (JSON) |
| `tool_definition.py` | 工具定义 | 三个工具的 JSON Schema、系统提示模板、向量计算沙箱 |
