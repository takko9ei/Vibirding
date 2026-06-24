"""DeepSeekClient — runtime model adapter via the OpenAI-compatible endpoint.

DeepSeek's API is OpenAI-compatible, so this client talks to it through the
`openai` SDK pointed at DeepSeek's base_url. Like GeminiClient/MockClient it
implements the one contract the loop knows (architecture section 6):

    complete(messages, tools=None) -> ModelResponse

and returns the SAME normalized ModelResponse shape (same fields; stop_reason is
the internal "tool_use"/"end_turn"/... vocabulary), so swapping the client is
invisible to loop / registry / tools / trace.

Manual function calling only: we declare tools, execute them ourselves, and send
results back as role="tool" messages. The OpenAI chat.completions API never
auto-executes functions, so there is nothing to disable.

All OpenAI/DeepSeek shapes are confined to this file. Verified against the
installed openai SDK (2.43.0) + DeepSeek docs (api-docs.deepseek.com).
"""

from __future__ import annotations

import json

from openai import APIError, OpenAI

from .. import config
from ..schemas import ModelResponse, ToolCall


class DeepSeekError(Exception):
    """Clean, user-facing error — raised instead of leaking a raw stack trace."""


# Map OpenAI/DeepSeek finish_reason -> internal normalized stop_reason.
# (tool_calls is handled separately, by the presence of message.tool_calls.)
_FINISH_MAP = {"stop": "end_turn", "length": "max_tokens"}


class DeepSeekClient:
    """Provider-neutral facade over DeepSeek's OpenAI-compatible chat endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float | None = None,
    ) -> None:
        # config is read lazily here (not as defaults) so the values can be
        # resolved at call time and the module imports cleanly.
        key = api_key or config.load_deepseek_api_key()
        if not key:
            raise DeepSeekError(
                "DEEPSEEK_API_KEY 未设置：请在项目根 .env 写入 DEEPSEEK_API_KEY=<your-key>。"
            )
        self.model = model or config.MODEL_NAME
        self.base_url = base_url or config.DEEPSEEK_BASE_URL
        self.temperature = config.TEMPERATURE if temperature is None else temperature
        self._client = OpenAI(api_key=key, base_url=self.base_url)

    # ── public contract ──────────────────────────────────────────────────────
    def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ModelResponse:
        # Build request OUTSIDE the try so translation bugs surface as real
        # tracebacks, not as mislabeled network errors.
        oai_messages = self._to_messages(messages)
        oai_tools = self._to_tools(tools)

        kwargs: dict = {
            "model": self.model,
            "messages": oai_messages,
            "temperature": self.temperature,
        }
        if oai_tools:  # omit entirely when there are no tools
            kwargs["tools"] = oai_tools

        try:
            resp = self._client.chat.completions.create(**kwargs)
        except APIError as e:
            # covers connection / timeout / auth / rate-limit / status errors
            raise DeepSeekError(f"DeepSeek 调用失败：{e}") from e

        return self._to_model_response(resp)

    # ── outbound: internal messages -> OpenAI messages ───────────────────────
    @staticmethod
    def _to_messages(messages: list[dict]) -> list[dict]:
        # Our internal message format is already OpenAI-shaped, so this is nearly
        # 1:1 — the only real work is nesting tool calls into OpenAI's structure.
        out: list[dict] = []
        for msg in messages:
            role = msg.get("role")

            if role in ("system", "user"):
                out.append({"role": role, "content": msg.get("content") or ""})

            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    out.append(
                        {
                            "role": "assistant",
                            "content": msg.get("content"),  # may be None
                            "tool_calls": [
                                {
                                    "id": tc["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tc["name"],
                                        # our input dict -> OpenAI JSON string
                                        "arguments": json.dumps(
                                            tc.get("input") or {}, ensure_ascii=False
                                        ),
                                    },
                                }
                                for tc in tool_calls
                            ],
                        }
                    )
                else:
                    out.append({"role": "assistant", "content": msg.get("content") or ""})

            elif role == "tool":
                # OpenAI tool message keys: role / tool_call_id / content.
                out.append(
                    {
                        "role": "tool",
                        "tool_call_id": msg["tool_call_id"],
                        "content": msg.get("content", ""),
                    }
                )

        return out

    # ── outbound: tool specs -> OpenAI tools ─────────────────────────────────
    @staticmethod
    def _to_tools(tools: list[dict] | None) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": spec["name"],
                    "description": spec["description"],
                    "parameters": spec["input_schema"],  # JSON Schema dict
                },
            }
            for spec in tools
        ]

    # ── inbound: OpenAI response -> internal ModelResponse ───────────────────
    @classmethod
    def _to_model_response(cls, resp) -> ModelResponse:
        choice = resp.choices[0]
        message = choice.message
        tool_calls = message.tool_calls or []

        if tool_calls:
            calls = [
                ToolCall(
                    id=tc.id,
                    name=tc.function.name,
                    input=cls._parse_args(tc.function.arguments),
                )
                for tc in tool_calls
            ]
            return ModelResponse(
                text=message.content,
                tool_calls=calls,
                stop_reason="tool_use",
                usage=cls._map_usage(resp.usage),
            )

        return ModelResponse(
            text=message.content,
            tool_calls=[],
            stop_reason=cls._map_finish(choice.finish_reason),
            usage=cls._map_usage(resp.usage),
        )

    @staticmethod
    def _parse_args(arguments: str | None) -> dict:
        # OpenAI/DeepSeek deliver function arguments as a JSON string.
        if not arguments:
            return {}
        try:
            return json.loads(arguments)
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _map_finish(finish_reason: str | None) -> str:
        if finish_reason is None:
            return "end_turn"
        return _FINISH_MAP.get(finish_reason, finish_reason)

    @staticmethod
    def _map_usage(usage) -> dict | None:
        if usage is None:
            return None
        return {
            "input_tokens": usage.prompt_tokens,
            "output_tokens": usage.completion_tokens,
        }
