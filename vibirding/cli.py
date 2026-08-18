#!/usr/bin/env python
"""vibirding CLI — the single delivery-grade entry point.

It collapses the wiring that S1–S7 spread across scripts/run_s*.py into one place:
register all four tools, run one agent turn over the user's text, and show the
result. There are NO subcommands — the model decides, per an intent-routing
preamble composed here at the entry layer, whether the input is a NEW sighting to
record (ends in append_log, gated) or a QUESTION about past records (read_log
only, no write).

Entry-layer message assembly (same technique as S6's today_hint(); the constant
SYSTEM_PROMPT and every tool's behavior stay untouched):

    system = SYSTEM_PROMPT + today_hint() + INTENT_PREAMBLE

Usage:
    python -m vibirding "傍晚葛西临海公园家燕十几只在低空飞"
    python -m vibirding "我在葛西临海公园记录过哪些鸟"
    python -m vibirding "水元公园一只小鸟腹部橙红抖尾" --image bird.jpg
    python -m vibirding "..." --yes --verbose --max-steps 8

Needs DEEPSEEK_API_KEY in the project-root .env (see .env.example). EBIRD_API_KEY
/ HHO_API_KEY are only needed if the model calls range_check / bird_id.
"""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Allow both `python -m vibirding` and `python vibirding/cli.py` from the repo
# root: put the repo root on sys.path, then use absolute imports.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT, today_hint  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.deepseek_client import DeepSeekClient, DeepSeekError  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import Observation  # noqa: E402
from vibirding.tools.bird_id import BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolManager  # noqa: E402

# Model-facing routing note, appended AFTER SYSTEM_PROMPT + today_hint(). It only
# routes intent; it does not change any recording rule in SYSTEM_PROMPT.
INTENT_PREAMBLE = """== 先判断本次输入的意图 ==
用户这次给你的，可能是两类之一，请先判断属于哪类：
1) 【记录】一次新的观鸟观测（一句具体的见闻描述）——按上面的流程整理，并调用 append_log 写入日志。
2) 【查询】对历史记录的提问（如“我在某地记录过哪些鸟”“我见过某种鸟吗”“上个月都记了什么”）——
   这时【只调用 read_log 查询，并直接用自然语言回答】；【不要调用 append_log、不要写入任何新记录】。
拿不准时：输入是一次具体观测就按【记录】；输入是一个问句/检索请求就按【查询】。"""


def _cli_approver(tool_name: str, risk: str, inp: dict) -> str:
    """Real terminal write-approval prompt, injected into Permissions.

    Shows a digest of the Observation about to be written, then reads y/n/a and
    returns the vocabulary Permissions understands: allow / deny / always. input()
    lives here at the entry layer only — never inside permissions.check / the
    execution path.
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


def _auto_approver(tool_name: str, risk: str, inp: dict) -> str:
    """--yes: approve every write automatically (demo / scripted use)."""
    return "always"


def _obs_line(o: Observation) -> str:
    """One written Observation -> one human-readable line."""
    count = f"×{o.count}" if o.count is not None else "×?"
    tail = f"source={o.source}"
    if o.flags:
        tail += f", flags={o.flags}"
    return (f"{o.obs_date or '?日期'} {o.place or '?地点'} "
            f"{o.species or '?种'} {count}  ({tail}, id={o.id})")


def _token_totals(events: list) -> tuple[int, int]:
    """Sum normalized input/output tokens across all model_call events."""
    tin = sum((e.detail.get("usage") or {}).get("input_tokens") or 0 for e in events)
    tout = sum((e.detail.get("usage") or {}).get("output_tokens") or 0 for e in events)
    return tin, tout


def build_registry(log: Log) -> ToolManager:
    """Register all four tools against one shared Log handle (the real log)."""
    registry = ToolManager()
    registry.register(ReadLogTool(log))
    registry.register(RangeCheckTool())
    registry.register(BirdIdTool())
    registry.register(AppendLogTool(log))
    return registry


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        prog="vibirding",
        description="观鸟速记 agent：把一句自然语言笔记整理成结构化观测并写入日志；也能查历史。",
    )
    ap.add_argument("note", nargs="+",
                    help="观鸟笔记，或对历史记录的提问（多词会自动拼接；建议加引号）")
    ap.add_argument("--image", metavar="PATH", default=None,
                    help="可选：本地鸟类图片路径，交给 bird_id 做视觉鉴种")
    ap.add_argument("-y", "--yes", action="store_true",
                    help="自动同意写入，跳过 y/n 确认（演示 / 脚本化）")
    ap.add_argument("-v", "--verbose", action="store_true",
                    help="打印完整分步 trace（默认只打简洁结果）")
    ap.add_argument("--max-steps", type=int, default=6,
                    help="单回合步数预算（默认 6）")
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    note = " ".join(args.note).strip()
    if not note:
        print("✗ 请提供笔记或查询文本。")
        return 2

    # Signal an attached image to the model the same way S4 / eval do.
    if args.image:
        if not Path(args.image).exists():
            print(f"✗ 图片文件不存在：{args.image}")
            return 2
        user_content = note + f"\n（附图，本地路径：{args.image}）"
    else:
        user_content = note

    log = Log()  # the real data/observations.jsonl
    registry = build_registry(log)
    permissions = Permissions(approver=_auto_approver if args.yes else _cli_approver)

    try:
        llm = DeepSeekClient()  # raises DeepSeekError if DEEPSEEK_API_KEY is missing
    except DeepSeekError as e:
        print("✗ 初始化 DeepSeek 失败：", e)
        print("  提示：把项目根的 .env.example 复制为 .env，并填入 DEEPSEEK_API_KEY。")
        return 2

    # Entry-layer message assembly: SYSTEM_PROMPT constant stays unchanged.
    system = SYSTEM_PROMPT + "\n\n" + today_hint() + "\n\n" + INTENT_PREAMBLE
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]
    budget = Budget(max_steps=args.max_steps)
    trace = TraceWriter(
        run_id=f"cli_{datetime.now():%Y%m%d_%H%M%S}",
        to_console=args.verbose,  # verbose -> the loop prints every step
    )
    events: list = []

    print("=" * 64)
    print("vibirding · 观鸟速记")
    print("输入 :", note + (f"   [附图 {args.image}]" if args.image else ""))
    print("-" * 64)

    before = len(log.query())
    try:
        _, final_text = run_agent_turn(
            messages, registry, llm, permissions, budget, trace, on_event=events.append
        )
    except DeepSeekError as e:
        print("✗ 调用 DeepSeek 失败（可能是网络或额度问题）：", e)
        return 1
    after = log.query()
    new_rows = after[before:]  # rows written during THIS turn (query = record -> none)

    # ---- concise result (always) ----
    print("-" * 64)
    print("结果：")
    print(final_text or "（模型没有给出最终答复；预算可能耗尽，可加大 --max-steps）")
    if new_rows:
        print(f"\n已写入 {len(new_rows)} 条观测：")
        for o in new_rows:
            print("   -", _obs_line(o))
    else:
        print("\n（本次未写入日志——查询请求，或写入被拒绝 / 未触发）")
    print("\ntrace :", trace.path)

    # ---- extra detail on --verbose ----
    if args.verbose:
        tin, tout = _token_totals(events)
        stop = budget.stop_reason()
        print("-" * 64)
        print("事件序列   :", [e.kind for e in events])
        print("token 用量 :", f"input={tin} output={tout}")
        if stop:
            print("预算停因   :", stop)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
