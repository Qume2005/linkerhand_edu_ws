"""PySide2 chat UI for LLM hand control."""

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
    DOF_ORDER, build_system_prompt, build_user_context, get_tools,
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
    """跨线程信号中转。"""
    assistant_text_chunk = Signal(str)
    response_done = Signal(object)
    busy_changed = Signal(bool)
    error_occurred = Signal(str)


class ChatWindow(QWidget):
    """主聊天窗口。"""

    dof_publish_requested = Signal(list)

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

        self.setWindowTitle("L10 Hand - LLM Control")
        self.setFixedSize(800, 600)
        self._apply_stylesheet()
        self._build_ui()

    def set_ros_node(self, node):
        self.ros_node = node
        self.dof_publish_requested.connect(self._publish_dof)

    def _publish_dof(self, values: list):
        if self.ros_node:
            self.ros_node.publish_dof(values)

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
                values = self._extract_dof(tc.arguments)
                self._last_published_dof = list(values)
                self._add_display_msg("tool", f"set_hand_dof([{', '.join(str(v) for v in values)}])", values=values)
                self.dof_publish_requested.emit(values)
                result = f"已执行: DOF={values}"
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

    def _extract_dof(self, arguments: dict) -> list:
        values = []
        for name in DOF_ORDER:
            v = arguments.get(name, 127)
            values.append(max(0, min(255, int(v))))
        return values

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
