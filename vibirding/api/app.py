"""FastAPI application factory for v2 media and parse-preview endpoints."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.staticfiles import StaticFiles

from .. import config
from ..db.session import SessionFactory, build_session_factory
from ..llm.deepseek_client import DeepSeekClient, DeepSeekError
from ..schemas import MediaUploadResponse, ParseRequest, ParseResult
from ..services.assembly import ParseAssemblyError, ParseAssemblyService
from ..services.matching import DryRunMatchingService
from ..services.media import (
    MediaStorageService,
    MediaTooLargeError,
    MediaValidationError,
    UnsupportedMediaTypeError,
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


def create_app(
    session_factory: SessionFactory | None = None,
    media_dir: Path | None = None,
    parse_service: _ParsesPreview | None = None,
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
