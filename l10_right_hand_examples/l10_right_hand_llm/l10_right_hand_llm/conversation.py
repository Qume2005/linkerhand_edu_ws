"""Multi-turn conversation history management."""

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
