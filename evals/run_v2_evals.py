#!/usr/bin/env python
"""Run the fixed v2 batch parsing and matching eval suite offline."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import NAMESPACE_URL, UUID, uuid5

import yaml
from sqlalchemy import func, select, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.db.models import ObservationRow, PhotoRow, SessionRow  # noqa: E402
from vibirding.db.session import build_engine  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    BirdIdResult,
    ModelResponse,
    PhotoInput,
    SpeciesCatalogEntry,
    ToolCall,
)
from vibirding.services.assembly import ParseAssemblyService  # noqa: E402
from vibirding.services.matching import DryRunMatchingService  # noqa: E402
from vibirding.services.parse import (  # noqa: E402
    PhotoPreprocessService,
    TextSplitService,
)
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


DEFAULT_TASKS = ROOT / "evals" / "v2_tasks.yaml"
DEFAULT_ANSWERS = ROOT / "evals" / "v2_answers.yaml"
REFERENCE_DATE = date(2026, 9, 7)

CATALOG = [
    SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key="grey_treepie",
        canonical_chinese_name="灰喜鹊",
        scientific_name="Cyanopica cyanus",
        aliases=["山喜鹊"],
    ),
    SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key="great_cormorant",
        canonical_chinese_name="普通鸬鹚",
        scientific_name="Phalacrocorax carbo",
        aliases=["鸬鹚"],
    ),
    SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key="tree_sparrow",
        canonical_chinese_name="树麻雀",
        scientific_name="Passer montanus",
        aliases=["麻雀"],
    ),
    SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key="carrion_crow",
        canonical_chinese_name="小嘴乌鸦",
        scientific_name="Corvus corone",
        aliases=["乌鸦"],
    ),
    SpeciesCatalogEntry(
        taxonomy_source="ebird",
        taxonomy_key="large_billed_crow",
        canonical_chinese_name="大嘴乌鸦",
        scientific_name="Corvus macrorhynchos",
        aliases=["乌鸦"],
    ),
]


class CountingMockClient:
    """Expose call counts while retaining the production MockClient behavior."""

    def __init__(self, script: list[ModelResponse]) -> None:
        self._client = MockClient(script)
        self.call_count = 0

    def complete(
        self, messages: list[dict], tools: list[dict] | None = None
    ) -> ModelResponse:
        self.call_count += 1
        return self._client.complete(messages, tools)


class FixtureBirdIdentifier:
    """Return a fixed provider result selected by the fixture filename."""

    def __init__(self, results: dict[str, BirdIdResult]) -> None:
        self._results = results
        self.calls: list[str] = []

    def identify(self, image_path: str) -> BirdIdResult:
        key = Path(image_path).stem
        self.calls.append(key)
        return self._results[key].model_copy(deep=True)


@dataclass
class CaseResult:
    case_id: str
    checks: list[tuple[str, bool, str]]
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(passed for _, passed, _ in self.checks)


def load_cases(tasks_path: Path, answers_path: Path) -> list[tuple[dict, dict]]:
    tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8")) or []
    answers = yaml.safe_load(answers_path.read_text(encoding="utf-8")) or []
    task_ids = [item["id"] for item in tasks]
    answer_ids = [item["id"] for item in answers]
    if len(set(task_ids)) != len(task_ids) or len(set(answer_ids)) != len(answer_ids):
        raise ValueError("v2 eval IDs must be unique")
    if set(task_ids) != set(answer_ids):
        raise ValueError("v2 task and answer IDs must match exactly")
    if len(tasks) != 6:
        raise ValueError(f"v2 fixed eval must contain 6 cases, found {len(tasks)}")
    answers_by_id = {item["id"]: item["expected"] for item in answers}
    return [(task, answers_by_id[task["id"]]) for task in tasks]


def business_counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
        )


def development_counts() -> tuple[int, int, int, int]:
    engine = build_engine()
    try:
        with engine.connect() as connection:
            row = connection.execute(
                text(
                    "select "
                    "(select count(*) from species), "
                    "(select count(*) from observations), "
                    "(select count(*) from sessions), "
                    "(select count(*) from photos)"
                )
            ).one()
            return tuple(int(value) for value in row)
    finally:
        engine.dispose()


def eval_schema_count() -> int:
    engine = build_engine()
    try:
        with engine.connect() as connection:
            return int(
                connection.execute(
                    text(
                        "select count(*) from information_schema.schemata "
                        "where schema_name like 'v2_eval_%'"
                    )
                ).scalar_one()
            )
    finally:
        engine.dispose()


def build_split_script(case_id: str, payload: dict | None) -> list[ModelResponse]:
    if payload is None:
        return []
    return [
        ModelResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(
                    id=f"{case_id}-split",
                    name="return_text_split",
                    input=payload,
                )
            ],
        )
    ]


def grade(
    expected: dict,
    result,
    species_ids: dict[str, UUID],
    photo_ids: dict[str, UUID],
    split_calls: int,
    photo_calls: list[str],
    counts_before: tuple[int, int, int],
    counts_after: tuple[int, int, int],
) -> list[tuple[str, bool, str]]:
    checks: list[tuple[str, bool, str]] = []

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append((name, bool(passed), detail))

    actual_order = [draft.client_draft_id for draft in result.draft_observations]
    add(
        "draft_order",
        actual_order == expected["draft_order"],
        f"expected={expected['draft_order']} actual={actual_order}",
    )
    drafts_by_id = {
        draft.client_draft_id: draft for draft in result.draft_observations
    }
    for expected_draft in expected["drafts"]:
        draft_id = expected_draft["client_draft_id"]
        draft = drafts_by_id.get(draft_id)
        add(f"{draft_id}.exists", draft is not None)
        if draft is None:
            continue
        for field in (
            "place",
            "obs_date",
            "time_of_day",
            "count",
            "source",
            "species_label",
            "needs_confirmation",
        ):
            if field in expected_draft:
                actual = getattr(draft, field)
                wanted = expected_draft[field]
                add(
                    f"{draft_id}.{field}",
                    actual == wanted,
                    f"expected={wanted!r} actual={actual!r}",
                )
        if "species_key" in expected_draft:
            key = expected_draft["species_key"]
            wanted_species_id = species_ids[key] if key is not None else None
            add(
                f"{draft_id}.species_id",
                draft.species_id == wanted_species_id,
                f"expected={wanted_species_id} actual={draft.species_id}",
            )
        if "photo_keys" in expected_draft:
            wanted_photo_ids = [photo_ids[key] for key in expected_draft["photo_keys"]]
            add(
                f"{draft_id}.photo_ids",
                draft.photo_ids == wanted_photo_ids,
                f"expected={wanted_photo_ids} actual={draft.photo_ids}",
            )
        if "flags_contain" in expected_draft:
            wanted_flags = set(expected_draft["flags_contain"])
            add(
                f"{draft_id}.flags",
                wanted_flags <= set(draft.flags),
                f"expected subset={wanted_flags} actual={draft.flags}",
            )

    actual_unmatched = [
        (link.photo_id, link.client_draft_id) for link in result.unmatched_photos
    ]
    wanted_unmatched = [
        (photo_ids[item["photo_key"]], item["client_draft_id"])
        for item in expected["unmatched"]
    ]
    add(
        "unmatched",
        actual_unmatched == wanted_unmatched,
        f"expected={wanted_unmatched} actual={actual_unmatched}",
    )

    joined_warnings = "\n".join(result.warnings)
    for token in expected["warnings_contain"]:
        add(
            f"warning:{token}",
            token in joined_warnings,
            f"actual={result.warnings}",
        )
    if not expected["warnings_contain"]:
        add("warnings.empty", result.warnings == [], f"actual={result.warnings}")

    add(
        "split_calls",
        split_calls == expected["split_calls"],
        f"expected={expected['split_calls']} actual={split_calls}",
    )
    add(
        "photo_calls",
        len(photo_calls) == expected["photo_calls"],
        f"expected={expected['photo_calls']} actual={photo_calls}",
    )
    add("job_status", result.job_status == "completed", result.job_status)
    add(
        "zero_business_writes",
        counts_after == counts_before == (0, 0, 0),
        f"before={counts_before} after={counts_after}",
    )
    return checks


def run_case(case: dict, expected: dict) -> CaseResult:
    case_id = case["id"]
    try:
        with temporary_schema(f"v2_eval_{case_id}") as session_factory:
            records = TaxonomyService(session_factory).import_entries(CATALOG)
            species_ids = {record.taxonomy_key: record.id for record in records}
            counts_before = business_counts(session_factory)

            with TemporaryDirectory(prefix=f"vibirding-{case_id}-") as temp_dir:
                temp_path = Path(temp_dir)
                provider_results: dict[str, BirdIdResult] = {}
                photo_ids: dict[str, UUID] = {}
                photo_inputs: list[PhotoInput] = []
                for photo_fixture in case.get("photos", []):
                    key = photo_fixture["key"]
                    photo_id = uuid5(NAMESPACE_URL, f"vibirding:{case_id}:{key}")
                    image_path = temp_path / f"{key}.jpg"
                    image_path.write_bytes(
                        b"\xff\xd8\xff\xe0" + f"{case_id}:{key}".encode() + b"\xff\xd9"
                    )
                    photo_ids[key] = photo_id
                    provider_results[key] = BirdIdResult.model_validate(
                        photo_fixture["result"]
                    )
                    photo_inputs.append(
                        PhotoInput(photo_id=photo_id, image_path=str(image_path))
                    )

                llm = CountingMockClient(
                    build_split_script(case_id, case.get("split_payload"))
                )
                identifier = FixtureBirdIdentifier(provider_results)
                drafts = (
                    TextSplitService(llm).split(
                        case["input_text"], reference_date=REFERENCE_DATE
                    )
                    if case["input_text"].strip()
                    else []
                )
                photos = PhotoPreprocessService(identifier).preprocess(photo_inputs)
                result = ParseAssemblyService(
                    DryRunMatchingService(TaxonomyService(session_factory))
                ).assemble(drafts, photos)
                counts_after = business_counts(session_factory)
                checks = grade(
                    expected,
                    result,
                    species_ids,
                    photo_ids,
                    llm.call_count,
                    identifier.calls,
                    counts_before,
                    counts_after,
                )
                return CaseResult(case_id=case_id, checks=checks)
    except Exception as exc:
        return CaseResult(
            case_id=case_id,
            checks=[],
            error=f"{type(exc).__name__}: {exc}",
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="v2 2.6 fixed offline evals for batch parsing and matching"
    )
    parser.add_argument("--ids", help="comma-separated case IDs")
    parser.add_argument("--tasks", default=str(DEFAULT_TASKS))
    parser.add_argument("--answers", default=str(DEFAULT_ANSWERS))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        cases = load_cases(Path(args.tasks), Path(args.answers))
    except (OSError, ValueError, yaml.YAMLError) as exc:
        print(f"无法加载 v2 eval：{exc}")
        return 2

    if args.ids:
        wanted = {item.strip() for item in args.ids.split(",") if item.strip()}
        available = {case["id"] for case, _ in cases}
        unknown = wanted - available
        if unknown:
            print(f"未知 v2 eval ID：{sorted(unknown)}")
            return 2
        cases = [(case, answer) for case, answer in cases if case["id"] in wanted]

    development_before = development_counts()
    schemas_before = eval_schema_count()
    print("=" * 72)
    print(f"v2 2.6 固定 Evals（offline）— 用例 {len(cases)} 条")
    print("=" * 72)

    results = [run_case(case, expected) for case, expected in cases]
    for result in results:
        marker = "PASS" if result.passed else "FAIL"
        print(f"{marker}  {result.case_id}")
        if result.error:
            print(f"        ✗ {result.error}")
        for name, passed, detail in result.checks:
            if not passed:
                print(f"        ✗ {name}: {detail}")

    development_after = development_counts()
    schemas_after = eval_schema_count()
    clean = development_after == development_before and schemas_after == schemas_before
    if not clean:
        print(
            "FAIL  isolation "
            f"development {development_before} -> {development_after}; "
            f"schemas {schemas_before} -> {schemas_after}"
        )

    passed_count = sum(result.passed for result in results)
    print("\n" + "-" * 72)
    print(f"通过率 {passed_count}/{len(results)}")
    print(f"开发库与临时 schema 清理：{'PASS' if clean else 'FAIL'}")
    print("-" * 72)
    return 0 if passed_count == len(results) and clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
