#!/usr/bin/env python
"""HTTP verification for v2 slice 3.5 observation editing."""

from __future__ import annotations

import sys
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
        "obs_date": "2026-09-01",
        "time_of_day": "上午",
        "count": 3,
        "behavior": "停在树上",
        "raw_note": f"{draft_id} 原文",
        "species_label": "灰喜鹊",
        "species_id": str(species_id),
        "confidence": 88,
        "source": "user",
        "flags": ["fixture"],
        "photo_ids": photo_ids or [],
        "needs_confirmation": False,
    }


def table_counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
        )


with TemporaryDirectory(prefix="vibirding-observation-edit-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("observation_edit") as session_factory:
        grey, cormorant = TaxonomyService(session_factory).import_entries(
            [
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="azwmag1",
                    canonical_chinese_name="灰喜鹊",
                    scientific_name="Cyanopica cyanus",
                ),
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="grecor",
                    canonical_chinese_name="普通鸬鹚",
                    scientific_name="Phalacrocorax carbo",
                ),
            ]
        )
        app = create_app(session_factory=session_factory, media_dir=media_dir)

        with TestClient(app) as client:
            image_bytes = b"\xff\xd8\xff\xe0edit-api-photo\xff\xd9"
            upload = client.post(
                "/api/media",
                files={"photo": ("edit.jpg", image_bytes, "image/jpeg")},
            )
            check("fixture 照片上传成功", upload.status_code == 201, upload.text)
            media = upload.json()

            create_first = client.post(
                "/api/observations",
                json={
                    "text": "包含照片的第一批原始笔记",
                    "media_ids": [media["media_id"]],
                    "observations": [
                        draft(
                            "draft-first",
                            grey.id,
                            photo_ids=[media["media_id"]],
                        )
                    ],
                    "confirmed": True,
                },
            )
            create_second = client.post(
                "/api/observations",
                json={
                    "text": "第二批原始笔记",
                    "media_ids": [],
                    "observations": [draft("draft-second", grey.id)],
                    "confirmed": True,
                },
            )
            check("两条 fixture 写入成功", create_first.status_code == 201 and create_second.status_code == 201)
            first_id = create_first.json()["created"][0]["observation_id"]
            second_id = create_second.json()["created"][0]["observation_id"]

            baseline = client.get(f"/api/observations/{first_id}").json()
            baseline_counts = table_counts(session_factory)
            baseline_file = (media_dir / f"{media['hash']}.jpg").read_bytes()
            baseline_order = [
                item["observation_id"]
                for item in client.get("/api/observations").json()["items"]
            ]
            with session_factory() as session:
                row = session.get(ObservationRow, UUID(first_id))
                baseline_sequence = row.sequence_no
                baseline_session_id = row.session_id
                photo = session.get(PhotoRow, UUID(media["media_id"]))
                baseline_photo_links = (photo.session_id, photo.observation_id)

            updated = client.patch(
                f"/api/observations/{first_id}",
                json={
                    "place": "葛西临海公园",
                    "obs_date": "2026-09-05",
                    "time_of_day": "黄昏",
                    "species_label": "鸬鹚（手工展示名）",
                    "species_id": str(cormorant.id),
                    "count": 7,
                    "behavior": "潜水觅食",
                    "raw_note": "编辑后的单条原文",
                    "confidence": 96.5,
                    "flags": ["edited", "waterbird"],
                },
            )
            payload = updated.json()
            check("多字段 PATCH 返回 200", updated.status_code == 200, updated.text)
            check("可编辑字段全部更新", all([
                payload["place"] == "葛西临海公园",
                payload["obs_date"] == "2026-09-05",
                payload["time_of_day"] == "黄昏",
                payload["species_label"] == "普通鸬鹚",
                payload["species_id"] == str(cormorant.id),
                payload["count"] == 7,
                payload["behavior"] == "潜水觅食",
                payload["raw_note"] == "编辑后的单条原文",
                payload["confidence"] == 96.5,
                payload["flags"] == ["edited", "waterbird"],
            ]))
            check("非空 species_id 以名录规范名为准", payload["species_label"] != "鸬鹚（手工展示名）")
            check("成功响应仍是完整详情", payload["photos"][0]["media_id"] == media["media_id"] and payload["session"] == baseline["session"])
            check("身份与来源保持不变", payload["observation_id"] == first_id and payload["timestamp"] == baseline["timestamp"] and payload["source"] == baseline["source"])

            cleared = client.patch(
                f"/api/observations/{first_id}",
                json={"place": None, "behavior": None, "confidence": None},
            )
            check("显式 null 可清空可空字段", cleared.status_code == 200 and cleared.json()["place"] is None and cleared.json()["behavior"] is None and cleared.json()["confidence"] is None)
            check("省略字段保持原值", cleared.json()["count"] == 7 and cleared.json()["raw_note"] == "编辑后的单条原文")

            label_only = client.patch(
                f"/api/observations/{first_id}",
                json={"species_label": "不确定的水鸟"},
            )
            check("只改物种文字会清除旧 species_id", label_only.status_code == 200 and label_only.json()["species_label"] == "不确定的水鸟" and label_only.json()["species_id"] is None)

            id_only = client.patch(
                f"/api/observations/{first_id}",
                json={"species_id": str(grey.id)},
            )
            check("只给 species_id 自动采用规范中文名", id_only.status_code == 200 and id_only.json()["species_id"] == str(grey.id) and id_only.json()["species_label"] == "灰喜鹊")
            id_with_null_label = client.patch(
                f"/api/observations/{first_id}",
                json={"species_id": str(cormorant.id), "species_label": None},
            )
            check("非空 species_id 配空标签仍回填规范名", id_with_null_label.status_code == 200 and id_with_null_label.json()["species_label"] == "普通鸬鹚")
            unlink = client.patch(
                f"/api/observations/{first_id}", json={"species_id": None}
            )
            check("显式 null 只解除物种 ID 关联", unlink.status_code == 200 and unlink.json()["species_id"] is None and unlink.json()["species_label"] == "普通鸬鹚")

            empties = client.patch(
                f"/api/observations/{first_id}",
                json={"raw_note": "", "flags": []},
            )
            check("raw_note 空字符串与空 flags 合法", empties.status_code == 200 and empties.json()["raw_note"] == "" and empties.json()["flags"] == [])

            before_failures = client.get(f"/api/observations/{first_id}").json()
            invalid_date = client.patch(
                f"/api/observations/{first_id}", json={"obs_date": "2026-02-30"}
            )
            check("非法 ISO 日期返回 422", invalid_date.status_code == 422)
            check("空补丁返回 422", client.patch(f"/api/observations/{first_id}", json={}).status_code == 422)
            check("raw_note=null 返回 422", client.patch(f"/api/observations/{first_id}", json={"raw_note": None}).status_code == 422)
            check("flags=null 返回 422", client.patch(f"/api/observations/{first_id}", json={"flags": None}).status_code == 422)
            check("不可编辑 source 返回 422", client.patch(f"/api/observations/{first_id}", json={"source": "manual"}).status_code == 422)
            check("不可编辑照片返回 422", client.patch(f"/api/observations/{first_id}", json={"photo_ids": []}).status_code == 422)
            check("错误字段类型返回 422", client.patch(f"/api/observations/{first_id}", json={"count": "很多"}).status_code == 422)
            check("非法 observation UUID 返回 422", client.patch("/api/observations/not-a-uuid", json={"count": 1}).status_code == 422)
            check("未知 observation 返回 404", client.patch(f"/api/observations/{uuid4()}", json={"count": 1}).status_code == 404)

            unknown_species = uuid4()
            rollback = client.patch(
                f"/api/observations/{first_id}",
                json={
                    "place": "这项不应落库",
                    "species_id": str(unknown_species),
                },
            )
            check("未知 species_id 返回 404", rollback.status_code == 404 and str(unknown_species) in rollback.text)
            after_failures = client.get(f"/api/observations/{first_id}").json()
            check("失败请求没有部分更新", after_failures == before_failures)

            final_order = [
                item["observation_id"]
                for item in client.get("/api/observations").json()["items"]
            ]
            check("编辑不改变最新优先列表顺序", final_order == baseline_order and final_order[:2] == [second_id, first_id])
            check("编辑不创建或删除业务行", table_counts(session_factory) == baseline_counts)
            check("编辑不修改媒体文件", (media_dir / f"{media['hash']}.jpg").read_bytes() == baseline_file)
            with session_factory() as session:
                row = session.get(ObservationRow, UUID(first_id))
                photo = session.get(PhotoRow, UUID(media["media_id"]))
                check("sequence_no 和 session_id 保持不变", row.sequence_no == baseline_sequence and row.session_id == baseline_session_id)
                check("照片 session/observation 归属保持不变", (photo.session_id, photo.observation_id) == baseline_photo_links)


for name, passed, detail in _RESULTS:
    marker = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail and not passed else ""
    print(f"[{marker}] {name}{suffix}")

passed_count = sum(1 for _, passed, _ in _RESULTS if passed)
print(f"\n{passed_count}/{len(_RESULTS)} checks passed")
if passed_count != len(_RESULTS):
    raise SystemExit(1)
