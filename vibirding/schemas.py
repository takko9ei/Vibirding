"""Core data structures — the "blood type" of the whole system.

These models are completely provider-neutral: the loop, tools, memory and eval
layers only ever speak in terms of the types defined here, never in terms of
the runtime provider's native shapes (DeepSeek/OpenAI). Per docs/architecture.md section 4, this file is locked
first, before anything else is built.

All models use pydantic for validation.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    field_validator,
    model_validator,
)


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


class PhotoInput(BaseModel):
    """A caller-owned photo reference passed to the preprocessing slice."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    image_path: str

    @field_validator("image_path")
    @classmethod
    def image_path_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("image_path must not be blank")
        return value


class BirdIdCandidate(BaseModel):
    """One normalized candidate returned by the visual-ID provider."""

    model_config = ConfigDict(extra="forbid")

    species_label: str
    english_name: str | None = None
    scientific_name: str | None = None
    confidence: float = Field(ge=0, le=100)
    provider_candidate_id: str | None = None


class BirdIdResult(BaseModel):
    """Structured visual-ID adapter result, retaining candidates by target."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["identified", "unrecognized", "failed"]
    targets: list[list[BirdIdCandidate]] = Field(default_factory=list)
    message: str | None = None


class PhotoIdentification(BaseModel):
    """The single automatic candidate selected for one input photo."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    candidate: BirdIdCandidate | None = None
    status: Literal["identified", "unrecognized", "failed"]
    warning: str | None = None


class SpeciesCatalogEntry(BaseModel):
    """One provider-backed species row ready for catalog import."""

    model_config = ConfigDict(extra="forbid")

    taxonomy_source: str
    taxonomy_key: str
    canonical_chinese_name: str
    scientific_name: str | None = None
    aliases: list[str] = Field(default_factory=list)

    @field_validator("taxonomy_source", "taxonomy_key", "canonical_chinese_name")
    @classmethod
    def required_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("required taxonomy text must not be blank")
        return value

    @field_validator("scientific_name")
    @classmethod
    def optional_text_is_trimmed(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class SpeciesRecord(SpeciesCatalogEntry):
    """A species catalog row with its stable internal UUID."""

    id: UUID


class SpeciesLookup(BaseModel):
    """Names available when resolving text or a photo candidate."""

    model_config = ConfigDict(extra="forbid")

    species_label: str | None = None
    scientific_name: str | None = None


class TaxonomyResolution(BaseModel):
    """Explainable result of resolving names to one internal species ID."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["resolved", "unmapped", "ambiguous"]
    species_id: UUID | None = None
    matched_by: Literal["scientific_name", "canonical_name", "alias"] | None = None
    candidate_species_ids: list[UUID] = Field(default_factory=list)
    warning: str | None = None


class DraftSpeciesResolution(BaseModel):
    """Taxonomy resolution for one immutable input draft."""

    model_config = ConfigDict(extra="forbid")

    client_draft_id: str
    resolution: TaxonomyResolution


class PhotoMatchPlan(BaseModel):
    """Dry-run disposition for one photo, without mutating a draft."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    resolution: TaxonomyResolution | None = None
    status: Literal[
        "matched",
        "unmatched",
        "ambiguous",
        "unmapped",
        "unrecognized",
        "failed",
    ]
    client_draft_id: str | None = None
    warning: str | None = None


class DryRunMatchPlan(BaseModel):
    """Complete explainable matching plan produced without observation writes."""

    model_config = ConfigDict(extra="forbid")

    drafts: list[DraftSpeciesResolution]
    photos: list[PhotoMatchPlan]
    warnings: list[str] = Field(default_factory=list)


class PhotoDraft(BaseModel):
    """Audit link from an unmatched photo to its generated preview draft."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    client_draft_id: str


class ParseResult(BaseModel):
    """Complete pre-confirmation preview assembled from text and photos."""

    model_config = ConfigDict(extra="forbid")

    draft_observations: list[DraftObservation]
    unmatched_photos: list[PhotoDraft] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    job_status: Literal["completed"] = "completed"


class PhotoMetadataInput(BaseModel):
    """Metadata for a file already saved by the future media upload service."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    content_hash: str
    storage_path: str
    original_filename: str
    mime_type: str
    size_bytes: int = Field(ge=0)
    candidate: BirdIdCandidate | None = None

    @field_validator("content_hash")
    @classmethod
    def content_hash_must_be_sha256(cls, value: str) -> str:
        value = value.strip().lower()
        if len(value) != 64:
            raise ValueError("content_hash must be a 64-character SHA-256 hex value")
        try:
            bytes.fromhex(value)
        except ValueError as exc:
            raise ValueError("content_hash must contain hexadecimal characters") from exc
        return value

    @field_validator("storage_path", "original_filename", "mime_type")
    @classmethod
    def metadata_text_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("photo metadata text must not be blank")
        return value


class StoredPhoto(BaseModel):
    """A persisted content-addressed photo and its deduplication outcome."""

    model_config = ConfigDict(extra="forbid")

    photo_id: UUID
    content_hash: str
    storage_path: str
    original_filename: str
    mime_type: str
    size_bytes: int
    created: bool


class MediaUploadResponse(BaseModel):
    """Public HTTP response for a newly stored or reused media object."""

    model_config = ConfigDict(extra="forbid")

    media_id: UUID
    hash: str
    url: str


class ParseRequest(BaseModel):
    """HTTP input for a side-effect-free parse preview."""

    model_config = ConfigDict(extra="forbid")

    text: str
    media_ids: list[UUID]

    @model_validator(mode="after")
    def require_content_and_unique_media(self) -> "ParseRequest":
        if not self.text.strip() and not self.media_ids:
            raise ValueError("text and media_ids cannot both be empty")
        if len(set(self.media_ids)) != len(self.media_ids):
            raise ValueError("media_ids must be unique within a request")
        return self


class ObservationCreateRequest(BaseModel):
    """Public HTTP confirmation request without an untrusted user identity."""

    model_config = ConfigDict(extra="forbid")

    text: str
    media_ids: list[UUID]
    observations: list[DraftObservation] = Field(min_length=1)
    confirmed: StrictBool

    @model_validator(mode="after")
    def require_original_input(self) -> "ObservationCreateRequest":
        if not self.text.strip() and not self.media_ids:
            raise ValueError("text and media_ids cannot both be empty")
        return self


class ConfirmedBatch(BaseModel):
    """One explicit user confirmation request for a complete draft batch."""

    model_config = ConfigDict(extra="forbid")

    raw_text: str
    media_ids: list[UUID] = Field(default_factory=list)
    observations: list[DraftObservation] = Field(min_length=1)
    confirmed: StrictBool
    user_id: UUID | None = None

    @model_validator(mode="after")
    def require_original_input(self) -> "ConfirmedBatch":
        if not self.raw_text.strip() and not self.media_ids:
            raise ValueError("raw_text and media_ids cannot both be empty")
        return self


class CreatedObservation(BaseModel):
    """One successfully persisted draft."""

    model_config = ConfigDict(extra="forbid")

    client_draft_id: str
    observation_id: UUID


class FailedObservation(BaseModel):
    """One rejected draft and its user-visible reason."""

    model_config = ConfigDict(extra="forbid")

    client_draft_id: str
    reason: str


class BatchWriteResult(BaseModel):
    """Partial-success result; both lists are always present."""

    model_config = ConfigDict(extra="forbid")

    session_id: UUID
    created: list[CreatedObservation] = Field(default_factory=list)
    failed: list[FailedObservation] = Field(default_factory=list)


class TraceEvent(BaseModel):
    """One line logged per loop step (observability)."""

    step: int
    timestamp: str
    kind: str  # "model_call" | "tool_call" | "tool_result" | "final" | "budget_stop"
    summary: str  # one human-readable sentence
    detail: dict = Field(default_factory=dict)  # tool name, input/output preview, etc.
