#!/usr/bin/env python
"""S3 entry — run one real birding note through the loop with range_check live.

Mirrors scripts/run_deepseek.py; the difference is that the registry now also
carries the range_check tool, so the model can fetch the local recent eBird
species list and pick a species from it (architecture section 8, round 2). Needs
BOTH keys: DEEPSEEK_API_KEY (runtime model) and EBIRD_API_KEY (range_check).

The default note misspells the place ("卡西临海公园") on purpose: it exercises the
full chain — prompt corrects it to 葛西临海公园 -> hits the coordinate table ->
range_check actually queries eBird.

Usage (must use the project venv):
    .venv/Scripts/python.exe scripts/run_s3.py ["你的观鸟笔记..."]
"""

from __future__ import annotations

import json
import re
import sys
import uuid
from datetime import datetime, timezone
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
from vibirding.schemas import Observation  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolRegistry  # noqa: E402

DEFAULT_NOTE = (
    "今天上午在水元公园看到一直灰色、大型的涉禽，嘴巴很长，脖子很长，头部有深蓝色的条带"
)


def _extract_json(text: str | None) -> str | None:
    """Pull the JSON object out of the model's final text (fenced or bare)."""
    if not text:
        return None
    m = re.search(r"```json\s*(.+?)```", text, re.DOTALL) or re.search(
        r"```\s*(.+?)```", text, re.DOTALL
    )
    if m:
        return m.group(1).strip()
    start, end = text.find("{"), text.rfind("}")  # fallback: first {...last }
    return text[start : end + 1] if start != -1 and end > start else None


def main() -> int:
    note = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_NOTE

    # ---- wiring: like run_deepseek.py, plus the range_check tool ----
    registry = ToolRegistry()
    registry.register(ReadLogTool())
    registry.register(RangeCheckTool())
    trace = TraceWriter(run_id=f"s3_{datetime.now():%Y%m%d_%H%M%S}")
    # One model call per loop step. range_check adds a tool round, so allow a bit
    # more headroom than run_deepseek.py (3): a range_check round + a final.
    budget = Budget(max_steps=4)
    permissions = Permissions()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": note},
    ]
    events: list = []

    print("=" * 64)
    print("S3：用真 DeepSeek + 真 range_check(eBird) 跑一条无图笔记")
    print("用户笔记:", note)
    print("-" * 64)

    try:
        llm = DeepSeekClient()  # may raise DeepSeekError if key missing
        final_messages, final_text = run_agent_turn(
            messages, registry, llm, permissions, budget, trace, on_event=events.append
        )
    except DeepSeekError as e:
        print()
        print("✗ 调用 DeepSeek 失败：", e)
        return 1

    print("-" * 64)
    print("模型最终回复:\n", final_text)
    print("-" * 64)

    # ---- observability summary ----
    kinds = [e.kind for e in events]

    def _called(tool_name: str) -> bool:
        return any(
            e.kind == "tool_result" and e.detail.get("name") == tool_name
            for e in events
        )

    total_in = sum((e.detail.get("usage") or {}).get("input_tokens") or 0 for e in events)
    total_out = sum((e.detail.get("usage") or {}).get("output_tokens") or 0 for e in events)
    print("事件序列        :", kinds)
    print("调用了 range_check:", _called("range_check"))
    print("调用了 read_log   :", _called("read_log"))
    print(f"token 用量      : input={total_in} output={total_out}")
    print("轨迹文件        :", trace.path)

    # ---- parse + validate the structured Observation ----
    raw = _extract_json(final_text)
    if raw is None:
        print("\n✗ 最终回复里没有找到 JSON，无法构造 Observation。")
        return 1
    try:
        data = json.loads(raw)
        # fields the model is NOT asked to fill — supplied here
        data.setdefault("id", uuid.uuid4().hex[:8])
        data.setdefault("timestamp", datetime.now(timezone.utc).isoformat())
        data.setdefault("source", "inferred")
        obs = Observation.model_validate(data)
    except (json.JSONDecodeError, ValueError) as e:
        print("\n✗ JSON 解析或 Observation 校验失败：", e)
        print("  原始 JSON 片段：", raw[:200])
        return 1

    print("\n✓ 成功产出一条结构化 Observation：")
    print(json.dumps(obs.model_dump(), ensure_ascii=False, indent=2))
    print("\nS3 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
