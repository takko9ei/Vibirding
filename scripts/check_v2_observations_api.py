#!/usr/bin/env python
"""HTTP verification for v2 slice 3.3 confirmed batch persistence."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

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
from vibirding.schemas import SpeciesCatalogEntry  # noqa: E402
from vibirding.services.batch import BatchWriteService  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def row_count(session_factory, model) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


def draft(
    draft_id: str,
    species_id: UUID | None,
    photo_ids: list[str] | None = None,
) -> dict:
    return {
        "client_draft_id": draft_id,
        "place": "井之头公园",
        "obs_date": "2026-09-06",
        "time_of_day": "上午",
        "count": 3,
        "behavior": "在树上活动",
        "raw_note": f"{draft_id} 原文",
        "species_label": "灰喜鹊",
        "species_id": str(species_id) if species_id is not None else None,
        "confidence": 95,
        "source": "user",
        "flags": [],
        "photo_ids": photo_ids or [],
        "needs_confirmation": False,
    }


fixed_now = datetime(2026, 9, 6, 10, 30, tzinfo=timezone.utc)

with TemporaryDirectory(prefix="vibirding-observations-api-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("observations_api") as session_factory:
        species = TaxonomyService(session_factory).import_entries(
            [
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="azwmag1",
                    canonical_chinese_name="灰喜鹊",
                    scientific_name="Cyanopica cyanus",
                )
            ]
        )[0]
        batch_service = BatchWriteService(
            session_factory,
            now=lambda: fixed_now,
        )
        app = create_app(
            session_factory=session_factory,
            media_dir=media_dir,
            batch_service=batch_service,
        )

        with TestClient(app) as client:
            def upload(number: int) -> str:
                content = (
                    b"\xff\xd8\xff\xe0"
                    + f"observation-api-{number}".encode()
                    + b"\xff\xd9"
                )
                response = client.post(
                    "/api/media",
                    files={
                        "photo": (
                            f"bird-{number}.jpg",
                            content,
                            "image/jpeg",
                        )
                    },
                )
                check(f"测试媒体 {number} 上传成功", response.status_code == 201)
                return response.json()["media_id"]

            media_ids = [upload(number) for number in range(1, 7)]

            unconfirmed = client.post(
                "/api/observations",
                json={
                    "text": "尚未确认",
                    "media_ids": [media_ids[0]],
                    "observations": [
                        draft("draft-unconfirmed", species.id, [media_ids[0]])
                    ],
                    "confirmed": False,
                },
            )
            check("confirmed=false 返回 400", unconfirmed.status_code == 400)
            check("未确认错误可读", bool(unconfirmed.json().get("detail")))
            check("未确认不创建 session", row_count(session_factory, SessionRow) == 0)
            check(
                "未确认不创建 observation",
                row_count(session_factory, ObservationRow) == 0,
            )
            with session_factory() as session:
                check(
                    "未确认不认领媒体",
                    session.get(PhotoRow, UUID(media_ids[0])).session_id is None,
                )

            completed = client.post(
                "/api/observations",
                json={
                    "text": "  完整成功的原始笔记\n",
                    "media_ids": media_ids[:2],
                    "observations": [
                        draft("draft-1", species.id, media_ids[:2]),
                        draft("draft-2", species.id),
                    ],
                    "confirmed": True,
                },
            )
            completed_payload = completed.json()
            check("完整成功返回 201", completed.status_code == 201, completed.text)
            check(
                "成功响应字段固定",
                set(completed_payload) == {"session_id", "created", "failed"},
            )
            check("完整成功 created 两条", len(completed_payload["created"]) == 2)
            check("完整成功 failed 仍存在且为空", completed_payload["failed"] == [])
            with session_factory() as session:
                session_row = session.get(
                    SessionRow,
                    UUID(completed_payload["session_id"]),
                )
                rows = session.scalars(
                    select(ObservationRow).where(
                        ObservationRow.session_id == session_row.id
                    )
                ).all()
                first_observation_id = UUID(
                    completed_payload["created"][0]["observation_id"]
                )
                photos = [
                    session.get(PhotoRow, UUID(media_id))
                    for media_id in media_ids[:2]
                ]
                check("成功 session 状态 completed", session_row.status == "completed")
                check(
                    "session 原样保存整篇文本",
                    session_row.raw_text == "  完整成功的原始笔记\n",
                )
                check("session 使用注入的 UTC 时间", session_row.created_at == fixed_now)
                check("成功创建两条 observation", len(rows) == 2)
                check("HTTP 不允许伪造 user_id", all(row.user_id is None for row in rows))
                check(
                    "草稿字段写入 observation",
                    rows[0].place == "井之头公园"
                    and rows[0].species_id == species.id
                    and rows[0].count == 3,
                )
                check(
                    "同一草稿多图关联正确",
                    all(row.observation_id == first_observation_id for row in photos),
                )
                check(
                    "成功媒体全部归属同一 session",
                    all(row.session_id == session_row.id for row in photos),
                )

            unknown_species_id = uuid4()
            partial = client.post(
                "/api/observations",
                json={
                    "text": "部分成功",
                    "media_ids": media_ids[2:4],
                    "observations": [
                        draft("draft-3", species.id, [media_ids[2]]),
                        draft(
                            "draft-4",
                            unknown_species_id,
                            [media_ids[3]],
                        ),
                    ],
                    "confirmed": True,
                },
            )
            partial_payload = partial.json()
            check("部分成功仍返回 201", partial.status_code == 201, partial.text)
            check(
                "部分成功同时返回 created/failed",
                len(partial_payload["created"]) == 1
                and len(partial_payload["failed"]) == 1,
            )
            check(
                "失败精确对应原草稿",
                partial_payload["failed"][0]["client_draft_id"] == "draft-4"
                and "species_id" in partial_payload["failed"][0]["reason"],
            )
            with session_factory() as session:
                partial_session = session.get(
                    SessionRow,
                    UUID(partial_payload["session_id"]),
                )
                failed_photo = session.get(PhotoRow, UUID(media_ids[3]))
                check("部分成功 session 状态 partial", partial_session.status == "partial")
                check(
                    "失败草稿媒体留在批次但不关联 observation",
                    failed_photo.session_id == partial_session.id
                    and failed_photo.observation_id is None,
                )

            all_failed = client.post(
                "/api/observations",
                json={
                    "text": "全部失败",
                    "media_ids": [media_ids[4]],
                    "observations": [
                        draft(
                            "draft-5",
                            uuid4(),
                            [media_ids[4]],
                        )
                    ],
                    "confirmed": True,
                },
            )
            all_failed_payload = all_failed.json()
            check("全部草稿失败仍返回 201", all_failed.status_code == 201)
            check(
                "全部失败仍同时返回两个列表",
                all_failed_payload["created"] == []
                and len(all_failed_payload["failed"]) == 1,
            )
            with session_factory() as session:
                check(
                    "全部失败仍保存 failed session",
                    session.get(
                        SessionRow,
                        UUID(all_failed_payload["session_id"]),
                    ).status
                    == "failed",
                )

            photo_only = client.post(
                "/api/observations",
                json={
                    "text": "",
                    "media_ids": [media_ids[5]],
                    "observations": [
                        draft("photo-draft-1", species.id, [media_ids[5]])
                    ],
                    "confirmed": True,
                },
            )
            photo_only_payload = photo_only.json()
            check("纯照片确认可以返回 201", photo_only.status_code == 201)
            with session_factory() as session:
                photo_session = session.get(
                    SessionRow,
                    UUID(photo_only_payload["session_id"]),
                )
                check("纯照片 session 如实保存空原文", photo_session.raw_text == "")

            text_only = client.post(
                "/api/observations",
                json={
                    "text": "纯文本记录",
                    "media_ids": [],
                    "observations": [draft("draft-text", species.id)],
                    "confirmed": True,
                },
            )
            check("纯文本确认可以返回 201", text_only.status_code == 201)

            sessions_before_errors = row_count(session_factory, SessionRow)
            observations_before_errors = row_count(
                session_factory,
                ObservationRow,
            )
            unknown_media_id = str(uuid4())
            unknown_media = client.post(
                "/api/observations",
                json={
                    "text": "未知媒体",
                    "media_ids": [unknown_media_id],
                    "observations": [draft("draft-unknown", species.id)],
                    "confirmed": True,
                },
            )
            check("未知媒体返回 404", unknown_media.status_code == 404)
            check(
                "404 包含未知 ID",
                unknown_media_id in unknown_media.json()["detail"],
            )

            owned_media = client.post(
                "/api/observations",
                json={
                    "text": "重复使用媒体",
                    "media_ids": [media_ids[0]],
                    "observations": [draft("draft-owned", species.id)],
                    "confirmed": True,
                },
            )
            check("已认领媒体返回 409", owned_media.status_code == 409)

            duplicate_media = client.post(
                "/api/observations",
                json={
                    "text": "重复媒体",
                    "media_ids": [media_ids[0], media_ids[0]],
                    "observations": [draft("draft-duplicate-media", species.id)],
                    "confirmed": True,
                },
            )
            check("批次内重复媒体返回 400", duplicate_media.status_code == 400)

            duplicate_drafts = client.post(
                "/api/observations",
                json={
                    "text": "重复草稿",
                    "media_ids": [],
                    "observations": [
                        draft("same-draft", species.id),
                        draft("same-draft", species.id),
                    ],
                    "confirmed": True,
                },
            )
            check("重复草稿 ID 返回 400", duplicate_drafts.status_code == 400)
            check(
                "所有批次级错误均无写入",
                row_count(session_factory, SessionRow) == sessions_before_errors
                and row_count(session_factory, ObservationRow)
                == observations_before_errors,
            )

            invalid_requests = [
                (
                    "confirmed 字符串返回 422",
                    {
                        "text": "记录",
                        "media_ids": [],
                        "observations": [draft("invalid-bool", species.id)],
                        "confirmed": "yes",
                    },
                ),
                (
                    "缺少 confirmed 返回 422",
                    {
                        "text": "记录",
                        "media_ids": [],
                        "observations": [draft("missing-confirm", species.id)],
                    },
                ),
                (
                    "空 observations 返回 422",
                    {
                        "text": "记录",
                        "media_ids": [],
                        "observations": [],
                        "confirmed": True,
                    },
                ),
                (
                    "文本和媒体同时为空返回 422",
                    {
                        "text": "  ",
                        "media_ids": [],
                        "observations": [draft("empty-input", species.id)],
                        "confirmed": True,
                    },
                ),
                (
                    "公开接口拒绝 user_id 返回 422",
                    {
                        "text": "记录",
                        "media_ids": [],
                        "observations": [draft("fake-user", species.id)],
                        "confirmed": True,
                        "user_id": str(uuid4()),
                    },
                ),
            ]
            for name, body in invalid_requests:
                response = client.post("/api/observations", json=body)
                check(name, response.status_code == 422, response.text)
            check(
                "422 请求全部零写入",
                row_count(session_factory, SessionRow) == sessions_before_errors
                and row_count(session_factory, ObservationRow)
                == observations_before_errors,
            )

        with session_factory() as session:
            final_sessions = session.scalar(
                select(func.count()).select_from(SessionRow)
            )
            final_observations = session.scalar(
                select(func.count()).select_from(ObservationRow)
            )
            final_photos = session.scalar(
                select(func.count()).select_from(PhotoRow)
            )
        check("只创建五个已确认 session", final_sessions == 5, str(final_sessions))
        check("成功草稿共创建五条 observation", final_observations == 5)
        check("六条上传媒体均保留", final_photos == 6)
        check("确认写入不删除媒体文件", len(list(media_dir.glob("*.jpg"))) == 6)


def main() -> int:
    print("=" * 72)
    print("v2 3.3 FastAPI 批量确认写入验证 — HTTP 客户端、临时 schema/目录")
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
