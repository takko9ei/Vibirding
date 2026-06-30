"""append_log — the ONLY write tool: append one Observation to the log.

This is the single tool with risk="write", so it is the only call that must pass
the permission gate (registry.py: if risk=="write" -> permissions.check) before it
runs. The model fills in the Observation fields it can judge; the two machine
fields (id, timestamp) are supplied here by run(), NOT by the model.

Per architecture section 7, turning a messy note into structured fields is the
model's own job, not a tool — the model reasons and puts the result straight into
this tool's arguments.

Satisfies the Tool protocol (tools/registry.py):
    name / description / input_schema / schema / risk / run(input, ctx)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from ..memory.log import Log
from ..schemas import Observation, ToolResult
from .registry import ToolContext


class AppendLogInput(BaseModel):
    """Our-side validation: mirrors Observation MINUS id/timestamp.

    id and timestamp are machine-generated in run(), so the model never supplies
    them. raw_note and source have no default -> they are required (the model must
    always provide the original note and where the species came from).
    """

    place: str | None = None
    obs_date: str | None = None
    time_of_day: str | None = None
    species: str | None = None
    count: int | None = None
    behavior: str | None = None
    raw_note: str  # required: the original messy note, kept verbatim
    confidence: float | None = None
    source: str  # required: "user" | "bird_id" | "inferred" | "manual"
    flags: list[str] = Field(default_factory=list)


class AppendLogTool:
    """The append_log tool instance registered into the ToolManager."""

    name = "append_log"
    description = (
        "把你整理好的一条观测记录写入观鸟日志（持久化）。这是唯一会写入的工具，"
        "执行前需经用户确认。参数就是这条观测的各字段；不要填 id 和 timestamp，"
        "它们由系统自动生成。"
    )
    # JSON Schema handed to the model as the function-declaration parameters.
    # id / timestamp are intentionally NOT exposed — run() fills them.
    input_schema = {
        "type": "object",
        "properties": {
            "place": {"type": "string", "description": "地点标准官方名（或省略）"},
            "obs_date": {"type": "string", "description": "观测日期 ISO，如 2026-06-27"},
            "time_of_day": {"type": "string", "description": "时段，如 上午/黄昏"},
            "species": {"type": "string", "description": "鉴定出的鸟种；不确定就省略"},
            "count": {"type": "integer", "description": "数量"},
            "behavior": {"type": "string", "description": "行为描述"},
            "raw_note": {"type": "string", "description": "用户原始笔记原文（务必原样保留）"},
            "confidence": {"type": "number", "description": "把握 0~1；source=user 时省略"},
            "source": {
                "type": "string",
                "description": "物种来源：user | bird_id | inferred | manual",
            },
            "flags": {
                "type": "array",
                "items": {"type": "string"},
                "description": "标注，如 place_corrected/autoid_conflict/low_confidence",
            },
        },
        "required": ["raw_note", "source"],
    }
    schema = AppendLogInput
    risk = "write"  # the ONE write tool -> the only one that hits the permission gate

    def __init__(self, log: Log | None = None) -> None:
        # Injectable log handle: default = real file; tests pass a temp-path Log.
        self._log = log or Log()

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        """Build the full Observation (adding the machine fields) and append it.

        The registry has already validated `input` against AppendLogInput and, for
        a write tool, passed the permission gate — so by the time we get here the
        write is authorized. We add id/timestamp, validate the COMPLETE Observation
        (belt-and-suspenders), append one line, and report a short summary. Any
        unexpected I/O error propagates to the registry, which normalizes it to
        ok=False (full tool error-tolerance is S6).
        """
        data = dict(input)  # copy so we never mutate the caller's dict
        data["id"] = uuid.uuid4().hex[:8]
        data["timestamp"] = datetime.now(timezone.utc).isoformat()
        obs = Observation.model_validate(data)
        self._log.append(obs)
        return ToolResult(ok=True, output=f"已写入日志：{_summary(obs)}")


def _summary(obs: Observation) -> str:
    """One-line, human-readable digest of what was written (pure function)."""
    parts = [
        obs.place or "?地点",
        obs.obs_date or "?日期",
        obs.species or "?种",
        f"×{obs.count}" if obs.count is not None else "×?",
    ]
    tail = f"（source={obs.source}"
    if obs.flags:
        tail += f", flags={obs.flags}"
    tail += f", id={obs.id}）"
    return " ".join(parts) + " " + tail
