"""LLM 客户端抽象层 —— 统一 OpenAI 与 Anthropic 两种 API 接口。

设计模式: 基类 + 工厂
---------------------
本模块采用「抽象基类 + 具体子类 + 工厂函数」的经典模式：

- ``LLMClientBase`` — 抽象基类，定义统一的 ``send()``、``send_streaming()``、
  ``format_tool_result()``、``format_assistant_msg()`` 接口
- ``OpenAIStyleClient`` — 基于 ``openai`` Python SDK，兼容所有 OpenAI 兼容 API
  （包括 DeepSeek、通义千问等第三方中转服务）
- ``AnthropicStyleClient`` — 基于 ``anthropic`` Python SDK，处理 Anthropic
  独有的 system 参数分离和 content block 消息格式
- ``create_client()`` — 工厂函数，根据 provider 名称返回对应子类实例

统一数据类:
- ``ToolCall`` — 跨 provider 的工具调用统一表示（call_id、name、arguments）
- ``LLMResponse`` — 跨 provider 的响应统一表示（text、tool_calls、finish_reason）

上层模块（conversation.py、chat_widget.py）仅依赖 ``LLMClientBase`` 接口，
无需关心底层 API 差异，实现 provider-agnostic 的消息流处理。
"""

import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolCall:
    """Unified representation of a tool call from either API."""
    call_id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class LLMResponse:
    """Unified response from either API."""
    text: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    finish_reason: str = ""
    raw: Any = None


class LLMClientBase:
    """Abstract base for LLM API backends."""

    def __init__(self, api_key: str, base_url: str, model: str):
        self.api_key = api_key
        self.base_url = base_url
        self.model = model

    def send(self, messages: List[Dict[str, Any]],
             tools: List[Dict[str, Any]]) -> LLMResponse:
        raise NotImplementedError

    def send_streaming(self, messages: List[Dict[str, Any]],
                       tools: List[Dict[str, Any]],
                       on_text_chunk: Callable[[str], None],
                       on_done: Callable[[LLMResponse], None]) -> None:
        raise NotImplementedError

    def format_tool_result(self, call: ToolCall, result: str) -> Dict[str, Any]:
        raise NotImplementedError

    def format_assistant_msg(self, response: LLMResponse) -> Dict[str, Any]:
        raise NotImplementedError


class OpenAIStyleClient(LLMClientBase):
    """Uses the openai Python package."""

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, base_url, model)
        try:
            from openai import OpenAI
        except ImportError:
            raise ImportError(
                "openai 包未安装。请运行: pip install openai"
            )
        self._client = OpenAI(api_key=api_key, base_url=base_url)

    def send(self, messages, tools):
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
        choice = response.choices[0]
        text = choice.message.content or ""
        tool_calls = []
        if choice.message.tool_calls:
            for tc in choice.message.tool_calls:
                tool_calls.append(ToolCall(
                    call_id=tc.id,
                    name=tc.function.name,
                    arguments=json.loads(tc.function.arguments),
                ))
        return LLMResponse(
            text=text,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
            raw=response,
        )

    def send_streaming(self, messages, tools, on_text_chunk, on_done):
        response = self._client.chat.completions.create(
            model=self.model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=True,
        )
        text_parts = []
        tool_calls_acc: Dict[int, Dict[str, str]] = {}
        finish_reason = "stop"

        for chunk in response:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta.content:
                text_parts.append(delta.content)
                on_text_chunk(delta.content)
            if delta.tool_calls:
                for tc_delta in delta.tool_calls:
                    idx = tc_delta.index
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {"id": "", "name": "", "arguments": ""}
                    if tc_delta.id:
                        tool_calls_acc[idx]["id"] = tc_delta.id
                    if tc_delta.function:
                        if tc_delta.function.name:
                            tool_calls_acc[idx]["name"] = tc_delta.function.name
                        if tc_delta.function.arguments:
                            tool_calls_acc[idx]["arguments"] += tc_delta.function.arguments
            if chunk.choices[0].finish_reason:
                finish_reason = chunk.choices[0].finish_reason

        tool_calls = []
        for idx in sorted(tool_calls_acc.keys()):
            acc = tool_calls_acc[idx]
            tool_calls.append(ToolCall(
                call_id=acc["id"],
                name=acc["name"],
                arguments=json.loads(acc["arguments"]) if acc["arguments"] else {},
            ))

        on_done(LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=finish_reason,
        ))

    def format_tool_result(self, call, result):
        return {
            "role": "tool",
            "tool_call_id": call.call_id,
            "content": result,
        }

    def format_assistant_msg(self, response):
        msg: Dict[str, Any] = {"role": "assistant", "content": response.text or None}
        if response.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc.call_id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in response.tool_calls
            ]
        return msg


class AnthropicStyleClient(LLMClientBase):
    """Uses the anthropic Python package."""

    def __init__(self, api_key: str, base_url: str, model: str):
        super().__init__(api_key, base_url, model)
        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "anthropic 包未安装。请运行: pip install anthropic"
            )
        self._client = Anthropic(api_key=api_key, base_url=base_url)

    def _split_system(self, messages):
        """Anthropic takes system as a separate parameter."""
        system_parts = []
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_parts.append(m["content"])
            else:
                filtered.append(m)
        return "\n".join(system_parts).strip(), filtered

    def send(self, messages, tools):
        system_text, filtered = self._split_system(messages)
        response = self._client.messages.create(
            model=self.model,
            system=system_text,
            messages=filtered,
            tools=tools,
            max_tokens=4096,
        )
        text_parts = []
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(ToolCall(
                    call_id=block.id,
                    name=block.name,
                    arguments=block.input,
                ))
        return LLMResponse(
            text="".join(text_parts),
            tool_calls=tool_calls,
            finish_reason=response.stop_reason,
            raw=response,
        )

    def send_streaming(self, messages, tools, on_text_chunk, on_done):
        system_text, filtered = self._split_system(messages)
        with self._client.messages.stream(
            model=self.model,
            system=system_text,
            messages=filtered,
            tools=tools,
            max_tokens=4096,
        ) as stream:
            text_parts = []
            for text in stream.text_stream:
                text_parts.append(text)
                on_text_chunk(text)

            final = stream.get_final_message()
            tool_calls = []
            for block in final.content:
                if block.type == "tool_use":
                    tool_calls.append(ToolCall(
                        call_id=block.id,
                        name=block.name,
                        arguments=block.input,
                    ))
            on_done(LLMResponse(
                text="".join(text_parts),
                tool_calls=tool_calls,
                finish_reason=final.stop_reason,
            ))

    def format_tool_result(self, call, result):
        return {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": call.call_id,
                    "content": result,
                }
            ],
        }

    def format_assistant_msg(self, response):
        content: List[Dict[str, Any]] = []
        if response.text:
            content.append({"type": "text", "text": response.text})
        for tc in response.tool_calls:
            content.append({
                "type": "tool_use",
                "id": tc.call_id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return {"role": "assistant", "content": content}


def create_client(provider: str, api_key: str, base_url: str,
                  model: str) -> LLMClientBase:
    """Factory: create the appropriate client based on provider name."""
    if provider == "Anthropic":
        return AnthropicStyleClient(api_key, base_url, model)
    return OpenAIStyleClient(api_key, base_url, model)
