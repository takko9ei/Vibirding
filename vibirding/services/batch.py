"""Explicitly confirmed, partially successful batch observation persistence."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db.models import PhotoRow, SpeciesRow
from ..db.repository import (
    ObservationRepository,
    PhotoRepository,
    SessionRepository,
)
from ..db.session import SessionFactory
from ..schemas import (
    BatchWriteResult,
    ConfirmedBatch,
    CreatedObservation,
    DraftObservation,
    FailedObservation,
)


class BatchConfirmationError(ValueError):
    """The request does not represent an explicit, unambiguous confirmation."""


class BatchMediaError(ValueError):
    """The confirmed batch refers to invalid or already-owned media."""


class _BatchItemError(ValueError):
    """One draft cannot be persisted, but sibling drafts may continue."""


class BatchWriteService:
    """Persist a confirmed session with savepoint-isolated observation writes."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._id_factory = id_factory
        self._now = now or (lambda: datetime.now(timezone.utc))

    def confirm(self, batch: ConfirmedBatch) -> BatchWriteResult:
        self._validate_confirmation(batch)

        created: list[CreatedObservation] = []
        failed: list[FailedObservation] = []
        session_id = self._id_factory()

        with self._session_factory.begin() as session:
            photo_repository = PhotoRepository(session)
            photos_by_id = photo_repository.lock_many(batch.media_ids)
            self._validate_media(batch.media_ids, photos_by_id)

            session_repository = SessionRepository(session)
            session_row = session_repository.create(
                session_id=session_id,
                created_at=self._now(),
                raw_text=batch.raw_text,
                user_id=batch.user_id,
            )
            photo_repository.assign_session(
                [photos_by_id[photo_id] for photo_id in batch.media_ids],
                session_id,
            )

            for draft in batch.observations:
                try:
                    observation_id = self._write_draft(
                        session,
                        draft,
                        batch,
                        photos_by_id,
                        session_id,
                    )
                except _BatchItemError as exc:
                    failed.append(
                        FailedObservation(
                            client_draft_id=draft.client_draft_id,
                            reason=str(exc),
                        )
                    )
                except IntegrityError:
                    failed.append(
                        FailedObservation(
                            client_draft_id=draft.client_draft_id,
                            reason="数据库约束拒绝了这条观测。",
                        )
                    )
                else:
                    created.append(
                        CreatedObservation(
                            client_draft_id=draft.client_draft_id,
                            observation_id=observation_id,
                        )
                    )

            status = self._status(len(created), len(failed))
            session_repository.set_status(session_row, status)

        return BatchWriteResult(
            session_id=session_id,
            created=created,
            failed=failed,
        )

    @staticmethod
    def _validate_confirmation(batch: ConfirmedBatch) -> None:
        if batch.confirmed is not True:
            raise BatchConfirmationError("batch must be explicitly confirmed")
        if len(set(batch.media_ids)) != len(batch.media_ids):
            raise BatchConfirmationError("media_ids must be unique within a batch")
        draft_ids = [draft.client_draft_id for draft in batch.observations]
        if len(set(draft_ids)) != len(draft_ids):
            raise BatchConfirmationError(
                "client_draft_id values must be unique within a batch"
            )

    @staticmethod
    def _validate_media(
        requested_ids: list[uuid.UUID],
        photos_by_id: dict[uuid.UUID, PhotoRow],
    ) -> None:
        missing = [photo_id for photo_id in requested_ids if photo_id not in photos_by_id]
        if missing:
            raise BatchMediaError(f"unknown media_ids: {', '.join(map(str, missing))}")
        owned = [
            photo_id
            for photo_id in requested_ids
            if photos_by_id[photo_id].session_id is not None
        ]
        if owned:
            raise BatchMediaError(
                f"media_ids already belong to a session: {', '.join(map(str, owned))}"
            )

    def _write_draft(
        self,
        session: Session,
        draft: DraftObservation,
        batch: ConfirmedBatch,
        photos_by_id: dict[uuid.UUID, PhotoRow],
        session_id: uuid.UUID,
    ) -> uuid.UUID:
        observation_id = self._id_factory()
        with session.begin_nested():
            photo_rows = self._validate_draft(
                session, draft, batch.media_ids, photos_by_id
            )
            ObservationRepository(session).append_draft(
                draft,
                observation_id=observation_id,
                timestamp=self._now(),
                session_id=session_id,
                user_id=batch.user_id,
            )
            PhotoRepository(session).assign_observation(
                photo_rows, observation_id
            )
        return observation_id

    @staticmethod
    def _validate_draft(
        session: Session,
        draft: DraftObservation,
        media_ids: list[uuid.UUID],
        photos_by_id: dict[uuid.UUID, PhotoRow],
    ) -> list[PhotoRow]:
        if len(set(draft.photo_ids)) != len(draft.photo_ids):
            raise _BatchItemError("草稿内含重复照片 ID。")
        outside = [photo_id for photo_id in draft.photo_ids if photo_id not in media_ids]
        if outside:
            raise _BatchItemError("草稿引用了本批次之外的照片。")

        rows = [photos_by_id[photo_id] for photo_id in draft.photo_ids]
        if any(row.observation_id is not None for row in rows):
            raise _BatchItemError("照片已被本批次中更早成功的草稿认领。")
        if draft.species_id is not None and session.get(
            SpeciesRow, draft.species_id
        ) is None:
            raise _BatchItemError("草稿引用的 species_id 不存在。")
        return rows

    @staticmethod
    def _status(created_count: int, failed_count: int) -> str:
        if created_count and failed_count:
            return "partial"
        if created_count:
            return "completed"
        return "failed"
