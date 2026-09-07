#!/usr/bin/env python
"""HTTP verification for v2 slice 3.6 observation deletion."""

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
from vibirding.db.models import (  # noqa: E402
    ObservationRow,
    PhotoRow,
    SessionRow,
    SpeciesRow,
)
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import Observation, SpeciesCatalogEntry  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def draft(
    draft_id: str,
    species_id: UUID,
    *,
    photo_ids: list[str] | None = None,
) -> dict:
    return {
        "client_draft_id": draft_id,
        "place": "井之头公园",
        "obs_date": "2026-09-07",
        "time_of_day": "上午",
        "count": 2,
        "behavior": "停在树上",
        "raw_note": f"{draft_id} 原文",
        "species_label": "灰喜鹊",
        "species_id": str(species_id),
        "confidence": 90,
        "source": "user",
        "flags": ["delete-fixture"],
        "photo_ids": photo_ids or [],
        "needs_confirmation": False,
    }


def table_counts(session_factory) -> tuple[int, int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
            session.scalar(select(func.count()).select_from(SpeciesRow)) or 0,
        )


with TemporaryDirectory(prefix="vibirding-observation-delete-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("observation_delete") as session_factory:
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
        app = create_app(session_factory=session_factory, media_dir=media_dir)

        with TestClient(app) as client:
            image_bytes = b"\xff\xd8\xff\xe0delete-api-photo\xff\xd9"
            upload = client.post(
                "/api/media",
                files={"photo": ("delete.jpg", image_bytes, "image/jpeg")},
            )
            check("fixture 照片上传成功", upload.status_code == 201, upload.text)
            media = upload.json()

            created = client.post(
                "/api/observations",
                json={
                    "text": "同一批次包含两条记录的原始笔记",
                    "media_ids": [media["media_id"]],
                    "observations": [
                        draft(
                            "delete-target",
                            species.id,
                            photo_ids=[media["media_id"]],
                        ),
                        draft("keep-target", species.id),
                    ],
                    "confirmed": True,
                },
            )
            check("v2 两条记录 fixture 写入成功", created.status_code == 201)
            payload = created.json()
            target_id = payload["created"][0]["observation_id"]
            keep_id = payload["created"][1]["observation_id"]
            session_id = payload["session_id"]

            legacy_id = uuid4()
            Log(session_factory).append(
                Observation(
                    id=str(legacy_id),
                    timestamp=datetime(
                        2026, 9, 7, 12, tzinfo=timezone.utc
                    ).isoformat(),
                    place="旧地点",
                    obs_date="2026-09-06",
                    species="旧式记录",
                    count=1,
                    raw_note="v1 单条原文",
                    source="user",
                )
            )

            baseline_counts = table_counts(session_factory)
            media_path = media_dir / f"{media['hash']}.jpg"
            baseline_file = media_path.read_bytes()
            with session_factory() as session:
                session_row = session.get(SessionRow, UUID(session_id))
                baseline_session = (
                    session_row.created_at,
                    session_row.raw_text,
                    session_row.status,
                    session_row.user_id,
                )

            deleted = client.delete(f"/api/observations/{target_id}")
            check("删除成功返回 204", deleted.status_code == 204, deleted.text)
            check("204 响应体为空", deleted.content == b"")
            check("204 不发送 JSON Content-Type", "content-type" not in deleted.headers)
            check("删除后详情返回 404", client.get(f"/api/observations/{target_id}").status_code == 404)
            check("删除后编辑返回 404", client.patch(f"/api/observations/{target_id}", json={"count": 9}).status_code == 404)
            check("重复删除返回 404", client.delete(f"/api/observations/{target_id}").status_code == 404)

            listed_ids = [
                item["observation_id"]
                for item in client.get("/api/observations").json()["items"]
            ]
            check("列表不再返回已删除记录", target_id not in listed_ids)
            check("同 session 的另一条记录仍存在", keep_id in listed_ids and client.get(f"/api/observations/{keep_id}").status_code == 200)
            check("v1 兼容记录仍存在", str(legacy_id) in listed_ids)

            with session_factory() as session:
                photo = session.get(PhotoRow, UUID(media["media_id"]))
                kept_observation = session.get(ObservationRow, UUID(keep_id))
                session_row = session.get(SessionRow, UUID(session_id))
                check("照片元数据仍存在", photo is not None)
                check("照片仅解除 observation 关联", photo.observation_id is None)
                check("照片仍属于原 session", photo.session_id == UUID(session_id))
                check("另一条记录仍属于原 session", kept_observation.session_id == UUID(session_id))
                check("session 审计字段完全不变", (
                    session_row.created_at,
                    session_row.raw_text,
                    session_row.status,
                    session_row.user_id,
                ) == baseline_session)

            check("媒体文件仍存在且字节不变", media_path.read_bytes() == baseline_file)
            media_response = client.get(media["url"])
            check("删除后媒体 URL 仍可读取", media_response.status_code == 200 and media_response.content == image_bytes)
            check("只减少一条 observation", table_counts(session_factory) == (baseline_counts[0] - 1, baseline_counts[1], baseline_counts[2], baseline_counts[3]))

            before_bad_requests = table_counts(session_factory)
            check("非法 observation UUID 返回 422", client.delete("/api/observations/not-a-uuid").status_code == 422)
            unknown_id = uuid4()
            unknown = client.delete(f"/api/observations/{unknown_id}")
            check("未知 observation 返回 404", unknown.status_code == 404 and str(unknown_id) in unknown.text)
            check("非法与未知请求不修改数据", table_counts(session_factory) == before_bad_requests)

            legacy_deleted = client.delete(f"/api/observations/{legacy_id}")
            check("无 session 的 v1 记录也可删除", legacy_deleted.status_code == 204 and legacy_deleted.content == b"")
            last_deleted = client.delete(f"/api/observations/{keep_id}")
            check("原 session 最后一条 observation 可删除", last_deleted.status_code == 204)
            check("全部 observation 删除后列表为空", client.get("/api/observations").json() == {"items": []})

            with session_factory() as session:
                session_row = session.get(SessionRow, UUID(session_id))
                photo = session.get(PhotoRow, UUID(media["media_id"]))
                check("删掉最后一条记录仍保留 session", session_row is not None and session_row.status == "completed")
                check("删掉最后一条记录仍保留照片及其 session", photo is not None and photo.session_id == UUID(session_id) and photo.observation_id is None)
            check("最终只删除 observations", table_counts(session_factory) == (0, baseline_counts[1], baseline_counts[2], baseline_counts[3]))


for name, passed, detail in _RESULTS:
    marker = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail and not passed else ""
    print(f"[{marker}] {name}{suffix}")

passed_count = sum(1 for _, passed, _ in _RESULTS if passed)
print(f"\n{passed_count}/{len(_RESULTS)} checks passed")
if passed_count != len(_RESULTS):
    raise SystemExit(1)
