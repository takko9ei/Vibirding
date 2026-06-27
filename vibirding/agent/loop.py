"""run_agent_turn — the model -> tool -> model turn loop.

This is the heart of the agent. It repeatedly asks the model what to do; when the
model wants tools it runs them, feeds the results back, and asks again; it stops
when the model ends its turn or the budget runs out. Every step writes one trace
line.

The loop is strictly provider-neutral: it only ever touches the normalized
ModelResponse / ToolResult shapes. "tool_use" here is an INTERNAL normalized
value — the loop never sees the provider's raw shapes (the client handles that).

Contract (architecture section 6, signature locked from S1):
    run_agent_turn(messages, tools, llm, permissions, budget, trace, on_event=...)
        -> (final_messages, final_text)
    # `tools` is the ToolRegistry: it both produces the model menu (specs())
    #  and executes calls (execute()).
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from ..schemas import TraceEvent
from ..tools.registry import ToolContext


def _preview(text: str | None, limit: int = 120) -> str:
    """Short, single-purpose helper: trim long/None text for trace details."""
    if not text:
        return ""
    return text if len(text) <= limit else text[:limit] + "…"


def run_agent_turn(
    messages: list[dict],
    tools,  # ToolRegistry — see module docstring
    llm,  # LLMClient (MockClient offline; DeepSeekClient/GeminiClient for real models)
    permissions,
    budget,
    trace,
    on_event: Callable[[TraceEvent], None] | None = None,
) -> tuple[list[dict], str | None]:
    # Build the execution context once; the write gate reads permissions from it.
    ctx = ToolContext(permissions=permissions)
    step = 0  # trace line counter (distinct from budget's loop-step counter)
    final_text: str | None = None

    def emit(kind: str, summary: str, detail: dict) -> None:
        """Write one trace line to the primary sink and the optional observer."""
        nonlocal step
        step += 1
        event = TraceEvent(
            step=step,
            timestamp=datetime.now().isoformat(),
            kind=kind,
            summary=summary,
            detail=detail,
        )
        trace.emit(event)  # primary sink: prints + appends JSONL
        if on_event is not None:
            on_event(event)  # optional extra observer

    # Each budget.tick() consumes one loop step; returns False once max_steps hit.
    while budget.tick():
        resp = llm.complete(messages, tools=tools.specs())
        emit(
            "model_call",
            f"模型响应 stop_reason={resp.stop_reason}，请求 {len(resp.tool_calls)} 个工具",
            {
                "stop_reason": resp.stop_reason,
                "n_tool_calls": len(resp.tool_calls),
                "usage": resp.usage,
                "text_preview": _preview(resp.text),
            },
        )
        # S6: feed this call's token usage to the budget. Signature/control flow
        # are unchanged; tick() (checked before the next call) will stop the loop
        # if the token cap is now exceeded — never mid-response.
        budget.observe(resp.usage)

        if resp.stop_reason == "tool_use":
            # 1. record the assistant's tool-call turn in the conversation
            messages.append(
                {
                    "role": "assistant",
                    "content": resp.text,
                    "tool_calls": [tc.model_dump() for tc in resp.tool_calls],
                }
            )
            # 2. run each requested tool, appending its result + two trace lines
            for call in resp.tool_calls:
                emit(
                    "tool_call",
                    f"调用工具 {call.name}",
                    {"name": call.name, "input": call.input},
                )
                result = tools.execute(call.name, call.input, ctx)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "name": call.name,
                        "content": result.output,
                    }
                )
                emit(
                    "tool_result",
                    f"工具 {call.name} 返回 ok={result.ok}",
                    {
                        "name": call.name,
                        "ok": result.ok,
                        "output_preview": _preview(result.output),
                    },
                )
            # 3. loop again so the model sees the tool results
            continue

        # Any non-tool_use stop_reason ends the turn (normally "end_turn").
        final_text = resp.text
        messages.append({"role": "assistant", "content": resp.text})
        emit(
            "final",
            f"最终答复：{_preview(resp.text)}",
            {"stop_reason": resp.stop_reason, "text_preview": _preview(resp.text)},
        )
        return messages, final_text

    # Fell out of the while: budget ran out before the model ended its turn.
    emit(
        "budget_stop",
        f"预算耗尽停止：{budget.stop_reason()}",
        {"stop_reason": budget.stop_reason()},
    )
    return messages, final_text
