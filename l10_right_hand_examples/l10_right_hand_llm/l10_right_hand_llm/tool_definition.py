"""Tool definitions for set_hand_dof in both OpenAI and Anthropic formats."""

# 10 个自由度名称 (对应 DOF0-DOF9, 0-255 范围)
DOF_ORDER = [
    "thumb_bend",       # DOF0 拇指弯曲
    "thumb_lateral",    # DOF1 拇指侧摆
    "index_bend",       # DOF2 食指弯曲
    "middle_bend",      # DOF3 中指弯曲
    "ring_bend",        # DOF4 无名指弯曲
    "little_bend",      # DOF5 小指弯曲
    "index_lateral",    # DOF6 食指侧摆
    "ring_lateral",     # DOF7 无名指侧摆
    "little_lateral",   # DOF8 小指侧摆
    "thumb_rotation",   # DOF9 拇指侧旋
]

# 预设动作 (10 个 DOF 值, 0=完全弯曲, 255=完全伸直)
PRESETS = {
    "open":  [255, 255, 255, 255, 255, 255, 255, 255, 255, 255],
    "fist":  [0, 0, 0, 0, 0, 0, 0, 0, 0, 0],
    "ok":    [80, 110, 116, 255, 255, 255, 255, 255, 255, 54],
    "pinch": [92, 112, 121, 0, 0, 0, 132, 0, 0, 48],
    "point": [0, 128, 255, 0, 24, 16, 49, 36, 81, 16],
    "peace": [30, 15, 255, 255, 0, 0, 255, 255, 255, 0],
}

# ---------- set_hand_dof 描述 ----------
SET_DOF_DESCRIPTION = (
    "Set the joint positions of a 10-DOF robotic hand. Each value is an integer "
    "from 0 to 255. The 10 values in order are: thumb_bend, thumb_lateral, "
    "index_bend, middle_bend, ring_bend, little_bend, index_lateral, "
    "ring_lateral, little_lateral, thumb_rotation.\n\n"
    "Value semantics vary by DOF type:\n"
    "- Bend DOFs (thumb_bend, index/middle/ring/little_bend): 0=fully bent (curled into palm), 255=fully straight (extended).\n"
    "- Lateral DOFs (index/ring/little_lateral): 0=fingers touching each other, 255=fingers spread apart.\n"
    "- thumb_lateral: 0=thumb tucked tightly against the palm/fingers, 255=thumb spread wide away from the palm.\n"
    "- thumb_rotation: 0=thumb rotated toward palm center (opposing fingers, like when pinching), 255=thumb rotated outward away from palm.\n\n"
    "IMPORTANT thumb rules for common gestures:\n"
    "- When the thumb should be hidden/tucked (e.g. peace/V sign, fist): use LOW values for thumb_lateral (0-30) and thumb_rotation (0-20), and a LOW thumb_bend.\n"
    "- When the thumb should be visible/extended (e.g. thumbs up, open hand): use HIGH values for thumb_lateral (200-255) and thumb_rotation (0-80), and a HIGH thumb_bend.\n"
    "- thumb_rotation is NOT the same as thumb_bend: rotation controls the thumb's twisting angle relative to the palm, not curling.\n\n"
    "Common gestures for reference:\n"
    "- Open hand (all straight): [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]\n"
    "- Fist (all closed): [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]\n"
    "- Peace / V sign (index+middle extended, rest closed, thumb tucked): [30, 15, 255, 255, 0, 0, 255, 255, 255, 0]\n"
    "- OK gesture: [80, 110, 116, 255, 255, 255, 255, 255, 255, 54]\n"
    "- Pinch: [92, 112, 121, 0, 0, 0, 132, 0, 0, 48]\n"
    "- Point (index finger extended): [0, 128, 255, 0, 24, 16, 49, 36, 81, 16]\n"
    "- Thumbs up (thumb extended, rest closed): [255, 255, 0, 0, 0, 0, 0, 0, 0, 0]\n\n"
    "You can combine these presets with modifications. For example, to make a "
    "rocker/horns sign, extend index and little fingers while bending "
    "the rest. Be creative and adjust individual DOF values to achieve "
    "the requested gesture."
)

# ---------- queue_hand_actions 描述 ----------
QUEUE_DESCRIPTION = (
    "Queue a choreographed sequence of hand poses for multi-step animation. "
    "Each step defines a target pose (10 DOF values), a transition duration, "
    "and a hold time before the next step begins.\n\n"
    "Use this tool when the user requests:\n"
    "- Multi-step motions: waving, finger counting (1-5), beckoning come-here\n"
    "- Rhythmic or repeated gestures: rock-paper-scissors, drumming fingers\n"
    "- Expressive animations: hand dance, sign language sequences\n"
    "- Any motion requiring more than one pose transition\n\n"
    "For a single pose change, use set_hand_dof instead.\n\n"
    "Each action step contains:\n"
    "- The 10 DOF values (thumb_bend through thumb_rotation, same semantics as set_hand_dof)\n"
    "- duration (seconds): transition time from the PREVIOUS pose to this step. "
    "Controls movement speed. Default 0.618s if omitted.\n"
    "- pause (seconds): how long to HOLD this pose before moving to the next step. "
    "Default 0 (immediately proceed to next step).\n\n"
    "Design tips for natural-looking sequences:\n"
    "- Short durations (0.2-0.4s) for quick, snappy gestures (snapping, tapping).\n"
    "- Longer durations (0.8-2.0s) for smooth, flowing transitions (stretching, opening).\n"
    "- Add pauses (0.2-1.0s) between key poses so each gesture is clearly visible.\n"
    "- For rhythmic motions (waving, beckoning), alternate between 2-3 poses with "
    "equal duration+pause for a natural rhythm.\n"
    "- When loop=true, the LAST step MUST include a pause value so the final pose "
    "is held before the sequence wraps around to step 1. Without it, the loop "
    "boundary will feel abrupt. Match the last step's pause to the rhythm of the "
    "other steps.\n"
    "- The FIRST step transitions from the hand's current position.\n"
    "- Use 3-8 steps for most sequences. More steps allow richer animations but "
    "take longer to generate.\n\n"
    "Example sequences:\n"
    "1. Finger counting 1 to 5:\n"
    "   Step 1: index up (index_bend=255, rest bend=0), duration=0.5, pause=0.6\n"
    "   Step 2: +middle up, duration=0.3, pause=0.6\n"
    "   Step 3: +ring up, duration=0.3, pause=0.6\n"
    "   Step 4: +little up, duration=0.3, pause=0.6\n"
    "   Step 5: open hand (all 255), duration=0.5, pause=0\n\n"
    "2. Simple wave (2 alternating poses, loop=true):\n"
    "   Step 1: open hand spread (all bend=255, laterals=255), duration=0.3, pause=0.15\n"
    "   Step 2: open hand slightly closed (bends=255, laterals=80), duration=0.3, pause=0.15\n\n"
    "3. Rock-paper-scissors:\n"
    "   Step 1: fist (all 0), duration=0.3, pause=0.8 (anticipation)\n"
    "   Step 2: fist bounce, duration=0.2, pause=0.3\n"
    "   Step 3: fist bounce again, duration=0.2, pause=0.3\n"
    "   Step 4: reveal gesture (paper=open, scissors=peace, rock=fist), duration=0.4, pause=0\n\n"
    "4. Single finger circle (any finger traces a circle while the rest stay in full fist, loop=true).\n"
    "   Use vector_calc to generate precise values. For the moving finger's bend and lateral:\n"
    "     expression='round(center + amplitude * cos(2*pi*x/N))', vector=[0,1,...,N-1]\n"
    "     expression='round(center + amplitude * sin(2*pi*x/N))', vector=[0,1,...,N-1]\n"
    "   Where center=(min+max)/2, amplitude=(max-min)/2. N=8-16 steps for smoothness.\n"
    "   Example: ring finger circle, bend center=227 amp=28, lateral center=128 amp=127, N=8:\n"
    "     bend values = vector_calc('round(227+28*cos(2*pi*x/8))', [0,1,2,3,4,5,6,7])\n"
    "     lateral values = vector_calc('round(128+127*sin(2*pi*x/8))', [0,1,2,3,4,5,6,7])\n"
    "     All other DOFs = 0 (full fist including thumb). Each step: duration=0.15, pause=0.\n"
    "     This technique works for any finger: use its (bend, lateral) pair as the two axes.\n"
)

# 队列步骤中 duration / pause 的参数描述
_STEP_DURATION_DESC = (
    "Transition time in seconds from the previous pose to this step's target pose. "
    "Controls movement speed. Default 0.618s if omitted. "
    "Use 0.2-0.5s for quick motions, 0.8-2.0s for slow smooth motions."
)
_STEP_PAUSE_DESC = (
    "Hold time in seconds at this pose before proceeding to the next step. "
    "Default 0 (no pause). Use 0.1-1.0s to let a pose be clearly visible "
    "before transitioning."
)

# ---------- vector_calc 描述 ----------
VECTOR_CALC_DESCRIPTION = (
    "Evaluate a math expression over a vector of input values. "
    "Given an expression string using variable 'x' and a list of numbers, "
    "returns a list of computed results (one per input value).\n\n"
    "Available functions and constants:\n"
    "- Trigonometric: sin(x), cos(x), tan(x) — angles in radians\n"
    "- Constants: pi (=3.14159...), e (=2.71828...)\n"
    "- Arithmetic: + - * / ** (power) % (modulo)\n"
    "- Other: sqrt(x), abs(x), round(x), int(x), min(a,b), max(a,b), pow(a,b)\n\n"
    "Use this tool to generate precise DOF value sequences mathematically, "
    "instead of computing them manually.\n\n"
    "Examples:\n"
    "- Generate 8 ring_bend values for a circle (center=227, amplitude=28):\n"
    "  expression='round(227 + 28 * cos(2 * pi * x / 8))', vector=[0,1,2,3,4,5,6,7]\n"
    "  → [255, 247, 227, 207, 199, 207, 227, 247]\n\n"
    "- Generate 8 ring_lateral values for a circle (center=128, amplitude=127):\n"
    "  expression='round(128 + 127 * sin(2 * pi * x / 8))', vector=[0,1,2,3,4,5,6,7]\n"
    "  → [128, 218, 255, 218, 128, 38, 1, 38]\n\n"
    "- Linear ramp from 0 to 255 in 10 steps:\n"
    "  expression='round(255 * x / 9)', vector=[0,1,2,3,4,5,6,7,8,9]\n"
    "  → [0, 28, 57, 85, 113, 142, 170, 198, 227, 255]\n\n"
    "- Ease-in-out curve for smooth open→close in 6 steps:\n"
    "  expression='round(255 * (1 - (x/5)**2))', vector=[0,1,2,3,4,5]\n"
    "  → [255, 245, 214, 163, 92, 0]\n\n"
    "Results are returned as a JSON array of numbers. "
    "Use round() or int() to get clean integer DOF values."
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
    "thumb_bend":     "Thumb bend: 0=fully bent (curled into palm), 255=fully straight (extended)",
    "thumb_lateral":  "Thumb lateral spread: 0=thumb tucked tightly against palm/fingers, 255=thumb spread wide away from palm",
    "index_bend":     "Index finger bend: 0=fully bent, 255=fully straight",
    "middle_bend":    "Middle finger bend: 0=fully bent, 255=fully straight",
    "ring_bend":      "Ring finger bend: 0=fully bent, 255=fully straight",
    "little_bend":    "Little finger bend: 0=fully bent, 255=fully straight",
    "index_lateral":  "Index finger lateral: 0=fingers touching, 255=fingers spread apart",
    "ring_lateral":   "Ring finger lateral: 0=fingers touching, 255=fingers spread apart",
    "little_lateral": "Little finger lateral: 0=fingers touching, 255=fingers spread apart",
    "thumb_rotation": "Thumb rotation: 0=rotated toward palm center (opposing fingers), 255=rotated outward away from palm",
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
        direction = "more outward" if d > 0 else "more inward"
    elif name == "index_lateral":
        direction = "more spread" if d > 0 else "more closed"
    elif name in ("ring_lateral", "little_lateral"):
        direction = "more spread" if d > 0 else "more closed"
    elif "bend" in name:
        direction = "straighter" if d > 0 else "more bent"
    elif "rotation" in name:
        direction = "external rotation" if d > 0 else "internal rotation"
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
    - Last publish != target → target was changed externally (control panel / other node)
    - Target != actual → hand is blocked or still converging
    - No last publish → LLM has never issued a command
    """
    has_published = last_published_dof is not None
    lines = ["[System Feedback]"]

    if has_published:
        lines.append(f"{'DOF':<16} {'LLM Pub':>7} {'Target':>7} {'Actual':>7}  Status")
    else:
        lines.append(f"{'DOF':<16} {'Target':>7} {'Actual':>7}  Status")
    lines.append("-" * 60)

    any_target_drift = False
    any_not_reached = False

    for i, name in enumerate(DOF_ORDER):
        tgt = target_dof[i] if i < len(target_dof) else 0
        cur = current_dof[i] if i < len(current_dof) else 0

        tags = []

        if has_published:
            lp = last_published_dof[i] if i < len(last_published_dof) else tgt
            if lp != tgt:
                any_target_drift = True
                diff = _describe_diff(name, lp, tgt)
                tags.append(f"target changed {diff}")
            if tgt != cur:
                any_not_reached = True
                diff = _describe_diff(name, tgt, cur)
                tags.append(f"not reached {diff}")
            tag_str = " ".join(tags) if tags else "OK"
            lines.append(f"{name:<16} {lp:>7} {tgt:>7} {cur:>7}  {tag_str}")
        else:
            if tgt != cur:
                any_not_reached = True
                diff = _describe_diff(name, tgt, cur)
                tags.append(f"not reached {diff}")
            tag_str = " ".join(tags) if tags else "OK"
            lines.append(f"{name:<16} {tgt:>7} {cur:>7}  {tag_str}")

    lines.append("-" * 60)
    notes = []
    if not has_published:
        notes.append("LLM has not issued any command yet")
    if any_target_drift:
        notes.append("Some targets modified externally (control panel / other node)")
    if any_not_reached:
        notes.append("Some DOFs have not reached target (blocked or converging)")
    if not notes:
        notes.append("All consistent, hand state normal")
    lines.append(" | ".join(notes))
    lines.append("")
    return "\n".join(lines)
