"""FastAPI application factory and the slice 3.1 media endpoint."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.staticfiles import StaticFiles

from .. import config
from ..db.session import SessionFactory, build_session_factory
from ..schemas import MediaUploadResponse
from ..services.media import (
    MediaStorageService,
    MediaTooLargeError,
    MediaValidationError,
    UnsupportedMediaTypeError,
)


def create_app(
    session_factory: SessionFactory | None = None,
    media_dir: Path | None = None,
) -> FastAPI:
    """Build an injectable application without opening a database connection."""
    resolved_media_dir = (media_dir or config.MEDIA_DIR).resolve()
    resolved_media_dir.mkdir(parents=True, exist_ok=True)
    storage = MediaStorageService(
        session_factory or build_session_factory(),
        resolved_media_dir,
    )
    app = FastAPI(title="Vibirding API", version="2.0.0")

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

    app.mount(
        "/media",
        StaticFiles(directory=resolved_media_dir),
        name="media",
    )
    return app
