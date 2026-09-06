#!/usr/bin/env python
"""HTTP verification for v2 slice 3.4 observation list and detail reads."""

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
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import Observation, SpeciesCatalogEntry  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def draft(
    draft_id: str,
    *,
    place: str,
    obs_date: str,
    species_label: str,
    species_id: UUID | None,
    photo_ids: list[str] | None = None,
    count: int = 1,
) -> dict:
    return {
        "client_draft_id": draft_id,
        "place": place,
        "obs_date": obs_date,
        "time_of_day": "上午",
        "count": count,
        "behavior": "测试行为",
        "raw_note": f"{draft_id} 的单条原文",
        "species_label": species_label,
        "species_id": str(species_id) if species_id else None,
        "confidence": 88,
        "source": "user",
        "flags": ["read-api-fixture"],
        "photo_ids": photo_ids or [],
        "needs_confirmation": False,
    }


def database_counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
        )


with TemporaryDirectory(prefix="vibirding-observation-reads-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("observation_reads") as session_factory:
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
            def upload(number: int) -> dict:
                content = (
                    b"\xff\xd8\xff\xe0"
                    + f"observation-read-{number}".encode()
                    + b"\xff\xd9"
                )
                response = client.post(
                    "/api/media",
                    files={
                        "photo": (
                            f"read-{number}.jpg",
                            content,
                            "image/jpeg",
                        )
                    },
                )
                check(f"测试媒体 {number} 上传成功", response.status_code == 201)
                return response.json()

            media = [upload(number) for number in range(1, 4)]

            first_batch = client.post(
                "/api/observations",
                json={
                    "text": "第一批完整原始笔记",
                    "media_ids": [media[0]["media_id"], media[1]["media_id"]],
                    "observations": [
                        draft(
                            "draft-a",
                            place="井之头公园",
                            obs_date="2026-09-01",
                            species_label="灰喜鹊",
                            species_id=grey.id,
                            photo_ids=[
                                media[0]["media_id"],
                                media[1]["media_id"],
                            ],
                            count=3,
                        ),
                        draft(
                            "draft-b",
                            place="葛西临海公园",
                            obs_date="2026-09-02",
                            species_label="普通鸬鹚",
                            species_id=cormorant.id,
                            count=2,
                        ),
                    ],
                    "confirmed": True,
                },
            )
            check("第一批 fixture 写入成功", first_batch.status_code == 201)
            first_payload = first_batch.json()
            observation_a = first_payload["created"][0]["observation_id"]
            observation_b = first_payload["created"][1]["observation_id"]

            second_batch = client.post(
                "/api/observations",
                json={
                    "text": "第二批完整原始笔记",
                    "media_ids": [media[2]["media_id"]],
                    "observations": [
                        draft(
                            "draft-c",
                            place="井之头公园",
                            obs_date="2026-09-03",
                            species_label="灰喜鹊",
                            species_id=grey.id,
                            photo_ids=[media[2]["media_id"]],
                            count=4,
                        )
                    ],
                    "confirmed": True,
                },
            )
            check("第二批 fixture 写入成功", second_batch.status_code == 201)
            observation_c = second_batch.json()["created"][0]["observation_id"]

            literal_batch = client.post(
                "/api/observations",
                json={
                    "text": "通配符字面量 fixture",
                    "media_ids": [],
                    "observations": [
                        draft(
                            "draft-d",
                            place="100%_池",
                            obs_date="2026-09-04",
                            species_label="百分号鸟",
                            species_id=None,
                        )
                    ],
                    "confirmed": True,
                },
            )
            check("字面量 fixture 写入成功", literal_batch.status_code == 201)
            observation_d = literal_batch.json()["created"][0]["observation_id"]

            legacy_id = uuid4()
            Log(session_factory).append(
                Observation(
                    id=str(legacy_id),
                    timestamp=datetime(
                        2026,
                        8,
                        1,
                        12,
                        tzinfo=timezone.utc,
                    ).isoformat(),
                    place="旧地点",
                    obs_date=None,
                    species="旧式记录",
                    count=1,
                    raw_note="v1 单条原文",
                    source="user",
                )
            )

            counts_before_reads = database_counts(session_factory)

            listed = client.get("/api/observations")
            listed_payload = listed.json()
            check("默认列表返回 200", listed.status_code == 200, listed.text)
            check("列表使用 items 信封", set(listed_payload) == {"items"})
            items = listed_payload["items"]
            check("默认列表返回全部五条 fixture", len(items) == 5)
            check(
                "列表按 sequence_no 最新优先",
                [item["observation_id"] for item in items]
                == [
                    str(legacy_id),
                    observation_d,
                    observation_c,
                    observation_b,
                    observation_a,
                ],
            )
            expected_summary_fields = {
                "observation_id",
                "timestamp",
                "species_label",
                "species_id",
                "count",
                "place",
                "obs_date",
                "time_of_day",
                "photo_count",
                "thumbnail_url",
            }
            check("列表摘要字段严格", set(items[0]) == expected_summary_fields)
            by_id = {item["observation_id"]: item for item in items}
            check(
                "列表照片数量正确",
                by_id[observation_a]["photo_count"] == 2
                and by_id[observation_c]["photo_count"] == 1
                and by_id[observation_b]["photo_count"] == 0,
            )
            check(
                "无照片时缩略图为 null",
                by_id[observation_b]["thumbnail_url"] is None,
            )
            expected_first_url = sorted([media[0]["url"], media[1]["url"]])[0]
            check(
                "缩略图使用内容哈希稳定首图",
                by_id[observation_a]["thumbnail_url"] == expected_first_url,
            )

            limited = client.get("/api/observations", params={"limit": 2})
            check(
                "limit 截取最新两条",
                [item["observation_id"] for item in limited.json()["items"]]
                == [str(legacy_id), observation_d],
            )

            place_filtered = client.get(
                "/api/observations",
                params={"place": "井之头"},
            )
            check(
                "地点子串筛选并保持新到旧",
                [item["observation_id"] for item in place_filtered.json()["items"]]
                == [observation_c, observation_a],
            )

            species_filtered = client.get(
                "/api/observations",
                params={"species": "灰喜"},
            )
            check(
                "物种子串筛选",
                [item["observation_id"] for item in species_filtered.json()["items"]]
                == [observation_c, observation_a],
            )

            date_filtered = client.get(
                "/api/observations",
                params={"date_from": "2026-09-02", "date_to": "2026-09-03"},
            )
            check(
                "起止日期包含边界",
                [item["observation_id"] for item in date_filtered.json()["items"]]
                == [observation_c, observation_b],
            )

            combined = client.get(
                "/api/observations",
                params={"place": "井之头", "date_from": "2026-09-03"},
            )
            check(
                "多个筛选条件使用 AND",
                [item["observation_id"] for item in combined.json()["items"]]
                == [observation_c],
            )

            literal = client.get(
                "/api/observations",
                params={"place": "%_"},
            )
            check(
                "% 和 _ 按普通字符筛选",
                [item["observation_id"] for item in literal.json()["items"]]
                == [observation_d],
            )

            blank_filters = client.get(
                "/api/observations",
                params={"place": "   ", "species": " "},
            )
            check("空白筛选等同未筛选", len(blank_filters.json()["items"]) == 5)

            empty = client.get(
                "/api/observations",
                params={"species": "不存在的鸟"},
            )
            check("无匹配返回空 items", empty.json() == {"items": []})

            detail = client.get(f"/api/observations/{observation_a}")
            detail_payload = detail.json()
            check("详情返回 200", detail.status_code == 200, detail.text)
            expected_detail_fields = expected_summary_fields | {
                "behavior",
                "raw_note",
                "confidence",
                "source",
                "flags",
                "photos",
                "session",
            }
            check("详情字段严格", set(detail_payload) == expected_detail_fields)
            check(
                "详情保留单条字段",
                detail_payload["raw_note"] == "draft-a 的单条原文"
                and detail_payload["behavior"] == "测试行为"
                and detail_payload["flags"] == ["read-api-fixture"],
            )
            check("详情返回全部两张照片", len(detail_payload["photos"]) == 2)
            check(
                "详情照片按内容哈希稳定排序",
                [photo["url"] for photo in detail_payload["photos"]]
                == sorted([media[0]["url"], media[1]["url"]]),
            )
            expected_photo_fields = {
                "media_id",
                "url",
                "original_filename",
                "mime_type",
                "size_bytes",
            }
            check(
                "照片只暴露安全展示字段",
                all(
                    set(photo) == expected_photo_fields
                    for photo in detail_payload["photos"]
                ),
            )
            check(
                "详情包含完整 session 原文与状态",
                detail_payload["session"]["raw_text"] == "第一批完整原始笔记"
                and detail_payload["session"]["status"] == "completed",
            )
            check(
                "session 不暴露 user_id",
                set(detail_payload["session"])
                == {"session_id", "created_at", "raw_text", "status"},
            )
            fetched_photo = client.get(detail_payload["photos"][0]["url"])
            check("详情媒体 URL 可以读取", fetched_photo.status_code == 200)

            legacy_detail = client.get(f"/api/observations/{legacy_id}")
            check("v1 记录详情返回 200", legacy_detail.status_code == 200)
            check(
                "v1 记录没有伪造 session 或照片",
                legacy_detail.json()["session"] is None
                and legacy_detail.json()["photos"] == [],
            )

            missing_id = str(uuid4())
            missing = client.get(f"/api/observations/{missing_id}")
            check("未知 observation 返回 404", missing.status_code == 404)
            check("404 包含查询 ID", missing_id in missing.json()["detail"])

            invalid_cases = [
                ("limit=0 返回 422", {"limit": 0}),
                ("limit=101 返回 422", {"limit": 101}),
                ("非法 date_from 返回 422", {"date_from": "2026-99-99"}),
            ]
            for name, params in invalid_cases:
                response = client.get("/api/observations", params=params)
                check(name, response.status_code == 422, response.text)
            invalid_uuid = client.get("/api/observations/not-a-uuid")
            check("非法 observation UUID 返回 422", invalid_uuid.status_code == 422)
            reversed_dates = client.get(
                "/api/observations",
                params={"date_from": "2026-09-04", "date_to": "2026-09-01"},
            )
            check("反向日期范围返回 400", reversed_dates.status_code == 400)
            check("400 日期错误可读", bool(reversed_dates.json().get("detail")))

            check(
                "所有 GET 请求均无数据库写入",
                database_counts(session_factory) == counts_before_reads,
            )


def main() -> int:
    print("=" * 72)
    print("v2 3.4 FastAPI 观测读取验证 — HTTP 客户端、临时 schema/目录")
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
