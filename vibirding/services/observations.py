"""Read models for observation list and management detail endpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from uuid import UUID

from ..db.models import ObservationRow, PhotoRow, SessionRow
from ..db.repository import (
    ObservationRepository,
    PhotoRepository,
    SessionRepository,
    SpeciesRepository,
)
from ..db.session import SessionFactory
from ..schemas import (
    ObservationDetail,
    ObservationListResponse,
    ObservationPhoto,
    ObservationSessionInfo,
    ObservationSummary,
    ObservationUpdateRequest,
)


class ObservationQueryError(ValueError):
    """The requested management query has contradictory bounds."""


class ObservationNotFoundError(LookupError):
    """The requested observation UUID does not exist."""


class ObservationSpeciesNotFoundError(LookupError):
    """An edit references a taxonomy UUID that does not exist."""


class ObservationReadService:
    """Build safe public observation views without database side effects."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def list_observations(
        self,
        *,
        limit: int = 20,
        place: str | None = None,
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ObservationListResponse:
        if not 1 <= limit <= 100:
            raise ObservationQueryError("limit must be between 1 and 100")
        if date_from is not None and date_to is not None and date_from > date_to:
            raise ObservationQueryError("date_from must not be after date_to")

        clean_place = self._optional_filter(place)
        clean_species = self._optional_filter(species)
        with self._session_factory() as session:
            rows = ObservationRepository(session).list_recent(
                limit=limit,
                place=clean_place,
                species=clean_species,
                date_from=date_from.isoformat() if date_from else None,
                date_to=date_to.isoformat() if date_to else None,
            )
            photos = PhotoRepository(session).list_for_observations(
                [row.id for row in rows]
            )
            photos_by_observation = self._group_photos(photos)
            items = [
                self._to_summary(row, photos_by_observation.get(row.id, []))
                for row in rows
            ]
        return ObservationListResponse(items=items)

    def get_observation(self, observation_id: UUID) -> ObservationDetail:
        with self._session_factory() as session:
            observation_repository = ObservationRepository(session)
            row = observation_repository.get_by_id(observation_id)
            if row is None:
                raise ObservationNotFoundError(
                    f"observation not found: {observation_id}"
                )
            return _detail_for_row(session, row)

    @staticmethod
    def _optional_filter(value: str | None) -> str | None:
        if value is None:
            return None
        cleaned = value.strip()
        return cleaned or None

    @staticmethod
    def _group_photos(
        photos: list[PhotoRow],
    ) -> dict[UUID, list[PhotoRow]]:
        grouped: dict[UUID, list[PhotoRow]] = defaultdict(list)
        for photo in photos:
            if photo.observation_id is not None:
                grouped[photo.observation_id].append(photo)
        return grouped

    @classmethod
    def _to_summary(
        cls,
        row: ObservationRow,
        photos: list[PhotoRow],
    ) -> ObservationSummary:
        return ObservationSummary(
            observation_id=row.id,
            timestamp=row.timestamp,
            species_label=row.species,
            species_id=row.species_id,
            count=row.count,
            place=row.place,
            obs_date=row.obs_date,
            time_of_day=row.time_of_day,
            photo_count=len(photos),
            thumbnail_url=cls._photo_url(photos[0]) if photos else None,
        )

    @classmethod
    def _to_detail(
        cls,
        row: ObservationRow,
        photos: list[PhotoRow],
        session_row: SessionRow | None,
    ) -> ObservationDetail:
        summary = cls._to_summary(row, photos)
        return ObservationDetail(
            **summary.model_dump(),
            behavior=row.behavior,
            raw_note=row.raw_note,
            confidence=row.confidence,
            source=row.source,
            flags=list(row.flags),
            photos=[cls._to_photo(photo) for photo in photos],
            session=cls._to_session(session_row) if session_row else None,
        )

    @classmethod
    def _to_photo(cls, row: PhotoRow) -> ObservationPhoto:
        return ObservationPhoto(
            media_id=row.id,
            url=cls._photo_url(row),
            original_filename=row.original_filename,
            mime_type=row.mime_type,
            size_bytes=row.size_bytes,
        )

    @staticmethod
    def _to_session(row: SessionRow) -> ObservationSessionInfo:
        return ObservationSessionInfo(
            session_id=row.id,
            created_at=row.created_at,
            raw_text=row.raw_text,
            status=row.status,
        )

    @staticmethod
    def _photo_url(row: PhotoRow) -> str:
        return f"/media/{row.content_hash}.jpg"


class ObservationEditService:
    """Apply one atomic management edit without changing audit relations."""

    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory

    def update_observation(
        self,
        observation_id: UUID,
        request: ObservationUpdateRequest,
    ) -> ObservationDetail:
        changes = request.model_dump(exclude_unset=True)
        with self._session_factory() as session:
            with session.begin():
                repository = ObservationRepository(session)
                row = repository.get_for_update(observation_id)
                if row is None:
                    raise ObservationNotFoundError(
                        f"observation not found: {observation_id}"
                    )

                self._resolve_species_changes(session, changes)
                if "obs_date" in changes and changes["obs_date"] is not None:
                    changes["obs_date"] = changes["obs_date"].isoformat()
                if "species_label" in changes:
                    changes["species"] = changes.pop("species_label")

                repository.update_fields(row, changes)
                return _detail_for_row(session, row)

    @staticmethod
    def _resolve_species_changes(session, changes: dict) -> None:
        label_sent = "species_label" in changes
        species_id_sent = "species_id" in changes

        if label_sent and not species_id_sent:
            changes["species_id"] = None

        species_id = changes.get("species_id")
        if not species_id_sent or species_id is None:
            return

        species_row = SpeciesRepository(session).get_by_id(species_id)
        if species_row is None:
            raise ObservationSpeciesNotFoundError(
                f"species not found: {species_id}"
            )
        changes["species_label"] = species_row.canonical_chinese_name


def _detail_for_row(session, row: ObservationRow) -> ObservationDetail:
    """Load immutable relations and reuse the 3.4 public detail mapping."""
    photos = PhotoRepository(session).list_for_observations([row.id])
    session_row = (
        SessionRepository(session).get_by_id(row.session_id)
        if row.session_id is not None
        else None
    )
    return ObservationReadService._to_detail(row, photos, session_row)
