"""多轮对话历史管理器 —— Provider 无关的消息格式化。

本模块管理 LLM 对话的消息列表（system / user / assistant / tool 角色），
屏蔽不同 API 提供者（OpenAI vs Anthropic）的消息格式差异。

核心设计
--------
``ConversationManager`` 不直接操作 provider 特有的消息结构，而是委托给
``LLMClientBase`` 的 ``format_assistant_msg()`` 和 ``format_tool_result()``
方法。这样同一个 ConversationManager 实例可以在运行时切换 provider 而无需
重置对话历史。

使用示例::

    from l10_right_hand_llm.conversation import ConversationManager
    from l10_right_hand_llm.llm_client import create_client

    client = create_client("OpenAI", api_key="...", base_url="...", model="gpt-4o")
    conv = ConversationManager(system_prompt="你是一个机器人手控制助手")

    conv.add_user("比个耶")
    response = client.send(conv.get_messages(), tools)
    conv.add_assistant(response, client)

    for tc in response.tool_calls:
        conv.add_tool_result(tc, "已执行", client)

    # 下一轮对话 — 系统会带上完整的消息历史
    response2 = client.send(conv.get_messages(), tools)
"""

from typing import Any, Dict, List

from l10_right_hand_llm.llm_client import LLMClientBase, LLMResponse, ToolCall


class ConversationManager:
    """Provider-agnostic multi-turn conversation history."""

    def __init__(self, system_prompt: str):
        self._messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt}
        ]

    def add_user(self, text: str) -> None:
        self._messages.append({"role": "user", "content": text})

    def add_assistant(self, response: LLMResponse,
                      client: LLMClientBase) -> None:
        msg = client.format_assistant_msg(response)
        self._messages.append(msg)

    def add_tool_result(self, call: ToolCall, result: str,
                        client: LLMClientBase) -> None:
        msg = client.format_tool_result(call, result)
        self._messages.append(msg)

    def get_messages(self) -> List[Dict[str, Any]]:
        return list(self._messages)

    def update_system(self, content: str) -> None:
        self._messages[0] = {"role": "system", "content": content}

    def clear(self, system_prompt: str) -> None:
        self._messages = [{"role": "system", "content": system_prompt}]
