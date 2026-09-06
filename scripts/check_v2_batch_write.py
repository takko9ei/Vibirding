#!/usr/bin/env python
"""Offline PostgreSQL verification for v2 slice 2.4 batch confirmation."""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pydantic import ValidationError  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.db.models import ObservationRow, PhotoRow, SessionRow  # noqa: E402
from vibirding.db.repository import PhotoRepository  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    BirdIdCandidate,
    ConfirmedBatch,
    DraftObservation,
    PhotoMetadataInput,
    SpeciesCatalogEntry,
)
from vibirding.services.batch import (  # noqa: E402
    BatchConfirmationError,
    BatchMediaError,
    BatchWriteService,
)
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def uid(number: int) -> UUID:
    return UUID(int=number)


def metadata(number: int) -> PhotoMetadataInput:
    return PhotoMetadataInput(
        photo_id=uid(number),
        content_hash=f"{number:064x}",
        storage_path=f"media/{number:064x}.jpg",
        original_filename=f"photo-{number}.jpg",
        mime_type="image/jpeg",
        size_bytes=100 + number,
        candidate=BirdIdCandidate(
            species_label="灰喜鹊",
            scientific_name="Cyanopica cyanus",
            confidence=95,
            provider_candidate_id="101",
        ),
    )


def draft(
    draft_id: str,
    species_id: UUID | None,
    photo_ids: list[UUID] | None = None,
) -> DraftObservation:
    return DraftObservation(
        client_draft_id=draft_id,
        place="井之头公园",
        obs_date="2026-09-05",
        species_label="灰喜鹊",
        species_id=species_id,
        count=3,
        raw_note=f"{draft_id} 原文",
        source="user",
        photo_ids=photo_ids or [],
    )


def row_count(session_factory, model) -> int:
    with session_factory() as session:
        return session.scalar(select(func.count()).select_from(model)) or 0


fixed_now = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)

with temporary_schema("batch") as session_factory:
    taxonomy = TaxonomyService(session_factory)
    species = taxonomy.import_entries(
        [
            SpeciesCatalogEntry(
                taxonomy_source="ebird",
                taxonomy_key="azwmag2",
                canonical_chinese_name="灰喜鹊",
                scientific_name="Cyanopica cyanus",
            )
        ]
    )[0]
    with session_factory.begin() as session:
        repository = PhotoRepository(session)
        for number in range(1, 9):
            repository.add(metadata(number))

    service = BatchWriteService(session_factory, now=lambda: fixed_now)

    # Not confirmed: fail before opening a transaction or claiming media.
    unconfirmed = ConfirmedBatch(
        raw_text="未确认批次",
        media_ids=[uid(1)],
        observations=[draft("draft-u", species.id, [uid(1)])],
        confirmed=False,
    )
    sessions_before = row_count(session_factory, SessionRow)
    observations_before = row_count(session_factory, ObservationRow)
    try:
        service.confirm(unconfirmed)
        unconfirmed_rejected = False
    except BatchConfirmationError:
        unconfirmed_rejected = True
    check("未确认请求被服务层拒绝", unconfirmed_rejected)
    check("未确认不创建 session", row_count(session_factory, SessionRow) == sessions_before)
    check("未确认不创建 observation", row_count(session_factory, ObservationRow) == observations_before)
    with session_factory() as session:
        check("未确认不认领照片", session.get(PhotoRow, uid(1)).session_id is None)

    # Fully successful confirmation: two observations and two photos on one draft.
    completed = service.confirm(
        ConfirmedBatch(
            raw_text="  完整成功批次\n",
            media_ids=[uid(1), uid(2)],
            observations=[
                draft("draft-1", species.id, [uid(1), uid(2)]),
                draft("draft-2", species.id),
            ],
            confirmed=True,
            user_id=uid(900),
        )
    )
    check("全成功 created 两条", len(completed.created) == 2)
    check("全成功 failed 仍存在且为空", completed.failed == [])
    with session_factory() as session:
        session_row = session.get(SessionRow, completed.session_id)
        observations = session.scalars(
            select(ObservationRow).where(
                ObservationRow.session_id == completed.session_id
            )
        ).all()
        photo_rows = [session.get(PhotoRow, uid(1)), session.get(PhotoRow, uid(2))]
        first_observation_id = completed.created[0].observation_id
        check("全成功 session 状态 completed", session_row.status == "completed")
        check("session 保存原始整篇文本", session_row.raw_text == "  完整成功批次\n")
        check("session 保存 UTC 创建时间", session_row.created_at == fixed_now)
        check("成功 observations 全部关联 session", len(observations) == 2)
        check("user_id 下发到每条 observation", all(row.user_id == uid(900) for row in observations))
        check("species_id 和兼容显示名同时保存", all(row.species_id == species.id and row.species == "灰喜鹊" for row in observations))
        check("同一草稿的多张照片关联同一 observation", all(row.observation_id == first_observation_id for row in photo_rows))
        check("本批照片全部关联 session", all(row.session_id == completed.session_id for row in photo_rows))

    # Partial success: unknown species and a photo already claimed earlier in this batch.
    partial = service.confirm(
        ConfirmedBatch(
            raw_text="部分成功批次",
            media_ids=[uid(3), uid(4)],
            observations=[
                draft("draft-3", species.id, [uid(3)]),
                draft("draft-4", uuid4(), [uid(4)]),
                draft("draft-5", species.id, [uid(3)]),
                draft("draft-6", species.id),
            ],
            confirmed=True,
        )
    )
    check("部分成功 created/failed 同时返回", len(partial.created) == 2 and len(partial.failed) == 2)
    check("成功与失败保持草稿顺序", [item.client_draft_id for item in partial.created] == ["draft-3", "draft-6"] and [item.client_draft_id for item in partial.failed] == ["draft-4", "draft-5"])
    check("逐条失败原因精确返回", "species_id" in partial.failed[0].reason and "认领" in partial.failed[1].reason)
    with session_factory() as session:
        session_row = session.get(SessionRow, partial.session_id)
        photo3 = session.get(PhotoRow, uid(3))
        photo4 = session.get(PhotoRow, uid(4))
        check("部分成功 session 状态 partial", session_row.status == "partial")
        check("成功草稿的照片正常落盘", photo3.observation_id == partial.created[0].observation_id)
        check("失败草稿的照片不关联 observation", photo4.observation_id is None)
        check("失败草稿的照片仍属于已确认 session", photo4.session_id == partial.session_id)

    # All item failures still preserve the confirmed audit session.
    all_failed = service.confirm(
        ConfirmedBatch(
            raw_text="全部失败批次",
            media_ids=[uid(5)],
            observations=[draft("draft-7", uuid4(), [uid(5)])],
            confirmed=True,
        )
    )
    check("全部失败 created 为空且 failed 非空", all_failed.created == [] and len(all_failed.failed) == 1)
    with session_factory() as session:
        check("全部失败 session 状态 failed", session.get(SessionRow, all_failed.session_id).status == "failed")
        check("全部失败仍不产生 observation 关联", session.get(PhotoRow, uid(5)).observation_id is None)

    # A draft may fail for referring to a photo outside the confirmed media set.
    outside = service.confirm(
        ConfirmedBatch(
            raw_text="越界照片批次",
            media_ids=[uid(6)],
            observations=[draft("draft-8", species.id, [uid(7)])],
            confirmed=True,
        )
    )
    check("草稿引用批次外照片只失败该条", outside.created == [] and "之外" in outside.failed[0].reason)
    with session_factory() as session:
        check("批次内未使用照片仍记录 session", session.get(PhotoRow, uid(6)).session_id == outside.session_id)
        check("批次外照片完全未被触碰", session.get(PhotoRow, uid(7)).session_id is None)

    # Unknown/already-owned media are batch-level failures and roll back session creation.
    sessions_before = row_count(session_factory, SessionRow)
    try:
        service.confirm(
            ConfirmedBatch(
                raw_text="未知媒体",
                media_ids=[uid(999)],
                observations=[draft("draft-9", species.id)],
                confirmed=True,
            )
        )
        unknown_media_rejected = False
    except BatchMediaError:
        unknown_media_rejected = True
    check("未知 media_id 整批拒绝", unknown_media_rejected)
    check("未知媒体失败回滚 session", row_count(session_factory, SessionRow) == sessions_before)

    try:
        service.confirm(
            ConfirmedBatch(
                raw_text="重复使用媒体",
                media_ids=[uid(1)],
                observations=[draft("draft-10", species.id)],
                confirmed=True,
            )
        )
        owned_media_rejected = False
    except BatchMediaError:
        owned_media_rejected = True
    check("已属于其他 session 的照片整批拒绝", owned_media_rejected)
    check("已认领媒体失败不创建新 session", row_count(session_factory, SessionRow) == sessions_before)

    # Ambiguous batch identity is rejected before database work.
    duplicate_cases = [
        ConfirmedBatch(
            raw_text="重复 media",
            media_ids=[uid(8), uid(8)],
            observations=[draft("draft-11", species.id)],
            confirmed=True,
        ),
        ConfirmedBatch(
            raw_text="重复 draft",
            media_ids=[],
            observations=[draft("same", species.id), draft("same", species.id)],
            confirmed=True,
        ),
    ]
    duplicate_results = []
    for case in duplicate_cases:
        try:
            service.confirm(case)
            duplicate_results.append(False)
        except BatchConfirmationError:
            duplicate_results.append(True)
    check("重复 media/draft ID 都在事务前拒绝", duplicate_results == [True, True])
    check("重复 ID 不创建 session", row_count(session_factory, SessionRow) == sessions_before)

    try:
        ConfirmedBatch(
            raw_text="非严格确认",
            observations=[draft("draft-12", species.id)],
            confirmed="yes",
        )
        strict_confirmation = False
    except ValidationError:
        strict_confirmation = True
    check("confirmed 不接受字符串等宽松真值", strict_confirmation)

    try:
        ConfirmedBatch(raw_text="空列表", observations=[], confirmed=True)
        empty_rejected = False
    except ValidationError:
        empty_rejected = True
    check("空 observations 在进入服务前拒绝", empty_rejected)


def main() -> int:
    print("=" * 72)
    print("v2 2.4 批量确认写入验证 — PostgreSQL 临时 schema")
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
