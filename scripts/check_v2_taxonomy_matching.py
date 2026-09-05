#!/usr/bin/env python
"""Offline verification for v2 slice 2.3 taxonomy and dry-run matching."""

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
from vibirding.db.models import ObservationRow  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    BirdIdCandidate,
    DraftObservation,
    PhotoIdentification,
    SpeciesCatalogEntry,
    SpeciesLookup,
)
from vibirding.services import taxonomy as taxonomy_module  # noqa: E402
from vibirding.services.matching import DryRunMatchingService  # noqa: E402
from vibirding.services.taxonomy import (  # noqa: E402
    EbirdTaxonomyAdapter,
    TaxonomyImportError,
    TaxonomyService,
)


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def uid(number: int) -> UUID:
    return UUID(int=number)


def entry(
    key: str,
    chinese: str,
    scientific: str,
    aliases: list[str] | None = None,
) -> SpeciesCatalogEntry:
    return SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key=key,
        canonical_chinese_name=chinese,
        scientific_name=scientific,
        aliases=aliases or [],
    )


def draft(draft_id: str, label: str) -> DraftObservation:
    return DraftObservation(
        client_draft_id=draft_id,
        raw_note=label,
        species_label=label,
        source="user",
    )


def photo(
    number: int,
    label: str,
    scientific: str | None,
) -> PhotoIdentification:
    return PhotoIdentification(
        photo_id=uid(number),
        status="identified",
        candidate=BirdIdCandidate(
            species_label=label,
            scientific_name=scientific,
            confidence=90,
        ),
    )


# eBird response adapter: only category=species and exact source fields survive.
api_rows = [
    {
        "speciesCode": "azwmag2",
        "comName": "灰喜鹊",
        "sciName": "Cyanopica cyanus",
        "category": "species",
    },
    {
        "speciesCode": "y00001",
        "comName": "乌鸦属",
        "sciName": "Corvus sp.",
        "category": "spuh",
    },
]
adapted = EbirdTaxonomyAdapter.parse_rows(api_rows)
check("eBird adapter 只保留 species", len(adapted) == 1)
check("speciesCode 成为 taxonomy_key", adapted[0].taxonomy_key == "azwmag2")
check("comName 成为规范中文名", adapted[0].canonical_chinese_name == "灰喜鹊")
check("sciName 成为科学名", adapted[0].scientific_name == "Cyanopica cyanus")


# fetch_entries itself is exercised with a local response stub, never the network.
class FakeResponse:
    status_code = 200

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return api_rows


captured: dict = {}


def fake_get(url, **kwargs):
    captured["url"] = url
    captured.update(kwargs)
    return FakeResponse()


original_get = taxonomy_module.httpx.get
taxonomy_module.httpx.get = fake_get
try:
    fetched = EbirdTaxonomyAdapter(api_key="offline-key").fetch_entries()
finally:
    taxonomy_module.httpx.get = original_get
check("fetch 使用官方 taxonomy endpoint", captured["url"].endswith("/ref/taxonomy/ebird"))
check("fetch 限定 species/json/zh_SIM", captured["params"] == {"cat": "species", "fmt": "json", "locale": "zh_SIM"})
check("fetch 使用 eBird token header", captured["headers"] == {"X-eBirdApiToken": "offline-key"})
check("fetch 返回结构化名录", fetched == adapted)


with temporary_schema("taxonomy") as session_factory:
    taxonomy = TaxonomyService(session_factory)
    initial = [
        entry("azwmag2", "灰喜鹊", "Cyanopica cyanus"),
        entry("grecor", "鸬鹚", "Phalacrocorax carbo"),
        entry("comkin1", "普通翠鸟", "Alcedo atthis", ["翠鸟"]),
        entry("larcro1", "大嘴乌鸦", "Corvus macrorhynchos", ["乌鸦"]),
        entry("carcro1", "小嘴乌鸦", "Corvus corone", ["乌鸦"]),
    ]
    imported = taxonomy.import_entries(initial)
    ids = {record.taxonomy_key: record.id for record in imported}
    check("名录条目全部导入", len(imported) == 5)
    check("每个物种获得内部 UUID", all(isinstance(record.id, UUID) for record in imported))

    updated = taxonomy.import_entries(
        [
            entry(
                "azwmag2",
                "灰喜鹊（东亚）",
                "Cyanopica cyanus",
                ["灰喜鹊", " 灰喜鹊 ", "Cyanopica cyanus", ""],
            )
        ]
    )[0]
    check("相同 source/key 导入保持内部 UUID", updated.id == ids["azwmag2"])
    check("年度名称可幂等更新", updated.canonical_chinese_name == "灰喜鹊（东亚）")
    check("aliases 去空白、去重复、排除科学名", updated.aliases == ["灰喜鹊"])

    before_duplicate = len(
        taxonomy.resolve_many([SpeciesLookup(species_label="灰喜鹊")])
    )
    try:
        taxonomy.import_entries(
            [
                entry("duplicate", "测试鸟甲", "Testus alpha"),
                entry("duplicate", "测试鸟乙", "Testus beta"),
            ]
        )
        duplicate_rejected = False
    except TaxonomyImportError:
        duplicate_rejected = True
    check("同批重复 source/key 整批拒绝", duplicate_rejected)
    check("重复批次拒绝后服务仍可查询", before_duplicate == 1)

    resolutions = taxonomy.resolve_many(
        [
            SpeciesLookup(species_label="  灰喜鹊  "),
            SpeciesLookup(
                species_label="错误中文名",
                scientific_name="cyanopica   CYANUS",
            ),
            SpeciesLookup(species_label="普通翠鸟"),
            SpeciesLookup(species_label="翠鸟"),
            SpeciesLookup(species_label="乌鸦"),
            SpeciesLookup(species_label="火星鸟"),
            SpeciesLookup(),
        ]
    )
    check("别名精确解析成功", resolutions[0].status == "resolved" and resolutions[0].matched_by == "alias")
    check("科学名优先且归一化大小写/空白", resolutions[1].species_id == ids["azwmag2"] and resolutions[1].matched_by == "scientific_name")
    check("规范中文名精确解析", resolutions[2].species_id == ids["comkin1"] and resolutions[2].matched_by == "canonical_name")
    check("普通别名精确解析", resolutions[3].species_id == ids["comkin1"] and resolutions[3].matched_by == "alias")
    check("同级多命中显式 ambiguous", resolutions[4].status == "ambiguous" and len(resolutions[4].candidate_species_ids) == 2)
    check("未知名称显式 unmapped", resolutions[5].status == "unmapped" and resolutions[5].warning is not None)
    check("空名称显式 unmapped", resolutions[6].status == "unmapped")

    drafts = [draft("draft-1", "灰喜鹊"), draft("draft-2", "鸬鹚")]
    photos = [
        photo(1, "不同的中文显示名", "Cyanopica cyanus"),
        photo(2, "灰喜鹊", "Cyanopica cyanus"),
        photo(3, "鸬鹚", "Phalacrocorax carbo"),
        photo(4, "翠鸟", "Alcedo atthis"),
        photo(5, "乌鸦", None),
        photo(6, "火星鸟", None),
        PhotoIdentification(
            photo_id=uid(7), status="unrecognized", warning="未识别"
        ),
        PhotoIdentification(photo_id=uid(8), status="failed", warning="上传失败"),
    ]
    drafts_before = [item.model_dump() for item in drafts]
    photos_before = [item.model_dump() for item in photos]
    plan = DryRunMatchingService(taxonomy).plan(drafts, photos)
    by_photo = {item.photo_id: item for item in plan.photos}

    check("文本草稿先解析为 species_id", all(item.resolution.status == "resolved" for item in plan.drafts))
    check("科学名相同即可跨中文显示名配对", by_photo[uid(1)].status == "matched" and by_photo[uid(1)].client_draft_id == "draft-1")
    check("同种多图归到同一草稿", by_photo[uid(2)].client_draft_id == "draft-1")
    check("另一物种匹配到对应草稿", by_photo[uid(3)].client_draft_id == "draft-2")
    check("名录已解析但文本无该种为 unmatched", by_photo[uid(4)].status == "unmatched")
    check("照片物种名歧义保持 ambiguous", by_photo[uid(5)].status == "ambiguous")
    check("照片物种查不到保持 unmapped", by_photo[uid(6)].status == "unmapped")
    check("未识别状态原样保留", by_photo[uid(7)].status == "unrecognized")
    check("识别失败状态原样保留", by_photo[uid(8)].status == "failed")
    check("所有非匹配情况产生可见 warnings", len(plan.warnings) >= 5)
    check("dry-run 不修改输入草稿", drafts_before == [item.model_dump() for item in drafts])
    check("dry-run 不修改输入照片", photos_before == [item.model_dump() for item in photos])

    ambiguous_plan = DryRunMatchingService(taxonomy).plan(
        [draft("draft-a", "灰喜鹊"), draft("draft-b", "灰喜鹊")],
        [photo(9, "灰喜鹊", "Cyanopica cyanus")],
    )
    check("同一 species_id 对应多条文本时不擅自选择", ambiguous_plan.photos[0].status == "ambiguous" and ambiguous_plan.photos[0].client_draft_id is None)

    with session_factory() as session:
        observation_count = session.scalar(
            select(func.count()).select_from(ObservationRow)
        )
    check("2.3 没有写 observations", observation_count == 0, str(observation_count))


def main() -> int:
    print("=" * 72)
    print("v2 2.3 名录与 dry-run 匹配验证 — 离线、PostgreSQL 临时 schema")
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
