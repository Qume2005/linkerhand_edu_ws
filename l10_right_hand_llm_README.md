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
xhost +
docker run -it --rm \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control

# 真机模式
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

`-v $(pwd)/llm_settings.json:/ws/llm_settings.json` 把宿主机工作目录下的配置文件映射进容器，这样容器直接复用已配置好的 API Key，不用重新设置。需要从工作空间目录下运行命令。

如果 GUI 无法启动（`could not connect to display`），加 `--net=host`：

```bash
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
docker run -it --rm \
  --gpus all \
  -e DISPLAY=$DISPLAY \
  -v /tmp/.X11-unix:/tmp/.X11-unix \
  -v $HOME/.Xauthority:/root/.Xauthority:ro \
  -v $(pwd)/llm_settings.json:/ws/llm_settings.json \
  l10-llm-control

# 无 NVIDIA / 软件渲染
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

支持 `sin`, `cos`, `tan`, `sqrt`, `abs`, `round`, `pi`, `e` 等。

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

| 手势 | DOF 值 |
|------|--------|
| 张开手 | `[255,255,255,255,255,255,255,255,255,255]` |
| 握拳 | `[0,0,0,0,0,0,0,0,0,0]` |
| 比耶 | `[30,15,255,255,0,0,255,255,255,0]` |
| 指向 | `[0,128,255,0,24,16,49,36,81,16]` |
| OK | `[80,110,116,255,255,255,255,255,255,54]` |
| 捏取 | `[92,112,121,0,0,0,132,0,0,48]` |

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
| Docker `could not connect to display` | 运行 `xhost +`，并加上 `-v $HOME/.Xauthority:/root/.Xauthority:ro`，必要时加 `--net=host` |
| Docker 找不到 CAN 设备 | 确认设备路径，加 `--device=/dev/can0` |