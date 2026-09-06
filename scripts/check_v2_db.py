#!/usr/bin/env python
"""Verify the full Alembic migration chain in a disposable PostgreSQL schema."""

from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateSchema, DropSchema

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding import config as app_config  # noqa: E402
from vibirding.db.models import Base  # noqa: E402
from vibirding.db.session import build_engine  # noqa: E402

EXPECTED_COLUMNS = {
    "id", "sequence_no", "timestamp", "place", "obs_date", "time_of_day",
    "species", "count", "behavior", "raw_note", "confidence", "source",
    "flags", "user_id", "species_id", "session_id",
}
EXPECTED_SPECIES_COLUMNS = {
    "id", "canonical_chinese_name", "scientific_name", "taxonomy_source",
    "taxonomy_key", "aliases",
}
EXPECTED_SESSION_COLUMNS = {"id", "created_at", "raw_text", "status", "user_id"}
EXPECTED_PHOTO_COLUMNS = {
    "id", "content_hash", "storage_path", "original_filename", "mime_type",
    "size_bytes", "species_label", "scientific_name", "confidence",
    "provider_candidate_id", "species_id", "session_id", "observation_id",
}


def _schema_url(database_url: str, schema: str) -> str:
    url = make_url(database_url).update_query_dict(
        {"options": f"-csearch_path={schema}"}
    )
    return url.render_as_string(hide_password=False)


def main() -> int:
    database_url = app_config.load_database_url()
    if not database_url:
        print("FAIL  DATABASE_URL 未设置")
        return 2

    schema = f"migration_{uuid.uuid4().hex}"
    admin_engine = build_engine(database_url)
    old_url = os.environ.get("DATABASE_URL")
    results: list[tuple[str, bool, str]] = []

    def check(name: str, passed: bool, detail: str = "") -> None:
        results.append((name, bool(passed), detail))

    try:
        with admin_engine.begin() as connection:
            connection.execute(CreateSchema(schema))

        isolated_url = _schema_url(database_url, schema)
        os.environ["DATABASE_URL"] = isolated_url
        alembic_config = Config(str(ROOT / "alembic.ini"))
        command.upgrade(alembic_config, "head")

        test_engine = build_engine(isolated_url)
        inspector = inspect(test_engine)
        tables = set(inspector.get_table_names())
        columns = {column["name"]: column for column in inspector.get_columns("observations")}
        species_columns = {
            column["name"]: column for column in inspector.get_columns("species")
        }
        session_columns = {
            column["name"]: column for column in inspector.get_columns("sessions")
        }
        photo_columns = {
            column["name"]: column for column in inspector.get_columns("photos")
        }
        orm_columns = set(Base.metadata.tables["observations"].columns.keys())
        orm_species_columns = set(Base.metadata.tables["species"].columns.keys())
        orm_session_columns = set(Base.metadata.tables["sessions"].columns.keys())
        orm_photo_columns = set(Base.metadata.tables["photos"].columns.keys())
        with test_engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        check("migration 到达 0003 head", revision == "0003", str(revision))
        check("创建 observations 表", "observations" in tables, str(tables))
        check("创建 species 表", "species" in tables, str(tables))
        check("创建 sessions/photos 表", {"sessions", "photos"}.issubset(tables), str(tables))
        check("migration 列集合正确", set(columns) == EXPECTED_COLUMNS, str(set(columns)))
        check("migration 与 ORM 列一致", set(columns) == orm_columns, str(orm_columns))
        check(
            "species migration 列集合正确",
            set(species_columns) == EXPECTED_SPECIES_COLUMNS,
            str(set(species_columns)),
        )
        check(
            "species migration 与 ORM 列一致",
            set(species_columns) == orm_species_columns,
            str(orm_species_columns),
        )
        check("sessions migration 列集合正确", set(session_columns) == EXPECTED_SESSION_COLUMNS, str(set(session_columns)))
        check("sessions migration 与 ORM 列一致", set(session_columns) == orm_session_columns, str(orm_session_columns))
        check("photos migration 列集合正确", set(photo_columns) == EXPECTED_PHOTO_COLUMNS, str(set(photo_columns)))
        check("photos migration 与 ORM 列一致", set(photo_columns) == orm_photo_columns, str(orm_photo_columns))
        check("id 使用 UUID", columns["id"]["type"].__class__.__name__ == "UUID")
        check("flags 使用 JSONB", columns["flags"]["type"].__class__.__name__ == "JSONB")
        check("flags 默认空 JSONB", "[]" in str(columns["flags"].get("default")))
        check("sequence_no 是 identity", columns["sequence_no"].get("identity") is not None)
        check("raw_note/source 非空",
              not columns["raw_note"]["nullable"] and not columns["source"]["nullable"])
        check("species.aliases 使用 JSONB", species_columns["aliases"]["type"].__class__.__name__ == "JSONB")
        check("observations.species_id 可空", columns["species_id"]["nullable"] is True)
        foreign_keys = inspector.get_foreign_keys("observations")
        species_fk = next(
            (fk for fk in foreign_keys if fk["constrained_columns"] == ["species_id"]),
            None,
        )
        check(
            "species_id 外键 ON DELETE SET NULL",
            species_fk is not None
            and species_fk["referred_table"] == "species"
            and species_fk.get("options", {}).get("ondelete") == "SET NULL",
            str(species_fk),
        )
        observation_fks = {tuple(fk["constrained_columns"]): fk for fk in foreign_keys}
        check(
            "observations.session_id 外键 ON DELETE SET NULL",
            ("session_id",) in observation_fks
            and observation_fks[("session_id",)]["referred_table"] == "sessions"
            and observation_fks[("session_id",)].get("options", {}).get("ondelete") == "SET NULL",
            str(observation_fks.get(("session_id",))),
        )
        photo_fks = {tuple(fk["constrained_columns"]): fk for fk in inspector.get_foreign_keys("photos")}
        check("photos 三个外键存在", set(photo_fks) == {("species_id",), ("session_id",), ("observation_id",)}, str(photo_fks))
        photo_uniques = inspector.get_unique_constraints("photos")
        check("photos.content_hash 唯一", any(item["column_names"] == ["content_hash"] for item in photo_uniques), str(photo_uniques))

        command.downgrade(alembic_config, "base")
        inspector = inspect(test_engine)
        remaining = set(inspector.get_table_names())
        check("downgrade 删除全部业务表", not {"observations", "species", "sessions", "photos"} & remaining, str(remaining))
        test_engine.dispose()
    finally:
        if old_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = old_url
        with admin_engine.begin() as connection:
            connection.execute(DropSchema(schema, cascade=True, if_exists=True))
        admin_engine.dispose()

    print("=" * 72)
    print("v2 PostgreSQL migration 验证 — 临时 schema")
    print("=" * 72)
    passed = 0
    for name, ok, detail in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" <- {detail}" if not ok else ""))
        passed += ok
    print("-" * 72)
    print(f"通过 {passed}/{len(results)}")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
