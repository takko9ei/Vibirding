"""read_log — a READ-ONLY tool that looks up past observations.

S1 ships a FAKE version: it returns a small hardcoded list of sightings and does
NOT touch any file (the real append-only log + query arrive in S4). It exists so
the loop has a believable read tool to call. Risk is "read", so it sails through
the permission gate.

It satisfies the Tool protocol from tools/registry.py:
    name / description / input_schema / schema / risk / run(input, ctx)
"""

from __future__ import annotations

from pydantic import BaseModel

from ..schemas import ToolResult
from .registry import ToolContext


class ReadLogInput(BaseModel):
    """Our-side validation: every filter is optional (you may query for all)."""

    place: str | None = None
    species: str | None = None
    date_range: str | None = None  # free-form for now, e.g. "2025-01..2025-12"


# A tiny canned "log" standing in for data/observations.jsonl until S4.
_FAKE_LOG: list[dict] = [
    {"obs_date": "2025-04-12", "place": "卡西临海公园", "species": "黑翅长脚鹬", "count": 12},
    {"obs_date": "2025-09-03", "place": "卡西临海公园", "species": "黑翅长脚鹬", "count": 8},
    {"obs_date": "2025-05-20", "place": "城北湿地", "species": "白鹭", "count": 3},
]


class ReadLogTool:
    """The fake read_log tool instance registered into the ToolRegistry."""

    name = "read_log"
    description = (
        "查历史观测记录，可按地点(place)、鸟种(species)、日期范围(date_range)过滤；"
        "用于核验某地某季是否见过某种鸟。"
    )
    # JSON Schema handed to the model as the function-declaration parameters.
    input_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "地点名"},
            "species": {"type": "string", "description": "鸟种名"},
            "date_range": {"type": "string", "description": "日期范围，如 2025-01..2025-12"},
        },
        "required": [],
    }
    schema = ReadLogInput
    risk = "read"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        # Light filtering over the canned list (substring match) just so the
        # result reflects the query. Still 100% offline, no file I/O.
        place = input.get("place")
        species = input.get("species")
        rows = [
            r
            for r in _FAKE_LOG
            if (place is None or place in r["place"])
            and (species is None or species in r["species"])
        ]
        if not rows:
            return ToolResult(ok=True, output="（无匹配的历史观测记录）")
        lines = [
            f"{r['obs_date']} {r['place']} {r['species']} ×{r['count']}" for r in rows
        ]
        return ToolResult(ok=True, output="历史观测：\n" + "\n".join(lines))
