"""FastAPI factory for v2 media, parse, and observation management."""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import (
    FastAPI,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from fastapi.staticfiles import StaticFiles

from .. import config
from ..db.session import SessionFactory, build_session_factory
from ..llm.deepseek_client import DeepSeekClient, DeepSeekError
from ..schemas import (
    BatchWriteResult,
    ConfirmedBatch,
    MediaUploadResponse,
    ObservationCreateRequest,
    ObservationDetail,
    ObservationListResponse,
    ObservationUpdateRequest,
    ParseRequest,
    ParseResult,
)
from ..services.assembly import ParseAssemblyError, ParseAssemblyService
from ..services.batch import (
    BatchConfirmationError,
    BatchMediaConflictError,
    BatchMediaNotFoundError,
    BatchWriteService,
)
from ..services.matching import DryRunMatchingService
from ..services.media import (
    MediaStorageService,
    MediaTooLargeError,
    MediaValidationError,
    UnsupportedMediaTypeError,
)
from ..services.observations import (
    ObservationDeleteService,
    ObservationEditService,
    ObservationNotFoundError,
    ObservationQueryError,
    ObservationReadService,
    ObservationSpeciesNotFoundError,
)
from ..services.parse import (
    PhotoPreprocessError,
    PhotoPreprocessService,
    TextSplitError,
    TextSplitService,
)
from ..services.preview import (
    ParseMediaNotFoundError,
    ParsePreviewError,
    ParsePreviewService,
)
from ..services.taxonomy import TaxonomyService
from ..tools.bird_id import BirdIdTool


class _ParsesPreview(Protocol):
    def parse(self, text: str, media_ids: list[UUID]) -> ParseResult: ...


class _ConfirmsBatch(Protocol):
    def confirm(self, batch: ConfirmedBatch) -> BatchWriteResult: ...


def create_app(
    session_factory: SessionFactory | None = None,
    media_dir: Path | None = None,
    parse_service: _ParsesPreview | None = None,
    batch_service: _ConfirmsBatch | None = None,
) -> FastAPI:
    """Build an injectable application without opening a database connection."""
    resolved_session_factory = session_factory or build_session_factory()
    resolved_media_dir = (media_dir or config.MEDIA_DIR).resolve()
    resolved_media_dir.mkdir(parents=True, exist_ok=True)
    storage = MediaStorageService(
        resolved_session_factory,
        resolved_media_dir,
    )
    active_parse_service = parse_service
    active_batch_service = batch_service or BatchWriteService(
        resolved_session_factory
    )
    observation_reader = ObservationReadService(resolved_session_factory)
    observation_editor = ObservationEditService(resolved_session_factory)
    observation_deleter = ObservationDeleteService(resolved_session_factory)
    app = FastAPI(title="Vibirding API", version="2.0.0")

    def get_parse_service() -> _ParsesPreview:
        nonlocal active_parse_service
        if active_parse_service is None:
            active_parse_service = _build_parse_service(resolved_session_factory)
        return active_parse_service

    @app.post(
        "/api/media",
        response_model=MediaUploadResponse,
        status_code=status.HTTP_201_CREATED,
        responses={
            status.HTTP_200_OK: {"model": MediaUploadResponse},
            status.HTTP_400_BAD_REQUEST: {"description": "Empty or invalid JPEG"},
            status.HTTP_413_CONTENT_TOO_LARGE: {"description": "File too large"},
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE: {
                "description": "Unsupported media type"
            },
        },
    )
    def upload_media(
        response: Response,
        photo: Annotated[UploadFile, File(description="JPEG bird photo")],
    ) -> MediaUploadResponse:
        try:
            stored = storage.store(
                photo.file,
                photo.filename or "",
                photo.content_type or "",
            )
        except UnsupportedMediaTypeError as exc:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail=str(exc),
            ) from exc
        except MediaTooLargeError as exc:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail=str(exc),
            ) from exc
        except MediaValidationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

        response.status_code = (
            status.HTTP_201_CREATED if stored.created else status.HTTP_200_OK
        )
        return MediaUploadResponse(
            media_id=stored.photo_id,
            hash=stored.content_hash,
            url=f"/media/{stored.content_hash}.jpg",
        )

    @app.post(
        "/api/parse",
        response_model=ParseResult,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Media not found"},
            status.HTTP_502_BAD_GATEWAY: {
                "description": "Text model or structured response failed"
            },
        },
    )
    def parse_preview(request: ParseRequest) -> ParseResult:
        try:
            return get_parse_service().parse(request.text, request.media_ids)
        except ParseMediaNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except (TextSplitError, DeepSeekError) as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=str(exc),
            ) from exc
        except (
            ParsePreviewError,
            PhotoPreprocessError,
            ParseAssemblyError,
        ) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.post(
        "/api/observations",
        response_model=BatchWriteResult,
        status_code=status.HTTP_201_CREATED,
        responses={
            status.HTTP_400_BAD_REQUEST: {
                "description": "Batch was not explicitly or unambiguously confirmed"
            },
            status.HTTP_404_NOT_FOUND: {"description": "Media not found"},
            status.HTTP_409_CONFLICT: {
                "description": "Media already belongs to another session"
            },
        },
    )
    def create_observations(
        request: ObservationCreateRequest,
    ) -> BatchWriteResult:
        batch = ConfirmedBatch(
            raw_text=request.text,
            media_ids=request.media_ids,
            observations=request.observations,
            confirmed=request.confirmed,
        )
        try:
            return active_batch_service.confirm(batch)
        except BatchMediaNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        except BatchMediaConflictError as exc:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=str(exc),
            ) from exc
        except BatchConfirmationError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/observations",
        response_model=ObservationListResponse,
    )
    def list_observations(
        limit: Annotated[int, Query(ge=1, le=100)] = 20,
        place: str | None = None,
        species: str | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> ObservationListResponse:
        try:
            return observation_reader.list_observations(
                limit=limit,
                place=place,
                species=species,
                date_from=date_from,
                date_to=date_to,
            )
        except ObservationQueryError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(exc),
            ) from exc

    @app.get(
        "/api/observations/{observation_id}",
        response_model=ObservationDetail,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Observation not found"}
        },
    )
    def get_observation(observation_id: UUID) -> ObservationDetail:
        try:
            return observation_reader.get_observation(observation_id)
        except ObservationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.patch(
        "/api/observations/{observation_id}",
        response_model=ObservationDetail,
        responses={
            status.HTTP_404_NOT_FOUND: {
                "description": "Observation or species not found"
            }
        },
    )
    def update_observation(
        observation_id: UUID,
        request: ObservationUpdateRequest,
    ) -> ObservationDetail:
        try:
            return observation_editor.update_observation(
                observation_id,
                request,
            )
        except (ObservationNotFoundError, ObservationSpeciesNotFoundError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc

    @app.delete(
        "/api/observations/{observation_id}",
        status_code=status.HTTP_204_NO_CONTENT,
        response_class=Response,
        responses={
            status.HTTP_404_NOT_FOUND: {"description": "Observation not found"}
        },
    )
    def delete_observation(observation_id: UUID) -> Response:
        try:
            observation_deleter.delete_observation(observation_id)
        except ObservationNotFoundError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=str(exc),
            ) from exc
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    app.mount(
        "/media",
        StaticFiles(directory=resolved_media_dir),
        name="media",
    )
    return app


def _build_parse_service(session_factory: SessionFactory) -> ParsePreviewService:
    """Lazily compose real providers so media upload starts without AI keys."""
    taxonomy = TaxonomyService(session_factory)
    matching = DryRunMatchingService(taxonomy)
    return ParsePreviewService(
        session_factory=session_factory,
        text_splitter=TextSplitService(DeepSeekClient()),
        photo_preprocessor=PhotoPreprocessService(BirdIdTool()),
        assembly=ParseAssemblyService(matching),
    )
