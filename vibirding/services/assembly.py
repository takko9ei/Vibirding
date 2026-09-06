"""Assemble the complete preview and create drafts for unmatched photos."""

from __future__ import annotations

from collections.abc import Iterable
from uuid import UUID

from ..schemas import (
    DraftObservation,
    ParseResult,
    PhotoDraft,
    PhotoIdentification,
)
from .matching import DryRunMatchingService


class ParseAssemblyError(ValueError):
    """The supplied draft or photo batch has ambiguous client identities."""


class ParseAssemblyService:
    """Build a side-effect-free preview from dry-run matching results."""

    def __init__(self, matching: DryRunMatchingService) -> None:
        self._matching = matching

    def assemble(
        self,
        drafts: list[DraftObservation],
        photos: list[PhotoIdentification],
    ) -> ParseResult:
        self._validate_unique_ids(drafts, photos)
        plan = self._matching.plan(drafts, photos)

        assembled = [draft.model_copy(deep=True) for draft in drafts]
        drafts_by_id = {draft.client_draft_id: draft for draft in assembled}
        photos_by_id = {photo.photo_id: photo for photo in photos}

        for draft_plan in plan.drafts:
            draft = drafts_by_id[draft_plan.client_draft_id]
            resolution = draft_plan.resolution
            if resolution.status == "resolved" and resolution.species_id is not None:
                draft.species_id = resolution.species_id
            else:
                draft.needs_confirmation = True

        context = {
            field: self._consensus(getattr(draft, field) for draft in drafts)
            for field in ("place", "obs_date", "time_of_day")
        }
        used_ids = set(drafts_by_id)
        generated_by_species: dict[UUID, DraftObservation] = {}
        unmatched_links: list[PhotoDraft] = []
        next_number = 1

        for photo_plan in plan.photos:
            if photo_plan.status == "matched" and photo_plan.client_draft_id:
                target = drafts_by_id[photo_plan.client_draft_id]
                if photo_plan.photo_id not in target.photo_ids:
                    target.photo_ids.append(photo_plan.photo_id)
                continue

            resolution = photo_plan.resolution
            if (
                photo_plan.status != "unmatched"
                or resolution is None
                or resolution.species_id is None
            ):
                continue

            generated = generated_by_species.get(resolution.species_id)
            if generated is None:
                client_draft_id, next_number = self._next_generated_id(
                    used_ids, next_number
                )
                photo = photos_by_id[photo_plan.photo_id]
                candidate = photo.candidate
                if candidate is None:
                    raise ParseAssemblyError(
                        "unmatched photo is missing its resolved candidate"
                    )
                generated = DraftObservation(
                    client_draft_id=client_draft_id,
                    place=context["place"],
                    obs_date=context["obs_date"],
                    time_of_day=context["time_of_day"],
                    count=None,
                    behavior=None,
                    raw_note=f"由未匹配照片自动生成：{candidate.species_label}",
                    species_label=candidate.species_label,
                    species_id=resolution.species_id,
                    confidence=None,
                    source="bird_id",
                    flags=["auto_created_from_unmatched_photo"],
                    photo_ids=[],
                    needs_confirmation=True,
                )
                generated_by_species[resolution.species_id] = generated
                assembled.append(generated)
                drafts_by_id[client_draft_id] = generated

            generated.photo_ids.append(photo_plan.photo_id)
            unmatched_links.append(
                PhotoDraft(
                    photo_id=photo_plan.photo_id,
                    client_draft_id=generated.client_draft_id,
                )
            )

        return ParseResult(
            draft_observations=assembled,
            unmatched_photos=unmatched_links,
            warnings=list(plan.warnings),
        )

    @staticmethod
    def _validate_unique_ids(
        drafts: list[DraftObservation],
        photos: list[PhotoIdentification],
    ) -> None:
        draft_ids = [draft.client_draft_id for draft in drafts]
        if len(set(draft_ids)) != len(draft_ids):
            raise ParseAssemblyError("client_draft_id values must be unique")
        photo_ids = [photo.photo_id for photo in photos]
        if len(set(photo_ids)) != len(photo_ids):
            raise ParseAssemblyError("photo_id values must be unique")

    @staticmethod
    def _consensus(values: Iterable[str | None]) -> str | None:
        collected = list(values)
        if not collected:
            return None
        first = collected[0]
        return first if all(value == first for value in collected[1:]) else None

    @staticmethod
    def _next_generated_id(
        used_ids: set[str],
        starting_number: int,
    ) -> tuple[str, int]:
        number = starting_number
        while f"photo-draft-{number}" in used_ids:
            number += 1
        client_draft_id = f"photo-draft-{number}"
        used_ids.add(client_draft_id)
        return client_draft_id, number + 1
