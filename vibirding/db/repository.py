"""Data-access semantics for observations."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..schemas import Observation, SpeciesCatalogEntry, SpeciesRecord
from .models import ObservationRow, SpeciesRow


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
