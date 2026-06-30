#!/usr/bin/env python
"""S5 entry — end-to-end: a note -> tidy -> append_log (with a real y/n/a gate) ->
then a query -> read_log reads the just-written record back.

This is the first run where the agent PERSISTS: the model calls append_log, the
write gate prompts you in the terminal, and on "yes" the Observation is appended
to the real data/observations.jsonl. A second turn then asks a question so the
model calls read_log and reads that record back from the same file.

All four tools are registered (read_log + range_check + bird_id + append_log).
The write gate's approver is a REAL stdin y/n/a prompt, injected here at the entry
layer (input() never lives inside permissions.check / the execution path).

Run (default note, or pass your own):
    .venv/Scripts/python.exe scripts/run_s5.py
    .venv/Scripts/python.exe scripts/run_s5.py "今早葛西临海公园约15只黑翅长脚鹬"

Needs DEEPSEEK_API_KEY (and EBIRD_API_KEY only if the model calls range_check).
"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.deepseek_client import DeepSeekClient, DeepSeekError  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.tools.bird_id import BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolManager  # noqa: E402

# A note that names the species + place, so the write path is the focus (the model
# may still call range_check to sanity-check). Override via argv.
DEFAULT_NOTE = "2025-06-27 上午，葛西临海公园，约15只黑翅长脚鹬在浅滩觅食。"
# A second-turn question that should make the model call read_log on the same log.
QUERY_NOTE = "我在葛西临海公园都记录过哪些鸟？"


def _cli_approver(tool_name: str, risk: str, inp: dict) -> str:
    """Real terminal write-approval prompt — injected into Permissions.

    Shows a digest of the Observation about to be written, then reads y/n/a.
    Returns the richer vocabulary Permissions understands: allow / deny / always.
    """
    print()
    print("⚠  即将写入日志（append_log）：")
    print(f"     地点   : {inp.get('place')}")
    print(f"     日期   : {inp.get('obs_date')}")
    print(f"     时段   : {inp.get('time_of_day')}")
    print(f"     种     : {inp.get('species')}")
    print(f"     数量   : {inp.get('count')}")
    print(f"     source : {inp.get('source')}")
    print(f"     flags  : {inp.get('flags')}")
    print(f"     原文   : {inp.get('raw_note')}")
    ans = input("   写入日志？[y]允许 / [n]拒绝 / [a]本回合都允许: ").strip().lower()
    if ans == "a":
        return "always"
    if ans == "y":
        return "allow"
    return "deny"


def _called_ok(events: list, tool_name: str) -> bool:
    return any(
        e.kind == "tool_result" and e.detail.get("name") == tool_name and e.detail.get("ok")
        for e in events
    )


def _tokens(events: list) -> tuple[int, int]:
    tin = sum((e.detail.get("usage") or {}).get("input_tokens") or 0 for e in events)
    tout = sum((e.detail.get("usage") or {}).get("output_tokens") or 0 for e in events)
    return tin, tout


def _turn(llm, registry, permissions, note: str, run_id: str, max_steps: int):
    """Run one agent turn over `note`; return (final_text, events)."""
    trace = TraceWriter(run_id=run_id)
    budget = Budget(max_steps=max_steps)
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": note},
    ]
    events: list = []
    _, final_text = run_agent_turn(
        messages, registry, llm, permissions, budget, trace, on_event=events.append
    )
    return final_text, events, trace


def main() -> int:
    note = " ".join(sys.argv[1:]).strip() or DEFAULT_NOTE
    log = Log()  # the REAL data/observations.jsonl

    # ---- wiring: all four tools; read tools + the one write tool ----
    registry = ToolManager()
    registry.register(ReadLogTool(log))
    registry.register(RangeCheckTool())
    registry.register(BirdIdTool())
    registry.register(AppendLogTool(log))
    # One Permissions for the whole session: "always" persists across both turns.
    permissions = Permissions(approver=_cli_approver)

    try:
        llm = DeepSeekClient()  # raises DeepSeekError if key missing
    except DeepSeekError as e:
        print("✗ 初始化 DeepSeek 失败：", e)
        return 1

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    before = len(log.query())

    # ===== Turn 1: note -> tidy -> append_log (y/n/a gate) =====
    print("=" * 64)
    print("S5 端到端 · 回合1：整理笔记 → append_log（写前需确认）")
    print("笔记:", note)
    print("-" * 64)
    try:
        final1, events1, trace1 = _turn(
            llm, registry, permissions, note, f"s5_write_{stamp}", max_steps=6
        )
    except DeepSeekError as e:
        print("✗ 调用 DeepSeek 失败：", e)
        return 1

    print("-" * 64)
    print("模型最终回复:\n", final1)
    print("-" * 64)
    tin, tout = _tokens(events1)
    print("事件序列          :", [e.kind for e in events1])
    print("调用了 range_check :", _called_ok(events1, "range_check"))
    print("调用并写入 append_log:", _called_ok(events1, "append_log"))
    print(f"token 用量        : input={tin} output={tout}")
    print("轨迹文件          :", trace1.path)

    after = len(log.query())
    print(f"\n日志条数: {before} → {after}（本回合新增 {after - before} 条）")
    for o in log.query():
        cnt = f"×{o.count}" if o.count is not None else "×?"
        print(f"   - {o.obs_date} {o.place} {o.species} {cnt} (source={o.source}, id={o.id})")

    # ===== Turn 2: query -> read_log reads it back =====
    print("\n" + "=" * 64)
    print("S5 端到端 · 回合2：查询 → read_log 真读")
    print("提问:", QUERY_NOTE)
    print("-" * 64)
    final2, events2, trace2 = _turn(
        llm, registry, permissions, QUERY_NOTE, f"s5_query_{stamp}", max_steps=4
    )
    print("-" * 64)
    print("模型最终回复:\n", final2)
    print("-" * 64)
    print("事件序列        :", [e.kind for e in events2])
    print("调用了 read_log :", _called_ok(events2, "read_log"))
    print("轨迹文件        :", trace2.path)

    print("\nS5 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
