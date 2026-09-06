"""Data-access semantics for observations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..schemas import (
    DraftObservation,
    Observation,
    PhotoMetadataInput,
    SpeciesCatalogEntry,
    SpeciesRecord,
)
from .models import ObservationRow, PhotoRow, SessionRow, SpeciesRow


class ObservationRepository:
    """Persist and query observations without owning transaction boundaries."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def append(self, obs: Observation) -> None:
        """Stage one observation insert in the caller's transaction."""
        self._session.add(
            ObservationRow(
                id=uuid.UUID(obs.id),
                timestamp=_parse_timestamp(obs.timestamp),
                place=obs.place,
                obs_date=obs.obs_date,
                time_of_day=obs.time_of_day,
                species=obs.species,
                count=obs.count,
                behavior=obs.behavior,
                raw_note=obs.raw_note,
                confidence=obs.confidence,
                source=obs.source,
                flags=list(obs.flags),
            )
        )
        self._session.flush()

    def query(
        self,
        place: str | None = None,
        species: str | None = None,
        date_range: str | None = None,
    ) -> list[Observation]:
        """Return matching observations in stable insertion order."""
        statement: Select[tuple[ObservationRow]] = select(ObservationRow)
        if place is not None:
            statement = statement.where(
                ObservationRow.place.is_not(None),
                ObservationRow.place.contains(place, autoescape=True),
            )
        if species is not None:
            statement = statement.where(
                ObservationRow.species.is_not(None),
                ObservationRow.species.contains(species, autoescape=True),
            )
        statement = _apply_date_range(statement, date_range)
        rows = self._session.scalars(statement.order_by(ObservationRow.sequence_no)).all()
        return [_to_observation(row) for row in rows]

    def append_draft(
        self,
        draft: DraftObservation,
        *,
        observation_id: uuid.UUID,
        timestamp: datetime,
        session_id: uuid.UUID,
        user_id: uuid.UUID | None,
    ) -> None:
        """Stage one confirmed v2 draft in the caller's transaction/savepoint."""
        self._session.add(
            ObservationRow(
                id=observation_id,
                timestamp=timestamp,
                place=draft.place,
                obs_date=draft.obs_date,
                time_of_day=draft.time_of_day,
                species=draft.species_label,
                species_id=draft.species_id,
                session_id=session_id,
                count=draft.count,
                behavior=draft.behavior,
                raw_note=draft.raw_note,
                confidence=draft.confidence,
                source=draft.source,
                flags=list(draft.flags),
                user_id=user_id,
            )
        )
        self._session.flush()


class SpeciesRepository:
    """Read and idempotently update the provider-backed species catalog."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(
        self,
        entries: list[SpeciesCatalogEntry],
        batch_size: int = 500,
    ) -> list[SpeciesRecord]:
        """Bulk upsert catalog rows while preserving IDs on provider updates."""
        records_by_key: dict[tuple[str, str], SpeciesRecord] = {}
        for start in range(0, len(entries), batch_size):
            batch = entries[start : start + batch_size]
            values = [
                {
                    "id": uuid.uuid4(),
                    "taxonomy_source": entry.taxonomy_source,
                    "taxonomy_key": entry.taxonomy_key,
                    "canonical_chinese_name": entry.canonical_chinese_name,
                    "scientific_name": entry.scientific_name,
                    "aliases": list(entry.aliases),
                }
                for entry in batch
            ]
            statement = insert(SpeciesRow).values(values)
            statement = statement.on_conflict_do_update(
                constraint="uq_species_source_key",
                set_={
                    "canonical_chinese_name": statement.excluded.canonical_chinese_name,
                    "scientific_name": statement.excluded.scientific_name,
                    "aliases": statement.excluded.aliases,
                },
            ).returning(SpeciesRow)
            rows = self._session.scalars(statement).all()
            for row in rows:
                record = _to_species(row)
                records_by_key[
                    (record.taxonomy_source, record.taxonomy_key)
                ] = record

        return [
            records_by_key[(entry.taxonomy_source, entry.taxonomy_key)]
            for entry in entries
        ]

    def list_all(self) -> list[SpeciesRecord]:
        rows = self._session.scalars(
            select(SpeciesRow).order_by(
                SpeciesRow.taxonomy_source, SpeciesRow.taxonomy_key
            )
        ).all()
        return [_to_species(row) for row in rows]


class SessionRepository:
    """Create and finalize one confirmed batch audit row."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def create(
        self,
        *,
        session_id: uuid.UUID,
        created_at: datetime,
        raw_text: str,
        user_id: uuid.UUID | None,
    ) -> SessionRow:
        row = SessionRow(
            id=session_id,
            created_at=created_at,
            raw_text=raw_text,
            status="processing",
            user_id=user_id,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def set_status(self, row: SessionRow, status: str) -> None:
        row.status = status
        self._session.flush()


class PhotoRepository:
    """Persist uploaded-file metadata and manage confirmed ownership links."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def add(self, metadata: PhotoMetadataInput) -> None:
        candidate = metadata.candidate
        self._session.add(
            PhotoRow(
                id=metadata.photo_id,
                content_hash=metadata.content_hash,
                storage_path=metadata.storage_path,
                original_filename=metadata.original_filename,
                mime_type=metadata.mime_type,
                size_bytes=metadata.size_bytes,
                species_label=(candidate.species_label if candidate else None),
                scientific_name=(candidate.scientific_name if candidate else None),
                confidence=(candidate.confidence if candidate else None),
                provider_candidate_id=(
                    candidate.provider_candidate_id if candidate else None
                ),
            )
        )
        self._session.flush()

    def lock_many(self, photo_ids: list[uuid.UUID]) -> dict[uuid.UUID, PhotoRow]:
        if not photo_ids:
            return {}
        rows = self._session.scalars(
            select(PhotoRow)
            .where(PhotoRow.id.in_(photo_ids))
            .with_for_update()
        ).all()
        return {row.id: row for row in rows}

    def assign_session(
        self, rows: list[PhotoRow], session_id: uuid.UUID
    ) -> None:
        for row in rows:
            row.session_id = session_id
        self._session.flush()

    def assign_observation(
        self, rows: list[PhotoRow], observation_id: uuid.UUID
    ) -> None:
        for row in rows:
            row.observation_id = observation_id
        self._session.flush()


def _apply_date_range(
    statement: Select[tuple[ObservationRow]],
    date_range: str | None,
) -> Select[tuple[ObservationRow]]:
    """Apply the legacy `start..end` lexicographic date filter."""
    if date_range is None or ".." not in date_range:
        return statement
    start, _, end = date_range.partition("..")
    start, end = start.strip(), end.strip()
    statement = statement.where(ObservationRow.obs_date.is_not(None))
    if start:
        statement = statement.where(ObservationRow.obs_date >= start)
    if end:
        statement = statement.where(ObservationRow.obs_date <= end)
    return statement


def _parse_timestamp(value: str) -> datetime:
    """Parse the ISO timestamp generated by AppendLogTool."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _to_observation(row: ObservationRow) -> Observation:
    """Map a database row back to the provider-neutral pydantic model."""
    return Observation(
        id=str(row.id),
        timestamp=row.timestamp.isoformat(),
        place=row.place,
        obs_date=row.obs_date,
        time_of_day=row.time_of_day,
        species=row.species,
        count=row.count,
        behavior=row.behavior,
        raw_note=row.raw_note,
        confidence=row.confidence,
        source=row.source,
        flags=list(row.flags),
    )


def _to_species(row: SpeciesRow) -> SpeciesRecord:
    return SpeciesRecord(
        id=row.id,
        taxonomy_source=row.taxonomy_source,
        taxonomy_key=row.taxonomy_key,
        canonical_chinese_name=row.canonical_chinese_name,
        scientific_name=row.scientific_name,
        aliases=list(row.aliases),
    )
