#!/usr/bin/env python
"""S4 entry — end-to-end test of "photo + note" on the testimgs set.

Each run picks ONE image + its sibling note (``<stem>_discribe.txt``) from the
test folder, feeds the note as the user message with the photo path appended
(``（附图，本地路径：…）``), registers read_log + range_check + bird_id, runs the
agent turn, and prints the structured Observation. Across the set the notes cover
the source-priority branches: a note that names the species (-> source="user",
photo used as a cross-check) and one that does not (-> bird_id decides, branch 3).

Pick which case to run, or leave it to random:
    .venv/Scripts/python.exe scripts/run_s4.py            # random pick
    .venv/Scripts/python.exe scripts/run_s4.py byx        # run a specific stem

Needs DEEPSEEK_API_KEY + HHO_API_KEY (and EBIRD_API_KEY if range_check fires).
"""

from __future__ import annotations

import json
import random
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
from vibirding.tools.bird_id import BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolManager  # noqa: E402

# The folder holding <stem>.jpg paired with <stem>_discribe.txt notes.
TESTIMGS_DIR = Path(r"C:\Users\Takko\Desktop\testimgs")
_DESC_SUFFIX = "_discribe.txt"  # note the source's spelling


def _load_cases(folder: Path) -> dict[str, tuple[Path, str]]:
    """Discover {stem: (image_path, note_text)} pairs in the folder."""
    cases: dict[str, tuple[Path, str]] = {}
    for img in sorted(folder.glob("*.jpg")):
        desc = folder / f"{img.stem}{_DESC_SUFFIX}"
        if desc.is_file():
            cases[img.stem] = (img, desc.read_text(encoding="utf-8").strip())
    return cases


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
    cases = _load_cases(TESTIMGS_DIR)
    if not cases:
        print(f"✗ 在 {TESTIMGS_DIR} 没找到任何 <stem>.jpg + <stem>{_DESC_SUFFIX} 配对。")
        return 1

    # pick the case: explicit stem arg, else random
    want = sys.argv[1] if len(sys.argv) > 1 else None
    if want and want not in cases:
        print(f"✗ 未知用例 '{want}'。可选：{', '.join(cases)}")
        return 1
    stem = want or random.choice(list(cases))
    image_path, note = cases[stem]

    # the photo is signalled to the model via the user message (entry-layer wiring;
    # loop/schema untouched). bird_id reads this same local path.
    user_content = f"{note}\n（附图，本地路径：{image_path}）"

    # ---- wiring: all three read tools registered ----
    registry = ToolManager()
    registry.register(ReadLogTool())
    registry.register(RangeCheckTool())
    registry.register(BirdIdTool())
    trace = TraceWriter(run_id=f"s4_{stem}_{datetime.now():%Y%m%d_%H%M%S}")
    budget = Budget(max_steps=5)  # bird_id round (+ maybe range_check) + final
    permissions = Permissions()
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]
    events: list = []

    print("=" * 64)
    print(f"S4 端到端：用例 '{stem}'（真 DeepSeek + read_log/range_check/bird_id）")
    print("笔记:", note)
    print("图片:", image_path)
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
    print("调用了 bird_id    :", _called("bird_id"))
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
    print("\nS4 OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
