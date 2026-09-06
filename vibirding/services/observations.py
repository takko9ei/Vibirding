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
)
from ..db.session import SessionFactory
from ..schemas import (
    ObservationDetail,
    ObservationListResponse,
    ObservationPhoto,
    ObservationSessionInfo,
    ObservationSummary,
)


class ObservationQueryError(ValueError):
    """The requested management query has contradictory bounds."""


class ObservationNotFoundError(LookupError):
    """The requested observation UUID does not exist."""


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
            photos = PhotoRepository(session).list_for_observations([row.id])
            session_row = (
                SessionRepository(session).get_by_id(row.session_id)
                if row.session_id is not None
                else None
            )
            return self._to_detail(row, photos, session_row)

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
