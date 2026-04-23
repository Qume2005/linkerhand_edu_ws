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
}

# ---------- set_hand_dof 描述 ----------
SET_DOF_DESCRIPTION = (
    "Set the joint positions of a 10-DOF robotic hand. Each value is an integer "
    "from 0 to 255. The 10 values in order are: thumb_bend, thumb_lateral, "
    "index_bend, middle_bend, ring_bend, little_bend, index_lateral, "
    "ring_lateral, little_lateral, thumb_rotation.\n\n"
    "Value semantics vary by DOF type:\n"
    "- Bend DOFs (thumb_bend, index/middle/ring/little_bend): 0=fully bent, 255=fully straight.\n"
    "- Lateral DOFs (index/ring/little_lateral): 0=fingers together, 255=slightly spread.\n"
    "- thumb_lateral: 0=retracted inward, 255=extended outward.\n"
    "- thumb_rotation: 0=rotated inward, 255=rotated outward.\n\n"
    "Common gestures for reference:\n"
    "- Open hand (all straight): [255, 255, 255, 255, 255, 255, 255, 255, 255, 255]\n"
    "- Fist (all closed): [0, 0, 0, 0, 0, 0, 0, 0, 0, 0]\n"
    "- OK gesture: [80, 110, 116, 255, 255, 255, 255, 255, 255, 54]\n"
    "- Pinch: [92, 112, 121, 0, 0, 0, 132, 0, 0, 48]\n"
    "- Point (index finger extended): [0, 128, 255, 0, 24, 16, 49, 36, 81, 16]\n"
    "- Thumbs up: [255, 255, 0, 0, 0, 0, 0, 0, 0, 0]\n\n"
    "You can combine these presets with modifications. For example, to make a "
    "peace sign, start from open and close ring and little fingers. "
    "To make a rocker/horns sign, extend index and little fingers while bending "
    "the rest. Be creative and adjust individual DOF values to achieve "
    "the requested gesture."
)

# ---------- System prompt ----------
SYSTEM_PROMPT_TEMPLATE = (
    "You are a dexterous robotic hand control assistant. "
    "Users describe hand gestures in natural language, and you translate them "
    "into precise DOF commands by calling the set_hand_dof tool. "
    "Briefly explain what gesture you are about to perform before calling the tool. "
    "Ask for clarification if the request is ambiguous. "
    "You can combine, modify, and create gestures beyond the presets.\n\n"
    "Current hand DOF state (0=fully bent, 255=fully straight):\n"
    "{dof_state}"
)

# ---------- Per-parameter definitions ----------
_DOF_PROPERTIES = {
    "thumb_bend":     "Thumb bend: 0=fully bent, 255=fully straight",
    "thumb_lateral":  "Thumb lateral: 0=retracted inward, 255=extended outward",
    "index_bend":     "Index finger bend: 0=fully bent, 255=fully straight",
    "middle_bend":    "Middle finger bend: 0=fully bent, 255=fully straight",
    "ring_bend":      "Ring finger bend: 0=fully bent, 255=fully straight",
    "little_bend":    "Little finger bend: 0=fully bent, 255=fully straight",
    "index_lateral":  "Index finger lateral: 0=fingers together, 255=slightly spread",
    "ring_lateral":   "Ring finger lateral: 0=fingers together, 255=slightly spread",
    "little_lateral": "Little finger lateral: 0=fingers together, 255=slightly spread",
    "thumb_rotation": "Thumb rotation: 0=rotated inward, 255=rotated outward",
}

# ---------- OpenAI tool ----------
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "set_hand_dof",
            "description": SET_DOF_DESCRIPTION,
            "parameters": {
                "type": "object",
                "properties": {
                    name: {
                        "type": "integer",
                        "minimum": 0,
                        "maximum": 255,
                        "description": desc,
                    }
                    for name, desc in _DOF_PROPERTIES.items()
                },
                "required": list(DOF_ORDER),
            },
        },
    },
]

# ---------- Anthropic tool ----------
ANTHROPIC_TOOLS = [
    {
        "name": "set_hand_dof",
        "description": SET_DOF_DESCRIPTION,
        "input_schema": {
            "type": "object",
            "properties": {
                name: {
                    "type": "integer",
                    "description": desc,
                }
                for name, desc in _DOF_PROPERTIES.items()
            },
            "required": list(DOF_ORDER),
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
