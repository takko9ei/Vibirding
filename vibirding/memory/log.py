"""Compatibility facade for the PostgreSQL observation repository.

The v1-facing contract intentionally stays tiny and unchanged:

    log.append(obs: Observation) -> None
    log.query(place=None, species=None, date_range=None) -> list[Observation]

Persistence, filtering, and row mapping live in `db.repository`; this module only
owns one transaction per append and one read session per query.
"""

from __future__ import annotations

from sqlalchemy.orm import Session, sessionmaker

from ..db.repository import ObservationRepository
from ..db.session import build_session_factory
from ..schemas import Observation


class Log:
    """The v1 Log API backed by an injectable PostgreSQL session factory."""

    def __init__(self, session_factory: sessionmaker[Session] | None = None) -> None:
        self._session_factory = session_factory or build_session_factory()

    def append(self, obs: Observation) -> None:
        """Insert one observation atomically."""
        with self._session_factory.begin() as session:
            ObservationRepository(session).append(obs)

    def query(
        self,
        place: str | None = None,
        species: str | None = None,
        date_range: str | None = None,
    ) -> list[Observation]:
        """Return rows matching the legacy filters in insertion order."""
        with self._session_factory() as session:
            return ObservationRepository(session).query(place, species, date_range)
