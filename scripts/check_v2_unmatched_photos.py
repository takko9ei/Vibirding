#!/usr/bin/env python
"""Offline verification for v2 slice 2.5 unmatched-photo draft assembly."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from sqlalchemy import func, select  # noqa: E402

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.db.models import ObservationRow, PhotoRow, SessionRow  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    BirdIdCandidate,
    DraftObservation,
    ParseResult,
    PhotoIdentification,
    SpeciesCatalogEntry,
)
from vibirding.services.assembly import (  # noqa: E402
    ParseAssemblyError,
    ParseAssemblyService,
)
from vibirding.services.matching import DryRunMatchingService  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def uid(number: int) -> UUID:
    return UUID(int=number)


def entry(key: str, chinese: str, scientific: str) -> SpeciesCatalogEntry:
    return SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key=key,
        canonical_chinese_name=chinese,
        scientific_name=scientific,
    )


def draft(
    draft_id: str,
    label: str,
    *,
    place: str | None = "井之头公园",
    obs_date: str | None = "2026-09-06",
    time_of_day: str | None = "morning",
) -> DraftObservation:
    return DraftObservation(
        client_draft_id=draft_id,
        place=place,
        obs_date=obs_date,
        time_of_day=time_of_day,
        count=2,
        raw_note=f"看见{label}",
        species_label=label,
        source="user",
    )


def photo(
    number: int,
    label: str,
    scientific: str | None,
    confidence: float = 90,
) -> PhotoIdentification:
    return PhotoIdentification(
        photo_id=uid(number),
        status="identified",
        candidate=BirdIdCandidate(
            species_label=label,
            scientific_name=scientific,
            confidence=confidence,
        ),
    )


with temporary_schema("unmatched_photos") as session_factory:
    taxonomy = TaxonomyService(session_factory)
    species = taxonomy.import_entries(
        [
            entry("azwmag2", "灰喜鹊", "Cyanopica cyanus"),
            entry("grecor", "普通鸬鹚", "Phalacrocorax carbo"),
            entry("comkin1", "普通翠鸟", "Alcedo atthis"),
            entry("eurhoo", "戴胜", "Upupa epops"),
        ]
    )
    species_ids = {item.taxonomy_key: item.id for item in species}
    service = ParseAssemblyService(DryRunMatchingService(taxonomy))

    drafts = [draft("draft-1", "灰喜鹊"), draft("draft-2", "普通鸬鹚")]
    photos = [
        photo(1, "灰喜鹊", "Cyanopica cyanus"),
        photo(2, "翠鸟", "Alcedo atthis", 95),
        photo(3, "普通翠鸟", "Alcedo atthis", 80),
        photo(4, "火星鸟", None),
        PhotoIdentification(photo_id=uid(5), status="unrecognized", warning="未识别"),
        PhotoIdentification(photo_id=uid(6), status="failed", warning="上传失败"),
    ]
    drafts_before = [item.model_dump() for item in drafts]
    photos_before = [item.model_dump() for item in photos]
    result = service.assemble(drafts, photos)

    check("返回正式 ParseResult", isinstance(result, ParseResult))
    check("同步任务状态固定 completed", result.job_status == "completed")
    check("两个文本草稿保留原顺序", [d.client_draft_id for d in result.draft_observations[:2]] == ["draft-1", "draft-2"])
    check("文本草稿补上 species_id", [d.species_id for d in result.draft_observations[:2]] == [species_ids["azwmag2"], species_ids["grecor"]])
    check("匹配照片归入原文本草稿", result.draft_observations[0].photo_ids == [uid(1)])
    check("文字未提及的物种只生成一个草稿", len(result.draft_observations) == 3)

    generated = result.draft_observations[2]
    check("自动草稿 ID 使用 photo-draft-N", generated.client_draft_id == "photo-draft-1")
    check("同种多张未匹配照片合并", generated.photo_ids == [uid(2), uid(3)])
    check("自动草稿保存可靠物种 ID", generated.species_id == species_ids["comkin1"])
    check("自动草稿使用首张候选显示名", generated.species_label == "翠鸟")
    check("自动草稿来源为 bird_id", generated.source == "bird_id")
    check("自动草稿不猜数量和聚合置信度", generated.count is None and generated.confidence is None)
    check("自动草稿明确标记来源", generated.flags == ["auto_created_from_unmatched_photo"])
    check("自动草稿强制进入用户确认", generated.needs_confirmation is True)
    check("一致地点日期时段安全继承", (generated.place, generated.obs_date, generated.time_of_day) == ("井之头公园", "2026-09-06", "morning"))
    check("自动 raw_note 可解释", generated.raw_note == "由未匹配照片自动生成：翠鸟")
    check("每张未匹配照片均保留审计映射", [(item.photo_id, item.client_draft_id) for item in result.unmatched_photos] == [(uid(2), "photo-draft-1"), (uid(3), "photo-draft-1")])
    check("无法可靠解析的照片不自动建草稿", {item.photo_id for item in result.unmatched_photos} == {uid(2), uid(3)})
    check("匹配失败原因继续对用户可见", len(result.warnings) >= 5)
    check("组装不修改输入草稿", drafts_before == [item.model_dump() for item in drafts])
    check("组装不修改输入照片", photos_before == [item.model_dump() for item in photos])

    divergent = service.assemble(
        [
            draft("photo-draft-1", "灰喜鹊", place="地点甲", obs_date="2026-09-05"),
            draft("draft-b", "普通鸬鹚", place="地点乙", obs_date="2026-09-06"),
        ],
        [
            photo(10, "戴胜", "Upupa epops"),
            photo(11, "翠鸟", "Alcedo atthis"),
        ],
    )
    generated_ids = [item.client_draft_id for item in divergent.draft_observations[2:]]
    check("自动 ID 避开已有草稿 ID", generated_ids == ["photo-draft-2", "photo-draft-3"])
    check("不同物种按首张照片顺序各建一条", [item.species_id for item in divergent.draft_observations[2:]] == [species_ids["eurhoo"], species_ids["comkin1"]])
    check("上下文不一致时不取第一条猜测", all(item.place is None and item.obs_date is None for item in divergent.draft_observations[2:]))

    no_text = service.assemble([], [photo(12, "戴胜", "Upupa epops")])
    check("纯照片输入也能生成草稿", len(no_text.draft_observations) == 1 and no_text.draft_observations[0].photo_ids == [uid(12)])
    check("无文本时上下文保持未知", no_text.draft_observations[0].place is None and no_text.draft_observations[0].obs_date is None)

    ambiguous = service.assemble(
        [draft("same-a", "灰喜鹊"), draft("same-b", "灰喜鹊")],
        [photo(13, "灰喜鹊", "Cyanopica cyanus")],
    )
    check("照片对应多个文本草稿时不另建记录", len(ambiguous.draft_observations) == 2 and not ambiguous.unmatched_photos)

    for bad_drafts, bad_photos in (
        ([draft("duplicate", "灰喜鹊"), draft("duplicate", "普通鸬鹚")], []),
        ([], [photo(20, "戴胜", "Upupa epops"), photo(20, "戴胜", "Upupa epops")]),
    ):
        try:
            service.assemble(bad_drafts, bad_photos)
            rejected = False
        except ParseAssemblyError:
            rejected = True
        check("重复客户端 ID 在组装前整批拒绝", rejected)

    with session_factory() as session:
        counts = [
            session.scalar(select(func.count()).select_from(model))
            for model in (ObservationRow, SessionRow, PhotoRow)
        ]
    check("2.5 不写 observations/sessions/photos", counts == [0, 0, 0], str(counts))


def main() -> int:
    print("=" * 72)
    print("v2 2.5 未匹配照片草稿验证 — 离线、PostgreSQL 临时 schema")
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
