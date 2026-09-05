"""Text-to-draft splitting for v2 slice 2.1.

The model extracts a shared context plus observation-specific facts. This
service validates that structured result and performs context inheritance in
ordinary Python, so the important merge rule is deterministic and testable.
It has no database, media, taxonomy, or external-tool side effects.
"""

from __future__ import annotations

from datetime import date
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from ..schemas import (
    BirdIdCandidate,
    BirdIdResult,
    DraftObservation,
    ModelResponse,
    PhotoIdentification,
    PhotoInput,
)


RETURN_TOOL_NAME = "return_text_split"


class TextSplitError(ValueError):
    """The input or model response cannot produce a trustworthy draft batch."""


class _CompletesMessages(Protocol):
    def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ModelResponse: ...


class _IdentifiesBirds(Protocol):
    def identify(self, image_path: str) -> BirdIdResult: ...


class _SharedContext(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    place: str | None = None
    obs_date: str | None = None
    time_of_day: str | None = None

    @field_validator("obs_date")
    @classmethod
    def obs_date_must_be_iso(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)


class _SplitObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # When omitted, these three fields inherit from shared_context. An explicit
    # null is meaningful: it overrides the shared value with "unknown".
    place: str | None = None
    obs_date: str | None = None
    time_of_day: str | None = None
    species_label: str | None = None
    count: int | None = None
    behavior: str | None = None
    raw_note: str
    confidence: float | None = None
    flags: list[str] = Field(default_factory=list)
    needs_confirmation: bool = False

    @field_validator("obs_date")
    @classmethod
    def obs_date_must_be_iso(cls, value: str | None) -> str | None:
        return _validate_iso_date(value)

    @field_validator("raw_note")
    @classmethod
    def raw_note_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("raw_note must not be blank")
        return value


class _TextSplitPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    shared_context: _SharedContext
    observations: list[_SplitObservation] = Field(min_length=1)


def _validate_iso_date(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("obs_date must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise ValueError("obs_date must use YYYY-MM-DD")
    return value


RETURN_TEXT_SPLIT_TOOL = {
    "name": RETURN_TOOL_NAME,
    "description": (
        "Return the complete structured split of the user's birding note. "
        "This is a result envelope, not an external action."
    ),
    "input_schema": _TextSplitPayload.model_json_schema(),
}


_SYSTEM_PROMPT = """你负责把一整篇观鸟笔记拆成独立观测草稿。

必须且只能调用一次 return_text_split，不要输出自由文本。

规则：
1. 一种鸟的一次观测是一条 observation，保持用户叙述顺序。
2. 全文共享的地点、日期、时段只写进 shared_context；每条 observation 省略这些字段即可继承。
3. 某条有自己的地点、日期或时段时，在该条显式填写以覆盖共享值。
4. obs_date 使用 YYYY-MM-DD。依据给定参考日期解析“今天、昨天”等相对日期。
5. raw_note 只保留与该条观测有关的用户原文片段，不要改写成整篇笔记。
6. 不要根据常识编造物种、数量、行为或上下文。物种不确定时 species_label=null，
   needs_confirmation=true；其他明显歧义也标记 needs_confirmation=true。
7. flags 只记录确实需要向用户说明的解析问题；没有就返回空列表。
8. 不处理照片，不生成 species_id，不写数据库。"""


class TextSplitService:
    """Split one natural-language note into validated text-only drafts."""

    def __init__(self, llm: _CompletesMessages) -> None:
        self._llm = llm

    def split(
        self, text: str, reference_date: date | None = None
    ) -> list[DraftObservation]:
        clean_text = text.strip()
        if not clean_text:
            raise TextSplitError("text must not be blank")

        resolved_date = reference_date or date.today()
        response = self._llm.complete(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": (
                        f"参考日期：{resolved_date.isoformat()}\n"
                        f"待拆分笔记：{clean_text}"
                    ),
                },
            ],
            tools=[RETURN_TEXT_SPLIT_TOOL],
        )

        if len(response.tool_calls) != 1:
            raise TextSplitError(
                "model must return exactly one return_text_split tool call"
            )
        call = response.tool_calls[0]
        if call.name != RETURN_TOOL_NAME:
            raise TextSplitError(
                f"model returned unexpected tool call: {call.name}"
            )

        try:
            payload = _TextSplitPayload.model_validate(call.input)
        except ValidationError as exc:
            raise TextSplitError(f"invalid text split payload: {exc}") from exc

        return [
            self._to_draft(item, payload.shared_context, index)
            for index, item in enumerate(payload.observations, start=1)
        ]

    @staticmethod
    def _to_draft(
        item: _SplitObservation, shared: _SharedContext, index: int
    ) -> DraftObservation:
        def inherit(field_name: str) -> str | None:
            if field_name in item.model_fields_set:
                return getattr(item, field_name)
            return getattr(shared, field_name)

        needs_confirmation = item.needs_confirmation or item.species_label is None
        return DraftObservation(
            client_draft_id=f"draft-{index}",
            place=inherit("place"),
            obs_date=inherit("obs_date"),
            time_of_day=inherit("time_of_day"),
            count=item.count,
            behavior=item.behavior,
            raw_note=item.raw_note,
            species_label=item.species_label,
            species_id=None,
            confidence=item.confidence,
            source="user",
            flags=item.flags,
            photo_ids=[],
            needs_confirmation=needs_confirmation,
        )


class PhotoPreprocessError(ValueError):
    """The caller supplied an ambiguous photo batch."""


class PhotoPreprocessService:
    """Convert a batch of photo references into one candidate per photo."""

    def __init__(self, bird_identifier: _IdentifiesBirds) -> None:
        self._bird_identifier = bird_identifier

    def preprocess(
        self, photos: list[PhotoInput]
    ) -> list[PhotoIdentification]:
        photo_ids = [photo.photo_id for photo in photos]
        if len(set(photo_ids)) != len(photo_ids):
            raise PhotoPreprocessError("photo_id values must be unique within a batch")

        results: list[PhotoIdentification] = []
        for photo in photos:
            recognition = self._bird_identifier.identify(photo.image_path)
            first_candidate = self._first_candidate(recognition)

            if recognition.status == "identified" and first_candidate is not None:
                results.append(
                    PhotoIdentification(
                        photo_id=photo.photo_id,
                        candidate=first_candidate,
                        status="identified",
                    )
                )
                continue

            status = (
                "failed" if recognition.status == "failed" else "unrecognized"
            )
            warning = recognition.message
            if recognition.status == "identified" and first_candidate is None:
                status = "unrecognized"
                warning = "懂鸟第一目标没有候选种。"
            results.append(
                PhotoIdentification(
                    photo_id=photo.photo_id,
                    status=status,
                    warning=warning,
                )
            )
        return results

    @staticmethod
    def _first_candidate(
        recognition: BirdIdResult,
    ) -> BirdIdCandidate | None:
        if not recognition.targets or not recognition.targets[0]:
            return None
        return recognition.targets[0][0]
