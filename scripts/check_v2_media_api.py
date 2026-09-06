#!/usr/bin/env python
"""HTTP verification for v2 slice 3.1 FastAPI media upload."""

from __future__ import annotations

import hashlib
import io
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.api.app import create_app  # noqa: E402
from vibirding.db.models import ObservationRow, PhotoRow, SessionRow  # noqa: E402
from vibirding.schemas import MediaUploadResponse, StoredPhoto  # noqa: E402
from vibirding.services.media import MediaStorageService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


class RecordingStream(io.BytesIO):
    """Record requested read sizes to prove the service streams in chunks."""

    def __init__(self, value: bytes) -> None:
        super().__init__(value)
        self.read_sizes: list[int] = []

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return super().read(size)


jpeg_one = b"\xff\xd8\xff\xe0" + b"vibirding-jpeg-one" + b"\xff\xd9"
jpeg_two = b"\xff\xd8\xff\xe1" + b"vibirding-jpeg-two" + b"\xff\xd9"
hash_one = hashlib.sha256(jpeg_one).hexdigest()


with TemporaryDirectory(prefix="vibirding-media-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("media_api") as session_factory:
        app = create_app(session_factory=session_factory, media_dir=media_dir)
        with TestClient(app) as client:
            created = client.post(
                "/api/media",
                files={"photo": ("../bird-one.jpg", jpeg_one, "image/jpeg")},
            )
            created_json = created.json()
            check("首次上传返回 201", created.status_code == 201, created.text)
            check("响应字段严格为 media_id/hash/url", set(created_json) == {"media_id", "hash", "url"})
            check("media_id 是 UUID", UUID(created_json["media_id"]).version == 4)
            check("响应 hash 等于真实 SHA-256", created_json["hash"] == hash_one)
            check("URL 使用哈希文件名", created_json["url"] == f"/media/{hash_one}.jpg")

            stored_path = media_dir / f"{hash_one}.jpg"
            check("文件按哈希名保存", stored_path.is_file())
            check("保存字节与上传完全一致", stored_path.read_bytes() == jpeg_one)

            fetched = client.get(created_json["url"])
            check("返回 URL 可直接读取图片", fetched.status_code == 200 and fetched.content == jpeg_one)
            check("静态图片响应 MIME 正确", fetched.headers["content-type"].startswith("image/jpeg"))

            with session_factory() as session:
                first_row = session.scalar(
                    select(PhotoRow).where(PhotoRow.content_hash == hash_one)
                )
            check("photos 元数据写入数据库", first_row is not None)
            check("数据库保存实际大小和规范 MIME", first_row.size_bytes == len(jpeg_one) and first_row.mime_type == "image/jpeg")
            check("原始文件名不含客户端目录", first_row.original_filename == "bird-one.jpg")
            check("上传阶段不伪造识别字段", first_row.species_id is None and first_row.species_label is None and first_row.confidence is None)

            duplicate = client.post(
                "/api/media",
                files={"photo": ("same-bytes.jpg", jpeg_one, "image/jpeg")},
            )
            check("相同内容重复上传返回 200", duplicate.status_code == 200, duplicate.text)
            check("重复内容复用相同响应标识", duplicate.json() == created_json)

            alias_mime = client.post(
                "/api/media",
                files={"photo": ("bird-two.jpg", jpeg_two, "image/jpg")},
            )
            check("image/jpg 兼容并规范化", alias_mime.status_code == 201, alias_mime.text)

            before_failure_files = sorted(path.name for path in media_dir.iterdir())
            invalid_cases = [
                ("空文件返回 400", ("empty.jpg", b"", "image/jpeg"), 400),
                ("伪 JPEG 返回 400", ("fake.jpg", b"not-a-jpeg", "image/jpeg"), 400),
                ("非 JPEG MIME 返回 415", ("bird.png", jpeg_one, "image/png"), 415),
                (
                    "超过 2 MiB 返回 413",
                    ("large.jpg", b"\xff\xd8\xff" + b"x" * (2 * 1024 * 1024), "image/jpeg"),
                    413,
                ),
            ]
            for name, upload, expected_status in invalid_cases:
                response = client.post("/api/media", files={"photo": upload})
                check(name, response.status_code == expected_status, response.text)
                check(f"{name}包含可读错误", bool(response.json().get("detail")))

            missing = client.post("/api/media")
            check("缺少 multipart photo 返回 422", missing.status_code == 422)
            check("失败请求不增加媒体文件", sorted(path.name for path in media_dir.iterdir()) == before_failure_files)
            check("失败请求不遗留临时文件", not list(media_dir.glob(".upload-*.tmp")))

            recording_stream = RecordingStream(jpeg_one)
            reused = MediaStorageService(session_factory, media_dir).store(
                recording_stream,
                "recording.jpg",
                "image/jpeg",
            )
            check("服务返回正式 StoredPhoto", isinstance(reused, StoredPhoto))
            check("服务确实按固定块读取", bool(recording_stream.read_sizes) and set(recording_stream.read_sizes) == {64 * 1024})
            check("直接服务调用仍按哈希复用", reused.created is False and reused.photo_id == UUID(created_json["media_id"]))

        with session_factory() as session:
            photo_count = session.scalar(select(func.count()).select_from(PhotoRow))
            observation_count = session.scalar(
                select(func.count()).select_from(ObservationRow)
            )
            session_count = session.scalar(select(func.count()).select_from(SessionRow))
        check("两种内容只创建两条 photos", photo_count == 2, str(photo_count))
        check("3.1 不写 observations/sessions", [observation_count, session_count] == [0, 0])
        check("两种内容只保存两个最终文件", len(list(media_dir.glob("*.jpg"))) == 2)


def main() -> int:
    print("=" * 72)
    print("v2 3.1 FastAPI 媒体上传验证 — HTTP 客户端、临时 schema/目录")
    print("=" * 72)
    passed = 0
    for name, ok, detail in _RESULTS:
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}"
            + (f" <- {detail}" if not ok and detail else "")
        )
        passed += ok
    print("-" * 72)
    print(f"通过 {passed}/{len(_RESULTS)}")
    return 0 if passed == len(_RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
