"""read_log — a READ-ONLY tool that looks up YOUR OWN past observations.

It is a personal-history lookup / weak prior ("have I logged this species here or
in this season before?"), NOT an authoritative season/range check — authoritative
seasonality/distribution belongs to range_check (eBird). See architecture sec 7.

S5: this now reads the REAL append-only log (memory/log.py Log.query) instead of
the S1 hardcoded fake list. Its external contract is unchanged — same
name / description / input_schema / schema / risk="read"; only run() changed (plus
an injectable Log handle so tests can point at a temp file). risk is "read", so it
sails through the permission gate.

Satisfies the Tool protocol (tools/registry.py):
    name / description / input_schema / schema / risk / run(input, ctx)
"""

from __future__ import annotations

from pydantic import BaseModel

from ..memory.log import Log
from ..schemas import Observation, ToolResult
from .registry import ToolContext


class ReadLogInput(BaseModel):
    """Our-side validation: every filter is optional (you may query for all)."""

    place: str | None = None
    species: str | None = None
    date_range: str | None = None  # free-form, e.g. "2025-01..2025-12"


class ReadLogTool:
    """The read_log tool instance registered into the ToolRegistry."""

    name = "read_log"
    description = (
        "查你自己的历史观测记录，可按地点(place)、鸟种(species)、日期范围(date_range)过滤。"
        "这是个人记录、弱先验（“我以前在这儿/这季节记录过什么”），"
        "不是权威的季节/分布核验。"
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

    def __init__(self, log: Log | None = None) -> None:
        # Injectable log handle: default = real file; tests pass a temp-path Log.
        self._log = log or Log()

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        # Real read: hand the optional filters to Log.query and format the hits.
        rows = self._log.query(
            place=input.get("place"),
            species=input.get("species"),
            date_range=input.get("date_range"),
        )
        if not rows:
            return ToolResult(ok=True, output="（无匹配的历史观测记录）")
        lines = [_format_row(o) for o in rows]
        return ToolResult(ok=True, output="历史观测：\n" + "\n".join(lines))


def _format_row(o: Observation) -> str:
    """One observation -> one human-readable line (None-safe; pure function)."""
    date = o.obs_date or "?"
    place = o.place or "?"
    species = o.species or "?"
    count = f"×{o.count}" if o.count is not None else "×?"
    return f"{date} {place} {species} {count}"
