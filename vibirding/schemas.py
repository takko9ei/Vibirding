"""Core data structures — the "blood type" of the whole system.

These models are completely provider-neutral: the loop, tools, memory and eval
layers only ever speak in terms of the types defined here, never in terms of
the runtime provider's native shapes (DeepSeek/OpenAI). Per docs/architecture.md section 4, this file is locked
first, before anything else is built.

All models use pydantic for validation.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ToolCall(BaseModel):
    """One tool request emitted by the model.

    DeepSeekClient maps OpenAI's ``tool_call.id`` -> ``id`` and the JSON-string
    ``tool_call.function.arguments`` -> ``input``. In S1 the MockClient fills
    these directly.
    """

    id: str  # pairs this call with its matching ToolResult
    name: str  # tool name to invoke
    input: dict = Field(default_factory=dict)  # arguments the model filled in


class ToolResult(BaseModel):
    """Normalized return of a tool execution. EVERY tool returns this shape."""

    ok: bool  # success / failure
    output: str  # text shown back to the model (result or error message)


class ModelResponse(BaseModel):
    """The model response after llm/client has normalized it.

    This is the ONLY response shape the loop understands; it hides all provider
    differences. ``stop_reason`` holds an internal normalized value
    ("tool_use" | "end_turn" | "max_tokens" | ...) — the client is responsible
    for mapping the provider's finish_reason / presence-of-tool_calls into these
    values (DeepSeekClient for the OpenAI-compatible API).
    """

    text: str | None = None  # textual answer (final answer or interim message)
    tool_calls: list[ToolCall] = Field(default_factory=list)  # tools wanted this turn
    stop_reason: str  # normalized: "tool_use" | "end_turn" | "max_tokens" | ...
    usage: dict | None = None  # normalized usage {input_tokens, output_tokens}


class Observation(BaseModel):
    """One observation record written to the log — the agent's final product.

    Locked now because it is the system's blood type, but S1 does not yet write
    it (there is no append_log until S4).
    """

    id: str
    timestamp: str  # ISO time
    place: str | None = None
    obs_date: str | None = None  # date of the observation
    time_of_day: str | None = None  # morning / dusk ...
    species: str | None = None  # identified species; may be None if unsure
    count: int | None = None
    behavior: str | None = None
    raw_note: str  # the original messy note, always kept
    confidence: float | None = None  # from bird_id or the model's self-estimate
    source: str  # "user" | "bird_id" | "inferred" | "manual"
    flags: list[str] = Field(default_factory=list)  # e.g. ["season_unusual"]


class DraftObservation(BaseModel):
    """One text-derived observation awaiting preview and confirmation.

    Slice 2.1 deliberately leaves taxonomy and photo fields empty. Keeping
    those fields in the public shape now gives later matching slices a stable
    object to enrich without changing the text splitter's return type.
    """

    model_config = ConfigDict(extra="forbid")

    client_draft_id: str
    place: str | None = None
    obs_date: str | None = None
    time_of_day: str | None = None
    count: int | None = None
    behavior: str | None = None
    raw_note: str
    species_label: str | None = None
    species_id: UUID | None = None
    confidence: float | None = None
    source: str
    flags: list[str] = Field(default_factory=list)
    photo_ids: list[UUID] = Field(default_factory=list)
    needs_confirmation: bool = False


class TraceEvent(BaseModel):
    """One line logged per loop step (observability)."""

    step: int
    timestamp: str
    kind: str  # "model_call" | "tool_call" | "tool_result" | "final" | "budget_stop"
    summary: str  # one human-readable sentence
    detail: dict = Field(default_factory=dict)  # tool name, input/output preview, etc.
