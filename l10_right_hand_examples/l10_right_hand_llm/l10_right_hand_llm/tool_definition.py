"""LLM 工具定义与系统提示模板 —— 连接自然语言与灵巧手 DOF 控制的桥梁。

本模块定义了 LLM 可调用的三个工具（OpenAI 和 Anthropic 双格式），构建
包含手部状态反馈的系统提示，以及为用户消息附加上下文信息。

三工具定义
----------
1. **set_hand_dof** — 单次静态手势设置，10 个 DOF 值 + 可选 duration
2. **queue_hand_actions** — 多步动作队列编排，支持循环播放，每步含
   DOF + duration + pause
3. **vector_calc** — 数学向量计算器，LLM 用它生成精确的 DOF 序列
   （正弦波、线性渐变、缓动曲线等），避免手算出错

系统提示模板
------------
``SYSTEM_PROMPT_TEMPLATE`` 定义了 LLM 的角色（灵巧手控制助手）、可用工具
概要、当前手部 DOF 状态。每次发送请求前会根据最新的 DOF 值动态刷新。

用户上下文构建
--------------
``build_user_context()`` 在每条用户消息前插入三列对比表：
    LLM 上次发布值 | 当前目标值 | 实际硬件值
帮助 LLM 理解手部当前状态、检测外部干预（如控制面板修改）、发现硬件阻塞。

向量计算安全沙箱
----------------
``eval_vector()`` 使用受限命名空间执行用户提供的数学表达式（sin、cos、
sqrt 等），禁止访问 ``__builtins__``，防止注入风险。
"""

# 10 个自由度名称 (对应 DOF0-DOF9, 0-255 范围)
from linker_hand_description.gesture_presets import DOF_ORDER, GESTURE_PRESETS

# 预设动作 — 向后兼容别名，实际值来自 linker_hand_description 共享配置
PRESETS = GESTURE_PRESETS

# ---------- set_hand_dof 描述 ----------
_GESTURE_NAME_MAP = {
    "open": "张开手掌（全部伸直）",
    "fist": "握拳（全部弯曲）",
    "peace": "剪刀手/V字（食指+中指伸出，其余弯曲，拇指内收）",
    "ok": "OK 手势",
    "pinch": "捏合",
    "point": "指向（食指伸出）",
    "thumbs_up": "点赞（拇指伸出，其余弯曲）",
}

_SET_DOF_PREAMBLE = (
    "设置 10 自由度灵巧手的关节位置。每个值为 0-255 的整数。"
    "按顺序排列的 10 个值为：thumb_bend（拇指弯曲）, thumb_lateral（拇指侧摆）, "
    "index_bend（食指弯曲）, middle_bend（中指弯曲）, ring_bend（无名指弯曲）, "
    "little_bend（小指弯曲）, index_lateral（食指侧摆）, "
    "ring_lateral（无名指侧摆）, little_lateral（小指侧摆）, thumb_rotation（拇指旋转）。\n\n"
    "各 DOF 的数值含义：\n"
    "- 弯曲类 DOF（thumb_bend, index/middle/ring/little_bend）: "
    "0=完全弯曲（收拢入掌心）, 255=完全伸直（伸出）。\n"
    "- 侧摆类 DOF（index/ring/little_lateral）: "
    "0=手指并拢, 255=手指张开。\n"
    "- thumb_lateral（拇指侧摆）: "
    "0=拇指紧贴掌心/手指, 255=拇指大幅张开远离掌心。\n"
    "- thumb_rotation（拇指旋转）: "
    "0=拇指向掌心方向旋转（与手指对握，如捏合时）, 255=拇指向外旋转远离掌心。\n\n"
    "常见手势的拇指规则：\n"
    "- 拇指需要隐藏/内收时（如剪刀手/V字、握拳）: "
    "thumb_lateral 用低值（0-30）, thumb_rotation 用低值（0-20）, thumb_bend 也用低值。\n"
    "- 拇指需要外露/伸直时（如点赞、张开手掌）: "
    "thumb_lateral 用高值（200-255）, thumb_rotation 用低-中值（0-80）, thumb_bend 用高值。\n"
    "- thumb_rotation 和 thumb_bend 不是同一个东西：rotation 控制拇指相对手掌的扭转角度，不是弯曲。\n\n"
    "常见手势参考：\n"
)

_SET_DOF_POSTAMBLE = (
    "\n你可以组合预设和自定义修改。例如要做摇滚/牛角手势，伸出食指和小指，"
    "其余手指弯曲。发挥创意，调整各 DOF 值来实现目标手势。"
)

def _build_gesture_examples() -> str:
    """从 GESTURE_PRESETS 自动生成手势示例列表。"""
    lines = []
    for name in ("open", "fist", "peace", "ok", "pinch", "point", "thumbs_up"):
        if name in GESTURE_PRESETS:
            label = _GESTURE_NAME_MAP.get(name, name)
            values = ", ".join(str(v) for v in GESTURE_PRESETS[name])
            lines.append(f"- {label}: [{values}]")
    return "\n".join(lines)

SET_DOF_DESCRIPTION = _SET_DOF_PREAMBLE + _build_gesture_examples() + _SET_DOF_POSTAMBLE

# ---------- queue_hand_actions 描述 ----------
QUEUE_DESCRIPTION = (
    "编排一串手部姿态序列用于多步动画。每个步骤定义一个目标姿态（10 个 DOF 值）、"
    "过渡时间和下一步开始前的停留时间。\n\n"
    "当用户请求以下动作时使用此工具：\n"
    "- 多步动作：挥手、数手指（1-5）、招手\n"
    "- 节奏性/重复手势：石头剪刀布、弹指\n"
    "- 表现性动画：手势舞、手语序列\n"
    "- 任何需要超过一个姿态转换的动作\n\n"
    "单个姿态变更请使用 set_hand_dof。\n\n"
    "每个动作步骤包含：\n"
    "- 10 个 DOF 值（从 thumb_bend 到 thumb_rotation，含义同 set_hand_dof）\n"
    "- duration（秒）: 从上一个姿态过渡到此步骤目标的过渡时间，控制运动速度。省略时默认 0.618 秒。\n"
    "- pause（秒）: 在此姿态停留多久后进入下一步。默认 0（立即进入下一步）。\n\n"
    "自然序列设计技巧：\n"
    "- 短时间（0.2-0.4 秒）用于快速干脆的手势（弹响、轻敲）。\n"
    "- 较长时间（0.8-2.0 秒）用于流畅的过渡（伸展、张开）。\n"
    "- 在关键姿态之间添加停顿（0.2-1.0 秒），让每个手势清晰可见。\n"
    "- 节奏性动作（挥手、招手），在 2-3 个姿态间交替，使用相等的 duration+pause 产生自然节奏。\n"
    "- loop=true 的 IMPORTANT 规则：序列中的最后一步必须始终有明确的 pause 值"
    "（不要留 0 或省略）。与其他步骤的节奏匹配。没有它，循环边界会感觉断裂。\n"
    "- 第一步从手部的当前位置开始过渡。\n"
    "- 大多数序列使用 3-8 步。更多步数允许更丰富的动画但生成时间更长。\n\n"
    "示例序列：\n"
    "1. 数手指 1 到 5：\n"
    "   第 1 步: 食指竖起（index_bend=255，其余弯曲=0）, duration=0.5, pause=0.6\n"
    "   第 2 步: +中指竖起, duration=0.3, pause=0.6\n"
    "   第 3 步: +无名指竖起, duration=0.3, pause=0.6\n"
    "   第 4 步: +小指竖起, duration=0.3, pause=0.6\n"
    "   第 5 步: 张开手掌（全部 255）, duration=0.5, pause=0\n\n"
    "2. 简单挥手（2 个交替姿态，loop=true）：\n"
    "   第 1 步: 张开手（全部弯曲=255，侧摆=255）, duration=0.3, pause=0.15\n"
    "   第 2 步: 手稍微合拢（弯曲=255，侧摆=80）, duration=0.3, pause=0.15\n\n"
    "3. 石头剪刀布：\n"
    "   第 1 步: 握拳（全部 0）, duration=0.3, pause=0.8（蓄力）\n"
    "   第 2 步: 握拳弹跳, duration=0.2, pause=0.3\n"
    "   第 3 步: 再次握拳弹跳, duration=0.2, pause=0.3\n"
    "   第 4 步: 出招（布=张开, 剪刀=剪刀手, 石头=握拳）, duration=0.4, pause=0\n\n"
    "4. 单指画圈（任意手指画圈，其余握拳，loop=true）。\n"
    "   使用 vector_calc 生成精确值。对于运动手指的弯曲和侧摆：\n"
    "     expression='round(center + amplitude * cos(2*pi*x/N))', vector=[0,1,...,N-1]\n"
    "     expression='round(center + amplitude * sin(2*pi*x/N))', vector=[0,1,...,N-1]\n"
    "   其中 center=(min+max)/2, amplitude=(max-min)/2。N=8-16 步以获得平滑效果。\n"
    "   示例: 无名指画圈，弯曲 center=227 amp=28, 侧摆 center=128 amp=127, N=8:\n"
    "     bend values = vector_calc('round(227+28*cos(2*pi*x/8))', [0,1,2,3,4,5,6,7])\n"
    "     lateral values = vector_calc('round(128+127*sin(2*pi*x/8))', [0,1,2,3,4,5,6,7])\n"
    "     所有其他 DOF = 0（完全握拳包括拇指）。每步: duration=0.15, pause=0。"
    "最后一步也必须 pause=0.1 使循环平滑过渡。\n"
    "     此技巧适用于任意手指：使用其 (弯曲, 侧摆) 对作为两个轴。\n"
)

# 队列步骤中 duration / pause 的参数描述
_STEP_DURATION_DESC = (
    "从上一个姿态过渡到此步骤目标的过渡时间（秒）。控制运动速度。"
    "省略时默认 0.618 秒。快速动作用 0.2-0.5 秒，慢速流畅动作用 0.8-2.0 秒。"
)
_STEP_PAUSE_DESC = (
    "在此姿态停留的时间（秒），然后进入下一步。"
    "默认 0（不停留）。使用 0.1-1.0 秒让姿态清晰可见后再转换。"
)

# ---------- vector_calc 描述 ----------
VECTOR_CALC_DESCRIPTION = (
    "对一组输入值列表逐个计算数学表达式。给定使用变量 'x' 的表达式字符串和数字列表，"
    "返回计算结果列表（每个输入值对应一个结果）。\n\n"
    "可用的函数和常量：\n"
    "- 三角函数: sin(x), cos(x), tan(x) — 角度为弧度\n"
    "- 常量: pi (=3.14159...), e (=2.71828...)\n"
    "- 算术: + - * / ** (幂) % (取模)\n"
    "- 其他: sqrt(x), abs(x), round(x), int(x), min(a,b), max(a,b), pow(a,b)\n\n"
    "使用此工具可以数学方式生成精确的 DOF 值序列，"
    "而无需手动计算。\n\n"
    "示例：\n"
    "- 为画圈生成 8 个无名指弯曲值（center=227, amplitude=28）：\n"
    "  expression='round(227 + 28 * cos(2 * pi * x / 8))', vector=[0,1,2,3,4,5,6,7]\n"
    "  → [255, 247, 227, 207, 199, 207, 227, 247]\n\n"
    "- 为画圈生成 8 个无名指侧摆值（center=128, amplitude=127）：\n"
    "  expression='round(128 + 127 * sin(2 * pi * x / 8))', vector=[0,1,2,3,4,5,6,7]\n"
    "  → [128, 218, 255, 218, 128, 38, 1, 38]\n\n"
    "- 10 步线性递增从 0 到 255：\n"
    "  expression='round(255 * x / 9)', vector=[0,1,2,3,4,5,6,7,8,9]\n"
    "  → [0, 28, 57, 85, 113, 142, 170, 198, 227, 255]\n\n"
    "- 6 步缓入缓出曲线，平滑张开→合拢：\n"
    "  expression='round(255 * (1 - (x/5)**2))', vector=[0,1,2,3,4,5]\n"
    "  → [255, 245, 214, 163, 92, 0]\n\n"
    "结果以 JSON 数字数组形式返回。"
    "使用 round() 或 int() 获取整数 DOF 值。"
)

# 向量计算的安全命名空间
import math as _math

SAFE_MATH_NAMESPACE = {
    "pi": _math.pi,
    "e": _math.e,
    "sin": _math.sin,
    "cos": _math.cos,
    "tan": _math.tan,
    "sqrt": _math.sqrt,
    "abs": abs,
    "round": round,
    "min": min,
    "max": max,
    "pow": pow,
    "int": int,
    "float": float,
}


def eval_vector(expression: str, vector: list) -> list:
    """对向量中的每个值求值表达式，返回结果列表。"""
    results = []
    for x_val in vector:
        ns = dict(SAFE_MATH_NAMESPACE)
        ns["x"] = x_val
        result = eval(expression, {"__builtins__": {}}, ns)
        results.append(result)
    return results

# ---------- System prompt ----------
SYSTEM_PROMPT_TEMPLATE = (
    "You are a dexterous robotic hand control assistant. "
    "Users describe hand gestures in natural language, and you translate them "
    "into precise DOF commands using the available tools. "
    "You MUST respond in Chinese (中文). "
    "Briefly explain what gesture you are about to perform before calling the tool. "
    "Ask for clarification if the request is ambiguous. "
    "You have three tools:\n"
    "- set_hand_dof: for a single pose change (one static gesture).\n"
    "- queue_hand_actions: for multi-step sequences (waving, counting, rhythmic motions).\n"
    "- vector_calc: evaluate a math expression over a vector of values. "
    "Use it to generate precise DOF sequences (circles, ramps, curves) "
    "instead of computing values manually.\n"
    "Choose the appropriate tool based on the user's request. "
    "You can combine, modify, and create gestures beyond the presets.\n\n"
    "Current hand DOF state (0=fully bent, 255=fully straight):\n"
    "{dof_state}"
)

# ---------- Per-parameter definitions ----------
_DOF_PROPERTIES = {
    "thumb_bend":     "拇指弯曲: 0=完全弯曲（收拢入掌心）, 255=完全伸直（伸出）",
    "thumb_lateral":  "拇指侧摆: 0=拇指紧贴掌心/手指, 255=拇指大幅张开远离掌心",
    "index_bend":     "食指弯曲: 0=完全弯曲, 255=完全伸直",
    "middle_bend":    "中指弯曲: 0=完全弯曲, 255=完全伸直",
    "ring_bend":      "无名指弯曲: 0=完全弯曲, 255=完全伸直",
    "little_bend":    "小指弯曲: 0=完全弯曲, 255=完全伸直",
    "index_lateral":  "食指侧摆: 0=手指并拢, 255=手指张开",
    "ring_lateral":   "无名指侧摆: 0=手指并拢, 255=手指张开",
    "little_lateral": "小指侧摆: 0=手指并拢, 255=手指张开",
    "thumb_rotation": "拇指旋转: 0=拇指向掌心方向旋转（与手指对握）, 255=拇指向外旋转远离掌心",
}

# ---------- OpenAI tools ----------
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_hand_dof",
            "description": SET_DOF_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    **{
                        name: {
                            "type": "integer",
                            "minimum": 0,
                            "maximum": 255,
                            "description": desc,
                        }
                        for name, desc in _DOF_PROPERTIES.items()
                    },
                    "duration": {
                        "type": "number",
                        "description": (
                            "Duration of the transition in seconds. "
                            "Controls how fast the hand moves from current pose to target pose. "
                            "Default is 0.618s. Use larger values (1-3s) for smooth, slow movements "
                            "and smaller values (0.1-0.5s) for quick, snappy movements."
                        ),
                    },
                },
                "required": list(DOF_ORDER),
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "queue_hand_actions",
            "description": QUEUE_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "description": {
                        "type": "string",
                        "description": "Brief name or summary of this action sequence (for display and logging)",
                    },
                    "loop": {
                        "type": "boolean",
                        "description": "If true, repeat the entire sequence indefinitely until a new command is given",
                    },
                    "actions": {
                        "type": "array",
                        "description": "Ordered list of hand pose steps to execute sequentially",
                        "items": {
                            "type": "object",
                            "properties": {
                                **{
                                    name: {
                                        "type": "integer",
                                        "minimum": 0,
                                        "maximum": 255,
                                        "description": desc,
                                    }
                                    for name, desc in _DOF_PROPERTIES.items()
                                },
                                "duration": {
                                    "type": "number",
                                    "description": _STEP_DURATION_DESC,
                                },
                                "pause": {
                                    "type": "number",
                                    "description": _STEP_PAUSE_DESC,
                                },
                            },
                            "required": list(DOF_ORDER),
                        },
                    },
                },
                "required": ["actions"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "vector_calc",
            "description": VECTOR_CALC_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    "expression": {
                        "type": "string",
                        "description": (
                            "Math expression using 'x' as the variable. "
                            "E.g. 'round(227 + 28 * cos(2 * pi * x / 8))'"
                        ),
                    },
                    "vector": {
                        "type": "array",
                        "items": {"type": "number"},
                        "description": (
                            "List of input values for x. "
                            "E.g. [0,1,2,3,4,5,6,7]"
                        ),
                    },
                },
                "required": ["expression", "vector"],
            },
        },
    },
]

# ---------- Anthropic tools ----------
ANTHROPIC_TOOLS = [
    {
        "name": "set_hand_dof",
        "description": SET_DOF_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                **{
                    name: {
                        "type": "integer",
                        "description": desc,
                    }
                    for name, desc in _DOF_PROPERTIES.items()
                },
                "duration": {
                    "type": "number",
                    "description": (
                        "Duration of the transition in seconds. "
                        "Controls how fast the hand moves from current pose to target pose. "
                        "Default is 0.618s. Use larger values (1-3s) for smooth, slow movements "
                        "and smaller values (0.1-0.5s) for quick, snappy movements."
                    ),
                },
            },
            "required": list(DOF_ORDER),
        },
    },
    {
        "name": "queue_hand_actions",
        "description": QUEUE_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Brief name or summary of this action sequence (for display and logging)",
                },
                "loop": {
                    "type": "boolean",
                    "description": "If true, repeat the entire sequence indefinitely until a new command is given",
                },
                "actions": {
                    "type": "array",
                    "description": "Ordered list of hand pose steps to execute sequentially",
                    "items": {
                        "type": "object",
                        "properties": {
                            **{
                                name: {
                                    "type": "integer",
                                    "description": desc,
                                }
                                for name, desc in _DOF_PROPERTIES.items()
                            },
                            "duration": {
                                "type": "number",
                                "description": _STEP_DURATION_DESC,
                            },
                            "pause": {
                                "type": "number",
                                "description": _STEP_PAUSE_DESC,
                            },
                        },
                        "required": list(DOF_ORDER),
                    },
                },
            },
            "required": ["actions"],
        },
    },
    {
        "name": "vector_calc",
        "description": VECTOR_CALC_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                "expression": {
                    "type": "string",
                    "description": (
                        "Math expression using 'x' as the variable. "
                        "E.g. 'round(227 + 28 * cos(2 * pi * x / 8))'"
                    ),
                },
                "vector": {
                    "type": "array",
                    "items": {"type": "number"},
                    "description": (
                        "List of input values for x. "
                        "E.g. [0,1,2,3,4,5,6,7]"
                    ),
                },
            },
            "required": ["expression", "vector"],
        },
    },
]


def get_tools(provider: str) -> list:
    """根据提供者返回对应格式的 tool 列表"""
    if provider == "Anthropic":
        return ANTHROPIC_TOOLS
    return OPENAI_TOOLS


def build_system_prompt(current_dof: list) -> str:
    """根据当前 DOF 状态构建 system prompt"""
    lines = []
    for i, name in enumerate(DOF_ORDER):
        v = current_dof[i] if i < len(current_dof) else 127
        lines.append(f"  {name}: {v}")
    dof_state = "\n".join(lines)
    return SYSTEM_PROMPT_TEMPLATE.format(dof_state=dof_state)


def _describe_diff(name: str, a: int, b: int) -> str:
    """Describe DOF value change direction."""
    d = b - a
    if d == 0:
        return ""
    if name == "thumb_lateral":
        direction = "更向外" if d > 0 else "更向内"
    elif name == "index_lateral":
        direction = "更张开" if d > 0 else "更并拢"
    elif name in ("ring_lateral", "little_lateral"):
        direction = "更张开" if d > 0 else "更并拢"
    elif "bend" in name:
        direction = "更直" if d > 0 else "更弯"
    elif "rotation" in name:
        direction = "外旋" if d > 0 else "内旋"
    else:
        direction = "+" if d > 0 else "-"
    return f"({abs(d)} {direction})"


def build_user_context(
    last_published_dof: list,
    target_dof: list,
    current_dof: list,
) -> str:
    """Build context prepended to user messages.

    Three-column comparison: last LLM publish | current target | current actual.
    - Last publish != target -> target was changed externally (control panel / other node)
    - Target != actual -> hand is blocked or still converging
    - No last publish -> LLM has never issued a command
    """
    has_published = last_published_dof is not None
    lines = ["[System Feedback]"]

    # 根据是否有 LLM 发布历史，决定表头是三列还是两列
    if has_published:
        lines.append(f"{'DOF':<16} {'LLM发布':>7} {'目标值':>7} {'实际值':>7}  状态")
    else:
        lines.append(f"{'DOF':<16} {'目标值':>7} {'实际值':>7}  状态")
    lines.append("-" * 60)

    any_target_drift = False   # 标记：目标值是否被外部修改
    any_not_reached = False    # 标记：硬件是否未到达目标值

    for i, name in enumerate(DOF_ORDER):
        tgt = target_dof[i] if i < len(target_dof) else 0
        cur = current_dof[i] if i < len(current_dof) else 0

        tags = []

        if has_published:
            # 三列对比模式：LLM Pub | Target | Actual
            lp = last_published_dof[i] if i < len(last_published_dof) else tgt
            if lp != tgt:
                # 第一列 != 第二列 → 目标值被外部修改（控制面板/其他节点）
                any_target_drift = True
                diff = _describe_diff(name, lp, tgt)
                tags.append(f"目标已变更{diff}")
            if tgt != cur:
                # 第二列 != 第三列 → 硬件阻塞或仍在收敛中
                any_not_reached = True
                diff = _describe_diff(name, tgt, cur)
                tags.append(f"未到达{diff}")
            tag_str = " ".join(tags) if tags else "正常"
            lines.append(f"{name:<16} {lp:>7} {tgt:>7} {cur:>7}  {tag_str}")
        else:
            # 两列模式（LLM 从未发过命令）：Target | Actual
            if tgt != cur:
                any_not_reached = True
                diff = _describe_diff(name, tgt, cur)
                tags.append(f"未到达{diff}")
            tag_str = " ".join(tags) if tags else "正常"
            lines.append(f"{name:<16} {tgt:>7} {cur:>7}  {tag_str}")

    # 底部汇总注释：帮助 LLM 快速理解整体状态
    lines.append("-" * 60)
    notes = []
    if not has_published:
        notes.append("LLM 尚未发出任何命令")
    if any_target_drift:
        notes.append("部分目标值被外部修改（控制面板/其他节点）")
    if any_not_reached:
        notes.append("部分 DOF 未到达目标值（阻塞或收敛中）")
    if not notes:
        notes.append("全部一致，手部状态正常")
    lines.append(" | ".join(notes))
    lines.append("")
    return "\n".join(lines)
