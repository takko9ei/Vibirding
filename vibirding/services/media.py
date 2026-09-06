"""Content-addressed JPEG storage backed by the photos table."""

from __future__ import annotations

import hashlib
import os
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO

from .. import config
from ..db.repository import PhotoRepository
from ..db.session import SessionFactory
from ..schemas import PhotoMetadataInput, StoredPhoto


class MediaValidationError(ValueError):
    """The uploaded bytes cannot be accepted as a media object."""


class UnsupportedMediaTypeError(MediaValidationError):
    """The declared MIME type is not supported by the current pipeline."""


class MediaTooLargeError(MediaValidationError):
    """The upload exceeded the configured byte limit while streaming."""


class MediaStorageService:
    """Validate, hash, store, and deduplicate one JPEG upload."""

    _CHUNK_BYTES = 64 * 1024

    def __init__(
        self,
        session_factory: SessionFactory,
        media_dir: Path,
        *,
        max_upload_bytes: int = config.MEDIA_MAX_UPLOAD_BYTES,
        id_factory: Callable[[], uuid.UUID] = uuid.uuid4,
    ) -> None:
        self._session_factory = session_factory
        self._media_dir = media_dir.resolve()
        self._max_upload_bytes = max_upload_bytes
        self._id_factory = id_factory

    def store(
        self,
        stream: BinaryIO,
        original_filename: str,
        mime_type: str,
    ) -> StoredPhoto:
        normalized_mime = self._normalize_mime(mime_type)
        safe_filename = self._safe_filename(original_filename)
        self._media_dir.mkdir(parents=True, exist_ok=True)
        temporary_path = self._media_dir / f".upload-{uuid.uuid4().hex}.tmp"

        try:
            content_hash, size_bytes, prefix = self._copy_and_hash(
                stream, temporary_path
            )
            if size_bytes == 0:
                raise MediaValidationError("上传文件为空。")
            if not prefix.startswith(b"\xff\xd8\xff"):
                raise MediaValidationError("文件内容不是有效的 JPEG。")

            final_path = self._media_dir / f"{content_hash}.jpg"
            os.replace(temporary_path, final_path)

            metadata = PhotoMetadataInput(
                photo_id=self._id_factory(),
                content_hash=content_hash,
                storage_path=str(final_path),
                original_filename=safe_filename,
                mime_type=normalized_mime,
                size_bytes=size_bytes,
            )
            with self._session_factory.begin() as session:
                row, created = PhotoRepository(session).create_or_get(metadata)

            return StoredPhoto(
                photo_id=row.id,
                content_hash=row.content_hash,
                storage_path=row.storage_path,
                original_filename=row.original_filename,
                mime_type=row.mime_type,
                size_bytes=row.size_bytes,
                created=created,
            )
        finally:
            temporary_path.unlink(missing_ok=True)

    def _copy_and_hash(
        self,
        stream: BinaryIO,
        destination: Path,
    ) -> tuple[str, int, bytes]:
        digest = hashlib.sha256()
        size_bytes = 0
        prefix = bytearray()
        with destination.open("xb") as target:
            while chunk := stream.read(self._CHUNK_BYTES):
                size_bytes += len(chunk)
                if size_bytes > self._max_upload_bytes:
                    raise MediaTooLargeError(
                        f"图片超过 {self._max_upload_bytes} 字节上限。"
                    )
                if len(prefix) < 3:
                    prefix.extend(chunk[: 3 - len(prefix)])
                digest.update(chunk)
                target.write(chunk)
        return digest.hexdigest(), size_bytes, bytes(prefix)

    @staticmethod
    def _normalize_mime(mime_type: str) -> str:
        normalized = mime_type.strip().lower()
        if normalized == "image/jpg":
            normalized = "image/jpeg"
        if normalized != "image/jpeg":
            raise UnsupportedMediaTypeError("当前只支持 JPEG 图片。")
        return normalized

    @staticmethod
    def _safe_filename(original_filename: str) -> str:
        safe = original_filename.strip().replace("\\", "/").rsplit("/", 1)[-1]
        if not safe:
            raise MediaValidationError("图片缺少原始文件名。")
        return safe
