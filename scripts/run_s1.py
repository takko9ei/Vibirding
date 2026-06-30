#!/usr/bin/env python
"""S1 offline smoke test — proves the model->tool->model loop runs end to end.

Zero cost, no network, no real model: the model is a scripted MockClient and the only
tool is the fake read_log. Run it with:

    python scripts/run_s1.py

It exits non-zero (AssertionError) if anything regresses; on success it prints the
full trace and "S1 SMOKE OK". This is a dev-time smoke script under scripts/, not
part of the final delivered package.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the repo root importable when launched as `python scripts/run_s1.py`
# (otherwise only scripts/ is on sys.path and `import vibirding` would fail).
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Entry-point responsibility: force UTF-8 stdout so the Chinese trace is readable
# even on a gbk Windows console. (trace.py stays library-neutral.)
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.schemas import ModelResponse, ToolCall  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.registry import ToolManager  # noqa: E402


def main() -> int:
    note = "上午卡西临海公园，大概20只黑头红腿小型涉禽"

    # Scripted model: turn 1 asks read_log (to verify the place/season), turn 2
    # ends the turn with a structured summary.
    script = [
        ModelResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id="c1",
                    name="read_log",
                    input={"place": "卡西临海公园", "species": "黑翅长脚鹬"},
                )
            ],
            usage={"input_tokens": 42, "output_tokens": 9},
        ),
        ModelResponse(
            stop_reason="end_turn",
            text=(
                "已整理：上午，卡西临海公园，黑头红腿小型涉禽约 20 只，疑似黑翅长脚鹬；"
                "该地历史同期有记录，季节合理。"
            ),
            usage={"input_tokens": 88, "output_tokens": 37},
        ),
    ]

    registry = ToolManager()
    registry.register(ReadLogTool())

    trace = TraceWriter(run_id="s1_smoke")
    if trace.path.exists():
        trace.path.unlink()  # start clean so the line-count assertion is exact

    budget = Budget(max_steps=8)
    permissions = Permissions()

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": note},
    ]

    events: list = []
    print("=" * 64)
    print("S1 smoke：离线跑 model→tool→model 循环（MockClient，无网络、无真实模型）")
    print("用户笔记:", note)
    print("-" * 64)

    final_messages, final_text = run_agent_turn(
        messages,
        registry,
        MockClient(script),
        permissions,
        budget,
        trace,
        on_event=events.append,
    )

    print("-" * 64)
    print("最终总结:", final_text)
    print("=" * 64)

    # --- assertions (the actual S1 acceptance checks) ---
    kinds = [e.kind for e in events]
    read_log_ok = any(
        e.kind == "tool_result"
        and e.detail.get("name") == "read_log"
        and e.detail.get("ok")
        for e in events
    )
    trace_lines = trace.path.read_text(encoding="utf-8").strip().splitlines()
    used_google = [m for m in sys.modules if m.split(".")[0] == "google"]

    assert read_log_ok, "read_log 没有被成功执行"
    assert final_text, "final_text 为空"
    assert kinds[-1] == "final", f"循环未以 final 收尾，而是 {kinds[-1]}"
    assert budget.stop_reason() is None, f"不应触发预算停止：{budget.stop_reason()}"
    assert len(trace_lines) == len(events), (
        f"轨迹行数({len(trace_lines)})与事件数({len(events)})不一致"
    )
    assert not used_google, f"不应 import google-genai，但发现：{used_google}"

    print("断言通过:")
    print(f"  - read_log 已执行           : {read_log_ok}")
    print(f"  - 事件序列                  : {kinds}")
    print(f"  - 轨迹文件                  : {trace.path}  ({len(trace_lines)} 行)")
    print(f"  - 预算未触发 (正常收尾)     : stop_reason={budget.stop_reason()}")
    print(f"  - 全程未加载 google-genai   : {not used_google}")
    print(f"  - 消息角色序列              : {[m['role'] for m in final_messages]}")
    print()
    print("S1 SMOKE OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
