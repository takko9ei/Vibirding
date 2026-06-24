"""GeminiClient — the real model adapter (google-genai, manual function calling).

Its ONLY job is two-way translation so the loop never sees Gemini's shapes:

  outbound  internal `messages`            -> Gemini `contents` + GenerateContentConfig
  inbound   Gemini GenerateContentResponse -> internal `ModelResponse`

It implements the same `complete(messages, tools=None) -> ModelResponse` contract
as MockClient (architecture section 6), so swapping the client changes nothing in
the loop / registry / tools / trace.

Manual function calling only: we pass function *declarations*, execute tools
ourselves, and send function responses back — automatic function calling is
disabled. All google-genai usage was verified against the installed SDK (2.9.0).
"""

from __future__ import annotations

from google import genai
from google.genai import errors as genai_errors
from google.genai import types

from .. import config
from ..schemas import ModelResponse, ToolCall


class GeminiError(Exception):
    """Clean, user-facing error — raised instead of leaking a raw stack trace."""


# Map Gemini's finish_reason enum -> our internal normalized stop_reason values.
_FINISH_MAP = {"STOP": "end_turn", "MAX_TOKENS": "max_tokens"}


class GeminiClient:
    """Provider-neutral facade over google-genai's generate_content."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = config.MODEL_NAME,
        temperature: float = config.TEMPERATURE,
    ) -> None:
        key = api_key or config.load_api_key()
        if not key:
            raise GeminiError(
                "GEMINI_API_KEY 未设置：请在项目根 .env 写入 GEMINI_API_KEY=<your-key>。"
            )
        self.model = model
        self.temperature = temperature
        self._client = genai.Client(api_key=key)

    # ── public contract ──────────────────────────────────────────────────────
    def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ModelResponse:
        # Build request OUTSIDE the try so translation bugs surface as real
        # tracebacks rather than being mislabeled as network failures.
        system_instruction, contents = self._to_contents(messages)
        cfg = self._build_config(tools, system_instruction)

        try:
            resp = self._client.models.generate_content(
                model=self.model, contents=contents, config=cfg
            )
        except genai_errors.APIError as e:
            # bad key / 4xx / 5xx etc. — APIError stringifies to a readable message
            raise GeminiError(f"Gemini API 调用失败：{e}") from e
        except Exception as e:  # only the network call is in scope here
            raise GeminiError(f"调用 Gemini 失败（可能是网络问题）：{e}") from e

        return self._to_model_response(resp)

    # ── outbound: internal messages -> Gemini contents ───────────────────────
    @staticmethod
    def _to_contents(messages: list[dict]) -> tuple[str | None, list[types.Content]]:
        system_parts: list[str] = []
        contents: list[types.Content] = []

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "system":
                if content:
                    system_parts.append(content)

            elif role == "user":
                contents.append(
                    types.Content(role="user", parts=[types.Part.from_text(text=content or "")])
                )

            elif role == "assistant":
                tool_calls = msg.get("tool_calls")
                if tool_calls:
                    parts: list[types.Part] = []
                    if content:  # the model may emit text alongside a tool call
                        parts.append(types.Part.from_text(text=content))
                    for tc in tool_calls:
                        parts.append(
                            types.Part.from_function_call(
                                name=tc["name"], args=tc.get("input") or {}
                            )
                        )
                    contents.append(types.Content(role="model", parts=parts))
                else:
                    contents.append(
                        types.Content(role="model", parts=[types.Part.from_text(text=content or "")])
                    )

            elif role == "tool":
                # Function responses go back as role="user" (confirmed from the
                # SDK's own AFC code). Gemini pairs them to the call by NAME.
                contents.append(
                    types.Content(
                        role="user",
                        parts=[
                            types.Part.from_function_response(
                                name=msg["name"], response={"result": msg.get("content", "")}
                            )
                        ],
                    )
                )

        system_instruction = "\n".join(system_parts) if system_parts else None
        return system_instruction, contents

    # ── outbound: tool specs -> GenerateContentConfig ────────────────────────
    def _build_config(
        self, tools: list[dict] | None, system_instruction: str | None
    ) -> types.GenerateContentConfig:
        gem_tools = None
        if tools:
            declarations = [
                types.FunctionDeclaration(
                    name=spec["name"],
                    description=spec["description"],
                    parameters=spec["input_schema"],  # JSON Schema dict -> types.Schema
                )
                for spec in tools
            ]
            gem_tools = [types.Tool(function_declarations=declarations)]

        return types.GenerateContentConfig(
            temperature=self.temperature,
            system_instruction=system_instruction,
            tools=gem_tools,
            # Manual function calling: never let the SDK auto-execute anything.
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )

    # ── inbound: Gemini response -> internal ModelResponse ───────────────────
    @classmethod
    def _to_model_response(cls, resp: types.GenerateContentResponse) -> ModelResponse:
        fcs = resp.function_calls or []
        text = cls._safe_text(resp)
        usage = cls._map_usage(resp.usage_metadata)

        if fcs:
            tool_calls = [
                ToolCall(
                    id=(fc.id or f"call-{i}-{fc.name}"),  # synth id if Gemini omits one
                    name=fc.name,
                    input=(fc.args or {}),
                )
                for i, fc in enumerate(fcs)
            ]
            return ModelResponse(
                text=text, tool_calls=tool_calls, stop_reason="tool_use", usage=usage
            )

        return ModelResponse(
            text=text, tool_calls=[], stop_reason=cls._map_finish(resp), usage=usage
        )

    @staticmethod
    def _safe_text(resp: types.GenerateContentResponse) -> str | None:
        # Read text parts directly instead of resp.text: resp.text logs a noisy
        # warning when a function_call part is present. Returns None when the
        # turn carries no text (e.g. a pure tool call).
        if not resp.candidates:
            return None
        content = resp.candidates[0].content
        if content is None or not content.parts:
            return None
        texts = [p.text for p in content.parts if getattr(p, "text", None)]
        return "".join(texts) if texts else None

    @staticmethod
    def _map_finish(resp: types.GenerateContentResponse) -> str:
        if not resp.candidates:
            return "end_turn"
        fr = resp.candidates[0].finish_reason
        name = getattr(fr, "name", str(fr)) if fr is not None else "STOP"
        return _FINISH_MAP.get(name, name.lower())

    @staticmethod
    def _map_usage(
        um: types.GenerateContentResponseUsageMetadata | None,
    ) -> dict | None:
        # NOTE: the response carries GenerateContentResponseUsageMetadata, which
        # uses candidates_token_count (NOT response_token_count — that field
        # belongs to a different, unrelated usage type).
        if um is None:
            return None
        return {
            "input_tokens": getattr(um, "prompt_token_count", None),
            "output_tokens": getattr(um, "candidates_token_count", None),
        }
