"""PySide2 聊天 UI —— LLM 手部控制的图形交互界面。

本模块实现基于 PySide2 (Qt) 的聊天窗口，用于与 LLM 进行自然语言对话并
实时控制灵巧手。支持流式响应显示、Markdown 渲染、暗色主题、工具调用展示。
"""

import html
import re
import threading
from typing import List, Optional

from PySide2.QtCore import Qt, Signal
from PySide2.QtGui import QFont, QTextCursor
from PySide2.QtWidgets import (
    QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTextEdit, QVBoxLayout, QWidget,
)

from l10_right_hand_llm.conversation import ConversationManager
from l10_right_hand_llm.llm_client import LLMClientBase, LLMResponse, create_client
from l10_right_hand_llm.settings_dialog import SettingsDialog
from l10_right_hand_llm.tool_definition import (
    DOF_ORDER, build_system_prompt, build_user_context, eval_vector, get_tools,
)

# ---- 暗色主题配色 ----
COLOR_BG = "#2d2d2d"
COLOR_SURFACE = "#3c3c3c"
COLOR_TEXT = "#cccccc"
COLOR_TEXT_DIM = "#888888"
COLOR_USER_BG = "#1a5276"
COLOR_ASSISTANT_BG = "#3c3c3c"
COLOR_TOOL_BG = "#5d4e37"
COLOR_ERROR = "#e74c3c"

# ---- Markdown → HTML ----
_CODE_BLOCK_RE = re.compile(r'```(\w*)\n(.*?)```', re.DOTALL)
_INLINE_CODE_RE = re.compile(r'`([^`\n]+)`')
_BOLD_RE = re.compile(r'\*\*(.+?)\*\*')
_ITALIC_RE = re.compile(r'(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)')


def markdown_to_html(text: str) -> str:
    """简易 Markdown → HTML 转换。"""
    # 先转义 HTML 特殊字符 (保留后续 markdown 语法)
    text = html.escape(text)
    # 代码块
    text = _CODE_BLOCK_RE.sub(
        lambda m: f'<pre style="background:#1e1e1e;border-radius:6px;padding:8px;overflow-x:auto;"><code>{m.group(2)}</code></pre>',
        text,
    )
    # 行内代码
    text = _INLINE_CODE_RE.sub(
        r'<code style="background:#1e1e1e;padding:2px 5px;border-radius:3px;">\1</code>',
        text,
    )
    # 粗体
    text = _BOLD_RE.sub(r'<b>\1</b>', text)
    # 斜体
    text = _ITALIC_RE.sub(r'<i>\1</i>', text)
    # 段落
    blocks = text.split('\n\n')
    parts = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        if block.startswith('<pre'):
            parts.append(block)
        else:
            block = block.replace('\n', '<br>')
            parts.append(f'<p style="margin:2px 0;">{block}</p>')
    return ''.join(parts)


# ---- CSS 模板 ----
_CHAT_CSS = """
body { margin: 0; padding: 4px; font-family: Sans, sans-serif; font-size: 14px; background: #252525; color: #ccc; }
pre { background: #1e1e1e; border-radius: 6px; padding: 8px; overflow-x: auto; }
code { background: #1e1e1e; padding: 2px 5px; border-radius: 3px; }
"""


class _StateSignal(QWidget):
    """跨线程信号中转站。

    由于 Qt 的信号/槽机制要求在 GUI 线程中操作控件，但 LLM API 调用
    在后台线程执行，因此需要通过 Qt Signal 将数据从工作线程安全地
    传递到主线程。_StateSignal 作为一个隐藏的 QWidget，充当信号中转：

    - ``assistant_text_chunk`` — 流式文本片段（逐字显示效果）
    - ``response_done`` — 完整响应对象（包含 tool_calls）
    - ``busy_changed`` — 忙碌状态切换（禁用/启用输入）
    - ``error_occurred`` — 错误信息展示
    """
    assistant_text_chunk = Signal(str)
    response_done = Signal(object)
    busy_changed = Signal(bool)
    error_occurred = Signal(str)


class ChatWindow(QWidget):
    """主聊天窗口 —— LLM 对话界面与灵巧手控制的桥梁。

    信号桥接模式
    ------------
    ChatWindow 采用「信号桥接」模式连接 Qt UI、ROS 节点和 LLM API 三个子系统：

    1. **Qt 内部信号** — ``_StateSignal`` 将 LLM 工作线程的流式输出、
       完成回调、错误等事件安全传递到 Qt 主线程进行 UI 更新。

    2. **跨模块信号** — ``dof_publish_requested`` 信号连接到 ROS 节点
       的 ``publish_dof()`` 方法，将 LLM 工具调用产生的 DOF 命令
       发送到 ROS 话题。由于信号在 Qt 主线程中触发，避免了跨线程
       直接调用 ROS publish 的线程安全问题。

    3. **流式渲染** — LLM 响应通过 ``send_streaming()`` 的两个回调
       (``on_text_chunk`` 和 ``on_done``) 分别处理逐字显示和最终结果，
       实现 ChatGPT 风格的流式输出效果。

    工具调用处理流程:
        用户输入 → LLM 流式推理 → tool_call → extract DOF →
        emit dof_publish_requested → ROS publish → 插值动画执行
    """

    dof_publish_requested = Signal(list, float)

    def __init__(self):
        super().__init__()
        self._sig = _StateSignal()
        self._sig.assistant_text_chunk.connect(self._on_text_chunk)
        self._sig.response_done.connect(self._on_response_done)
        self._sig.busy_changed.connect(self._set_busy)
        self._sig.error_occurred.connect(self._on_error)

        self.ros_node = None
        self._client: Optional[LLMClientBase] = None
        self._conversation = ConversationManager(build_system_prompt([255] * 10))
        self._last_published_dof = None
        self._busy = False

        # 消息列表 + 流式缓冲区
        self._display_msgs: List[dict] = []
        self._streaming_text = ""

        self.setWindowTitle("L10 灵巧手 - LLM 控制")
        self.setFixedSize(800, 600)
        self._apply_stylesheet()
        self._build_ui()

    def set_ros_node(self, node):
        self.ros_node = node
        self.dof_publish_requested.connect(self._publish_dof)

    def _publish_dof(self, values: list, duration: float):
        if self.ros_node:
            self.ros_node.publish_dof(values, duration)

    def _apply_stylesheet(self):
        self.setStyleSheet(f"""
            QWidget {{ background: {COLOR_BG}; color: {COLOR_TEXT}; }}
            QLabel {{ color: {COLOR_TEXT}; }}
            QPushButton {{
                background: {COLOR_SURFACE}; color: {COLOR_TEXT};
                border: 1px solid #555555; border-radius: 6px;
                padding: 6px 16px; font-size: 13px;
            }}
            QPushButton:hover {{ background: #4a4a4a; border-color: #777777; }}
            QPushButton:pressed {{ background: #555555; color: white; }}
            QPushButton:disabled {{ background: #333333; color: #666666; }}
            QLineEdit {{
                background: {COLOR_SURFACE}; color: {COLOR_TEXT};
                border: 1px solid #555555; border-radius: 4px;
                padding: 8px; font-size: 14px;
            }}
        """)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(12, 12, 12, 12)
        root.setSpacing(8)

        # 顶栏
        top_bar = QHBoxLayout()
        title = QLabel("L10 灵巧手 - LLM 控制")
        title.setFont(QFont("Sans", 14, QFont.Bold))
        top_bar.addWidget(title)
        top_bar.addStretch()

        self._settings_btn = QPushButton("设置")
        self._settings_btn.setFixedWidth(70)
        self._settings_btn.clicked.connect(self._open_settings)
        top_bar.addWidget(self._settings_btn)

        self._clear_btn = QPushButton("清空")
        self._clear_btn.setFixedWidth(70)
        self._clear_btn.clicked.connect(self._clear_conversation)
        top_bar.addWidget(self._clear_btn)

        root.addLayout(top_bar)

        # 聊天显示区
        self._chat_display = QTextEdit()
        self._chat_display.setReadOnly(True)
        self._chat_display.setFont(QFont("Sans", 13))
        root.addWidget(self._chat_display, stretch=1)

        # 输入栏
        input_bar = QHBoxLayout()

        self._input_field = QLineEdit()
        self._input_field.setPlaceholderText("描述一个手部手势...")
        self._input_field.returnPressed.connect(self._on_send)
        input_bar.addWidget(self._input_field, stretch=1)

        self._send_btn = QPushButton("发送")
        self._send_btn.setFixedWidth(80)
        self._send_btn.clicked.connect(self._on_send)
        input_bar.addWidget(self._send_btn)

        self._status_label = QLabel("就绪")
        self._status_label.setFixedWidth(90)
        self._status_label.setStyleSheet(f"color: {COLOR_TEXT_DIM}; font-size: 12px;")
        input_bar.addWidget(self._status_label)

        root.addLayout(input_bar)

    # ---- 设置 ----

    def _open_settings(self):
        dlg = SettingsDialog(self)
        if dlg.exec_() == SettingsDialog.Accepted:
            self._rebuild_client()

    def _rebuild_client(self):
        s = SettingsDialog.get_settings()
        if s["api_key"]:
            try:
                self._client = create_client(
                    s["provider"], s["api_key"], s["base_url"], s["model"]
                )
            except ImportError as e:
                self._client = None
                self._add_display_msg("error", str(e))
            except Exception as e:
                self._client = None
                self._add_display_msg("error", f"创建客户端失败: {e}")

    def _clear_conversation(self):
        self._last_published_dof = None
        dof = self.ros_node.get_current_dof() if self.ros_node else [255] * 10
        self._conversation.clear(build_system_prompt(dof))
        self._display_msgs.clear()
        self._streaming_text = ""
        self._render_chat()

    def _set_busy(self, busy: bool):
        self._busy = busy
        self._send_btn.setEnabled(not busy)
        self._input_field.setEnabled(not busy)
        self._status_label.setText("思考中..." if busy else "就绪")

    # ---- 发送消息 ----

    def _on_send(self):
        text = self._input_field.text().strip()
        if not text or self._busy:
            return

        if not self._client:
            self._rebuild_client()
        if not self._client:
            self._add_display_msg("error", "请先在设置中配置 API Key。")
            self._open_settings()
            return

        self._input_field.clear()
        self._add_display_msg("user", text)

        current_dof = self.ros_node.get_current_dof() if self.ros_node else [255] * 10
        target_dof = self.ros_node.get_target_dof() if self.ros_node else [255] * 10
        context = build_user_context(self._last_published_dof, target_dof, current_dof)
        self._conversation.add_user(context + text)

        self._set_busy(True)
        threading.Thread(target=self._call_llm_streaming, daemon=True).start()

    def _call_llm_streaming(self):
        try:
            self._sync_dof_state()
            s = SettingsDialog.get_settings()
            tools = get_tools(s["provider"])
            messages = self._conversation.get_messages()

            self._sig.assistant_text_chunk.emit("")

            self._client.send_streaming(
                messages, tools,
                on_text_chunk=lambda chunk: self._sig.assistant_text_chunk.emit(chunk),
                on_done=lambda resp: self._sig.response_done.emit(resp),
            )
        except Exception as e:
            self._sig.error_occurred.emit(str(e))

    # ---- Qt 主线程回调 ----

    def _on_text_chunk(self, chunk: str):
        if not chunk:
            # 开始新的 assistant 消息
            self._display_msgs.append({"role": "assistant", "text": ""})
            self._streaming_text = ""
            self._render_chat()
            return
        self._streaming_text += chunk
        # 更新最后一条 assistant 消息的文本
        for msg in reversed(self._display_msgs):
            if msg["role"] == "assistant":
                msg["text"] = self._streaming_text
                break
        self._render_chat()

    def _on_response_done(self, response: LLMResponse):
        self._streaming_text = ""
        self._conversation.add_assistant(response, self._client)

        if response.tool_calls:
            self._handle_tool_calls(response.tool_calls)
        else:
            self._set_busy(False)

    def _handle_tool_calls(self, tool_calls: list):
        for tc in tool_calls:
            if tc.name == "set_hand_dof":
                values, duration = self._extract_dof(tc.arguments)
                self._last_published_dof = list(values)
                self._add_display_msg("tool", f"set_hand_dof([{', '.join(str(v) for v in values)}], duration={duration:.3f}s)", values=values)
                self.dof_publish_requested.emit(values, duration)
                result = f"已执行: DOF={values}, 过渡={duration:.3f}s"
            elif tc.name == "queue_hand_actions":
                actions, loop = self._extract_action_queue(tc.arguments)
                last_dof = actions[-1]["dof"] if actions else [127] * 10
                self._last_published_dof = list(last_dof)
                desc = tc.arguments.get("description", "动作序列")
                step_count = len(actions)
                self._add_display_msg(
                    "tool",
                    f"queue_hand_actions(\"{desc}\", {step_count}步, 循环={loop})",
                )
                if self.ros_node:
                    self.ros_node.queue_actions(actions, loop)
                result = f"已执行动作队列: \"{desc}\", {step_count}步, 循环={loop}"
            elif tc.name == "vector_calc":
                expression = tc.arguments.get("expression", "x")
                vector = tc.arguments.get("vector", [])
                try:
                    computed = eval_vector(expression, vector)
                    # 尝试 round 为整数显示
                    display = [int(round(v)) if abs(v - round(v)) < 0.001 else round(v, 3) for v in computed]
                    result = str(display)
                except Exception as exc:
                    result = f"计算错误: {exc}"
                self._add_display_msg(
                    "tool",
                    f"vector_calc(\"{expression}\", {vector}) = {result}",
                )
            else:
                result = f"未知工具: {tc.name}"

            self._conversation.add_tool_result(tc, result, self._client)

        threading.Thread(target=self._call_llm_summary, daemon=True).start()

    def _call_llm_summary(self):
        try:
            self._sync_dof_state()
            s = SettingsDialog.get_settings()
            tools = get_tools(s["provider"])
            messages = self._conversation.get_messages()

            self._sig.assistant_text_chunk.emit("")

            self._client.send_streaming(
                messages, tools,
                on_text_chunk=lambda chunk: self._sig.assistant_text_chunk.emit(chunk),
                on_done=lambda resp: self._sig.response_done.emit(resp),
            )
        except Exception as e:
            self._sig.error_occurred.emit(str(e))

    def _sync_dof_state(self):
        dof = self.ros_node.get_current_dof() if self.ros_node else [255] * 10
        self._conversation.update_system(build_system_prompt(dof))

    def _extract_dof(self, arguments: dict):
        values = []
        for name in DOF_ORDER:
            v = arguments.get(name, 127)
            values.append(max(0, min(255, int(v))))
        duration = arguments.get("duration", None)
        if duration is None:
            duration = 0.0  # 节点会用默认值 0.618
        else:
            duration = max(0.05, min(10.0, float(duration)))
        return values, duration

    def _extract_action_queue(self, arguments: dict):
        raw_actions = arguments.get("actions", [])
        actions = []
        for step in raw_actions:
            values = []
            for name in DOF_ORDER:
                v = step.get(name, 127)
                values.append(max(0, min(255, int(v))))
            duration = step.get("duration", None)
            if duration is None:
                duration = 0.0
            else:
                duration = max(0.05, min(10.0, float(duration)))
            pause = max(0.0, min(10.0, float(step.get("pause", 0.0))))
            actions.append({
                "dof": values,
                "duration": duration,
                "pause": pause,
            })
        loop = arguments.get("loop", False)
        return actions, loop

    def _on_error(self, msg: str):
        self._add_display_msg("error", msg)
        self._set_busy(False)

    # ---- 消息列表管理 ----

    def _add_display_msg(self, role: str, text: str, values=None):
        self._display_msgs.append({"role": role, "text": text, "values": values})
        self._render_chat()

    # ---- 渲染 ----

    def _render_chat(self):
        """从 _display_msgs 构建完整 HTML 并渲染到 QTextEdit。"""
        # 保存滚动位置
        sb = self._chat_display.verticalScrollBar()
        at_bottom = sb.value() >= sb.maximum() - 20

        parts = [f'<html><head><style>{_CHAT_CSS}</style></head><body>']
        for msg in self._display_msgs:
            role = msg["role"]
            text = msg["text"]
            if role == "user":
                parts.append(
                    f'<p><b style="color:#5dade2;">你:</b> {html.escape(text)}</p>'
                )
            elif role == "assistant":
                rendered = markdown_to_html(text) if text else '<span style="color:#888;">...</span>'
                parts.append(
                    f'<p><b style="color:#82e0aa;">助手:</b> {rendered}</p>'
                )
            elif role == "tool":
                parts.append(
                    f'<p><b style="color:#f0b27a;">工具:</b> <code>{html.escape(text)}</code></p>'
                )
            elif role == "error":
                parts.append(
                    f'<p style="color:#e74c3c;"><b>错误:</b> {html.escape(text)}</p>'
                )
        parts.append('</body></html>')

        self._chat_display.setHtml(''.join(parts))

        # 恢复滚动位置
        if at_bottom:
            sb.setValue(sb.maximum())
