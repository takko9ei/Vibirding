"""Explainable species-ID photo-to-text matching with no write side effects."""

from __future__ import annotations

from collections import defaultdict
from uuid import UUID

from ..schemas import (
    DraftObservation,
    DraftSpeciesResolution,
    DryRunMatchPlan,
    PhotoIdentification,
    PhotoMatchPlan,
    SpeciesLookup,
    TaxonomyResolution,
)
from .taxonomy import TaxonomyService


class DryRunMatchingService:
    """Resolve text and photo species, then return a non-mutating match plan."""

    def __init__(self, taxonomy: TaxonomyService) -> None:
        self._taxonomy = taxonomy

    def plan(
        self,
        drafts: list[DraftObservation],
        photos: list[PhotoIdentification],
    ) -> DryRunMatchPlan:
        draft_lookups = [
            SpeciesLookup(species_label=draft.species_label) for draft in drafts
        ]
        identified_photos = [
            photo
            for photo in photos
            if photo.status == "identified" and photo.candidate is not None
        ]
        photo_lookups = [
            SpeciesLookup(
                species_label=photo.candidate.species_label,
                scientific_name=photo.candidate.scientific_name,
            )
            for photo in identified_photos
            if photo.candidate is not None
        ]

        all_resolutions = self._taxonomy.resolve_many(
            draft_lookups + photo_lookups
        )
        draft_resolutions = all_resolutions[: len(drafts)]
        photo_resolutions = iter(all_resolutions[len(drafts) :])

        draft_plans = [
            DraftSpeciesResolution(
                client_draft_id=draft.client_draft_id,
                resolution=resolution,
            )
            for draft, resolution in zip(drafts, draft_resolutions, strict=True)
        ]

        drafts_by_species: dict[UUID, list[str]] = defaultdict(list)
        for draft_plan in draft_plans:
            resolution = draft_plan.resolution
            if resolution.status == "resolved" and resolution.species_id is not None:
                drafts_by_species[resolution.species_id].append(
                    draft_plan.client_draft_id
                )

        identified_resolution_by_photo = {
            photo.photo_id: resolution
            for photo, resolution in zip(
                identified_photos, photo_resolutions, strict=True
            )
        }

        warnings: list[str] = []
        for draft_plan in draft_plans:
            if draft_plan.resolution.warning:
                warnings.append(
                    f"草稿 {draft_plan.client_draft_id}："
                    f"{draft_plan.resolution.warning}"
                )

        photo_plans: list[PhotoMatchPlan] = []
        for photo in photos:
            plan = self._plan_photo(
                photo,
                identified_resolution_by_photo.get(photo.photo_id),
                drafts_by_species,
            )
            photo_plans.append(plan)
            if plan.warning:
                warnings.append(f"照片 {photo.photo_id}：{plan.warning}")

        return DryRunMatchPlan(
            drafts=draft_plans,
            photos=photo_plans,
            warnings=warnings,
        )

    @staticmethod
    def _plan_photo(
        photo: PhotoIdentification,
        resolution: TaxonomyResolution | None,
        drafts_by_species: dict[UUID, list[str]],
    ) -> PhotoMatchPlan:
        if photo.status in ("unrecognized", "failed"):
            return PhotoMatchPlan(
                photo_id=photo.photo_id,
                status=photo.status,
                warning=photo.warning,
            )

        if photo.candidate is None or resolution is None:
            return PhotoMatchPlan(
                photo_id=photo.photo_id,
                status="unmapped",
                warning="照片没有可供名录解析的第一候选。",
            )

        if resolution.status != "resolved" or resolution.species_id is None:
            return PhotoMatchPlan(
                photo_id=photo.photo_id,
                resolution=resolution,
                status=resolution.status,
                warning=resolution.warning,
            )

        matching_drafts = drafts_by_species.get(resolution.species_id, [])
        if not matching_drafts:
            return PhotoMatchPlan(
                photo_id=photo.photo_id,
                resolution=resolution,
                status="unmatched",
                warning="照片物种没有对应的文本草稿。",
            )
        if len(matching_drafts) > 1:
            return PhotoMatchPlan(
                photo_id=photo.photo_id,
                resolution=resolution,
                status="ambiguous",
                warning=(
                    "照片物种对应多个文本草稿："
                    + "、".join(matching_drafts)
                ),
            )
        return PhotoMatchPlan(
            photo_id=photo.photo_id,
            resolution=resolution,
            status="matched",
            client_draft_id=matching_drafts[0],
        )
