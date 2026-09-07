#!/usr/bin/env python
"""HTTP verification for v2 slice 3.7 local species search."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

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
from vibirding.schemas import SpeciesCatalogEntry  # noqa: E402
from vibirding.services import taxonomy as taxonomy_module  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def entry(
    key: str,
    chinese: str,
    scientific: str | None,
    aliases: list[str] | None = None,
) -> SpeciesCatalogEntry:
    return SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key=key,
        canonical_chinese_name=chinese,
        scientific_name=scientific,
        aliases=aliases or [],
    )


def table_counts(session_factory) -> tuple[int, int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(SpeciesRow)) or 0,
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
        )


fixtures = [
    entry("rank-0", "乌鸦", "Rank zero"),
    entry("rank-1", "甲一", "乌鸦"),
    entry("rank-2", "甲二", "Rank two", ["乌鸦"]),
    entry("rank-3", "乌鸦甲", "Rank three"),
    entry("rank-4", "甲四", "乌鸦 scientific"),
    entry("rank-5", "甲五", "Rank five", ["乌鸦别名"]),
    entry("rank-6", "大嘴乌鸦", "Rank six"),
    entry("rank-6b", "乙七", "Example 乌鸦 bird"),
    entry("rank-6c", "乙八", "Rank eight", ["大嘴乌鸦别名"]),
    entry("corone", "小嘴乌鸦", "Corvus corone", ["Carrion Crow"]),
    entry("macrorhynchos", "大嘴乌鸦（东亚）", "Corvus macrorhynchos"),
    entry("unicode", "ABC鸟", "Cyanopica cyanus"),
    entry("literal", "100%_鸟", "Literal bird"),
    entry("not-literal", "100XY鸟", "Wildcard decoy"),
    entry("tie-b", "Bird Beta", "Tie beta"),
    entry("tie-a", "Bird Alpha", "Tie alpha"),
]


with TemporaryDirectory(prefix="vibirding-species-api-") as temp_dir:
    with temporary_schema("species_api") as session_factory:
        TaxonomyService(session_factory).import_entries(fixtures)
        baseline_counts = table_counts(session_factory)
        app = create_app(
            session_factory=session_factory,
            media_dir=Path(temp_dir),
        )

        original_get = taxonomy_module.httpx.get

        def reject_network(*args, **kwargs):
            nonlocal_network_calls[0] += 1
            raise AssertionError("species search must not call eBird")

        nonlocal_network_calls = [0]
        taxonomy_module.httpx.get = reject_network
        try:
            with TestClient(app) as client:
                ranked = client.get("/api/species", params={"q": "乌鸦"})
                check("物种查询返回 200", ranked.status_code == 200, ranked.text)
                ranked_payload = ranked.json()
                check("响应使用 items 信封", set(ranked_payload) == {"items"})
                ranked_items = ranked_payload["items"]
                keys_by_name = {
                    item.canonical_chinese_name: item.taxonomy_key
                    for item in fixtures
                }
                ranked_keys = [
                    keys_by_name[item["canonical_chinese_name"]]
                    for item in ranked_items
                ]
                check(
                    "完全/前缀/子串七级相关度顺序正确",
                    ranked_keys[:6]
                    == [
                        "rank-0",
                        "rank-1",
                        "rank-2",
                        "rank-3",
                        "rank-4",
                        "rank-5",
                    ]
                    and set(ranked_keys[6:9])
                    == {"rank-6", "rank-6b", "rank-6c"},
                    str(ranked_keys),
                )
                check(
                    "每项公开字段严格",
                    all(
                        set(item)
                        == {
                            "species_id",
                            "canonical_chinese_name",
                            "scientific_name",
                            "aliases",
                        }
                        for item in ranked_items
                    ),
                )
                check(
                    "响应保留学名和别名",
                    ranked_items[2]["scientific_name"] == "Rank two"
                    and ranked_items[2]["aliases"] == ["乌鸦"],
                )

                casefolded = client.get(
                    "/api/species", params={"q": "cOrVuS"}
                ).json()["items"]
                check(
                    "科学名查询大小写不敏感",
                    [item["canonical_chinese_name"] for item in casefolded]
                    == ["大嘴乌鸦（东亚）", "小嘴乌鸦"],
                )

                normalized = client.get(
                    "/api/species",
                    params={"q": "  Cyanopica   cyanus  "},
                ).json()["items"]
                check(
                    "连续空白被折叠后可完全匹配学名",
                    len(normalized) == 1
                    and normalized[0]["canonical_chinese_name"] == "ABC鸟",
                )
                fullwidth = client.get(
                    "/api/species", params={"q": "ＡＢＣ"}
                ).json()["items"]
                check(
                    "NFKC 规范化全角输入",
                    len(fullwidth) == 1
                    and fullwidth[0]["canonical_chinese_name"] == "ABC鸟",
                )

                literal = client.get(
                    "/api/species", params={"q": "100%_"}
                ).json()["items"]
                check(
                    "% 和 _ 按普通字符查询",
                    [item["canonical_chinese_name"] for item in literal]
                    == ["100%_鸟"],
                )

                tied = client.get(
                    "/api/species", params={"q": "bird"}
                ).json()["items"]
                tied_names = [
                    item["canonical_chinese_name"]
                    for item in tied
                    if item["canonical_chinese_name"].startswith("Bird")
                ]
                check("同相关度按规范名稳定排序", tied_names == ["Bird Alpha", "Bird Beta"])

                limited = client.get(
                    "/api/species", params={"q": "乌鸦", "limit": 3}
                ).json()["items"]
                check("limit 在相关度排序后截取", len(limited) == 3 and limited == ranked_items[:3])
                check("无匹配返回 200 空列表", client.get("/api/species", params={"q": "火星鸟"}).json() == {"items": []})

                check("缺少 q 返回 422", client.get("/api/species").status_code == 422)
                check("空字符串 q 返回 422", client.get("/api/species", params={"q": ""}).status_code == 422)
                blank = client.get("/api/species", params={"q": "   "})
                check("纯空白 q 返回 400", blank.status_code == 400 and "blank" in blank.text)
                check("超过 100 字符 q 返回 422", client.get("/api/species", params={"q": "a" * 101}).status_code == 422)
                check("limit=0 返回 422", client.get("/api/species", params={"q": "鸟", "limit": 0}).status_code == 422)
                check("limit=51 返回 422", client.get("/api/species", params={"q": "鸟", "limit": 51}).status_code == 422)
                check("非整数 limit 返回 422", client.get("/api/species", params={"q": "鸟", "limit": "many"}).status_code == 422)
        finally:
            taxonomy_module.httpx.get = original_get

        network_calls = nonlocal_network_calls[0]
        check("全部查询均未调用 eBird 网络", network_calls == 0)
        check("全部查询均未修改数据库", table_counts(session_factory) == baseline_counts)


for name, passed, detail in _RESULTS:
    marker = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail and not passed else ""
    print(f"[{marker}] {name}{suffix}")

passed_count = sum(1 for _, passed, _ in _RESULTS if passed)
print(f"\n{passed_count}/{len(_RESULTS)} checks passed")
if passed_count != len(_RESULTS):
    raise SystemExit(1)
