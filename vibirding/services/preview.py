"""Read-only orchestration for the complete v2 parse preview pipeline."""

from __future__ import annotations

from uuid import UUID

from ..db.repository import PhotoRepository
from ..db.session import SessionFactory
from ..schemas import ParseResult, PhotoInput
from .assembly import ParseAssemblyService
from .parse import PhotoPreprocessService, TextSplitService


class ParsePreviewError(ValueError):
    """The requested preview batch is not valid."""


class ParseMediaNotFoundError(ParsePreviewError):
    """One or more requested media IDs do not exist."""

    def __init__(self, media_ids: list[UUID]) -> None:
        self.media_ids = list(media_ids)
        shown = ", ".join(str(media_id) for media_id in media_ids)
        super().__init__(f"找不到以下媒体：{shown}")


class ParsePreviewService:
    """Compose text splitting, photo ID, taxonomy matching, and assembly."""

    def __init__(
        self,
        session_factory: SessionFactory,
        text_splitter: TextSplitService,
        photo_preprocessor: PhotoPreprocessService,
        assembly: ParseAssemblyService,
    ) -> None:
        self._session_factory = session_factory
        self._text_splitter = text_splitter
        self._photo_preprocessor = photo_preprocessor
        self._assembly = assembly

    def parse(self, text: str, media_ids: list[UUID]) -> ParseResult:
        """Build a preview while preserving media order and database state."""
        clean_text = text.strip()
        if not clean_text and not media_ids:
            raise ParsePreviewError("text and media_ids cannot both be empty")
        if len(set(media_ids)) != len(media_ids):
            raise ParsePreviewError("media_ids must be unique within a request")

        photo_inputs = self._load_photo_inputs(media_ids)
        drafts = self._text_splitter.split(clean_text) if clean_text else []
        identifications = self._photo_preprocessor.preprocess(photo_inputs)
        return self._assembly.assemble(drafts, identifications)

    def _load_photo_inputs(self, media_ids: list[UUID]) -> list[PhotoInput]:
        if not media_ids:
            return []
        with self._session_factory() as session:
            rows_by_id = PhotoRepository(session).get_many(media_ids)
            missing = [media_id for media_id in media_ids if media_id not in rows_by_id]
            if missing:
                raise ParseMediaNotFoundError(missing)
            return [
                PhotoInput(
                    photo_id=media_id,
                    image_path=rows_by_id[media_id].storage_path,
                )
                for media_id in media_ids
            ]
