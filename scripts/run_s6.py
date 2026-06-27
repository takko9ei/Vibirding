#!/usr/bin/env python
"""S6 entry — manually trigger budget stops / tool failures and watch the trace.

Demonstrates "死循环/报错不会失控" on the live path:
  --max-steps 1     force a step-budget stop
  --max-tokens 50   force a token-budget stop (loop feeds usage to the budget)
  --break-ebird     point eBird at a bogus key so range_check fails (graceful)
It also injects today_hint() into the system message so the model knows the real
date (fixes the year-guess bug) — SYSTEM_PROMPT itself stays a static constant.

Run:
  .venv/Scripts/python.exe scripts/run_s6.py --max-steps 1
  .venv/Scripts/python.exe scripts/run_s6.py --max-tokens 50
  .venv/Scripts/python.exe scripts/run_s6.py --break-ebird --note "..."

Needs DEEPSEEK_API_KEY (+ EBIRD_API_KEY / HHO_API_KEY if those tools fire).
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding import config  # noqa: E402
from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT, today_hint  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.deepseek_client import DeepSeekClient, DeepSeekError  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.tools.bird_id import BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolRegistry  # noqa: E402

# A note with NO date on purpose, so today_hint() is what supplies obs_date.
DEFAULT_NOTE = "上午在葛西临海公园，看到大约15只黑翅长脚鹬在浅滩觅食。"


def _cli_approver(tool_name: str, risk: str, inp: dict) -> str:
    """Real terminal write-approval prompt — injected into Permissions."""
    print()
    print("⚠  即将写入日志（append_log）：")
    print(f"     {inp.get('place')} | {inp.get('obs_date')} | "
          f"{inp.get('species')} ×{inp.get('count')} | source={inp.get('source')}")
    ans = input("   写入？[y]允许 / [n]拒绝 / [a]本回合都允许: ").strip().lower()
    return {"a": "always", "y": "allow"}.get(ans, "deny")


def main() -> int:
    ap = argparse.ArgumentParser(description="S6 budget / error-tolerance trigger")
    ap.add_argument("--max-steps", type=int, default=6, help="step cap (try 1 to force a stop)")
    ap.add_argument("--max-tokens", type=int, default=None, help="token cap (try 50 to force a stop)")
    ap.add_argument("--break-ebird", action="store_true", help="force range_check to fail")
    ap.add_argument("--note", default=DEFAULT_NOTE, help="the bird note to process")
    args = ap.parse_args()

    if args.break_ebird:
        # Force range_check's HTTP path to fail (bogus key -> 401) to show graceful
        # degrade. The tool returns ok=False; the model is told to fall back.
        config.load_ebird_api_key = lambda: "BOGUS-KEY-FORCING-FAILURE"  # type: ignore[assignment]
        print("（--break-ebird：eBird key 改为 bogus，range_check 将失败以演示优雅回退）")

    log = Log()  # the real data/observations.jsonl
    registry = ToolRegistry()
    registry.register(ReadLogTool(log))
    registry.register(RangeCheckTool())
    registry.register(BirdIdTool())
    registry.register(AppendLogTool(log))
    permissions = Permissions(approver=_cli_approver)

    try:
        llm = DeepSeekClient()  # raises DeepSeekError if key missing
    except DeepSeekError as e:
        print("✗ 初始化 DeepSeek 失败：", e)
        return 1

    # Date injection at the entry layer: SYSTEM_PROMPT stays a static constant.
    system_content = SYSTEM_PROMPT + "\n\n" + today_hint()
    messages = [
        {"role": "system", "content": system_content},
        {"role": "user", "content": args.note},
    ]
    budget = Budget(max_steps=args.max_steps, max_tokens=args.max_tokens)
    trace = TraceWriter(run_id=f"s6_{datetime.now():%Y%m%d_%H%M%S}")
    events: list = []

    print("=" * 64)
    print(f"S6 端到端触发：max_steps={args.max_steps} "
          f"max_tokens={args.max_tokens} break_ebird={args.break_ebird}")
    print("日期锚点:", today_hint())
    print("笔记    :", args.note)
    print("-" * 64)
    try:
        _, final_text = run_agent_turn(
            messages, registry, llm, permissions, budget, trace, on_event=events.append
        )
    except DeepSeekError as e:
        print("✗ 调用 DeepSeek 失败：", e)
        return 1

    print("-" * 64)
    kinds = [e.kind for e in events]
    stopped = budget.stop_reason()
    print("事件序列    :", kinds)
    print("budget 停因 :", stopped)
    print("出现 budget_stop:", any(k == "budget_stop" for k in kinds))

    # Readable conclusion, assembled at the entry layer (loop unchanged): use the
    # model's final answer if any, else a clear "hit the limit" conclusion.
    if final_text:
        print("模型最终回复:\n", final_text)
    elif stopped:
        print(f"结论：达到 {stopped} 上限，已基于已有信息中止（本回合未产出最终答复）。")
    else:
        print("结论：（无最终答复）")
    print("轨迹文件    :", trace.path)

    print("\nS6 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
