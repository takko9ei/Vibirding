#!/usr/bin/env python
"""Verify the initial Alembic migration in a disposable PostgreSQL schema."""

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
    "flags", "user_id",
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
        orm_columns = set(Base.metadata.tables["observations"].columns.keys())
        with test_engine.connect() as connection:
            revision = connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()

        check("migration 到达 0001 head", revision == "0001", str(revision))
        check("创建 observations 表", "observations" in tables, str(tables))
        check("migration 列集合正确", set(columns) == EXPECTED_COLUMNS, str(set(columns)))
        check("migration 与 ORM 列一致", set(columns) == orm_columns, str(orm_columns))
        check("id 使用 UUID", columns["id"]["type"].__class__.__name__ == "UUID")
        check("flags 使用 JSONB", columns["flags"]["type"].__class__.__name__ == "JSONB")
        check("flags 默认空 JSONB", "[]" in str(columns["flags"].get("default")))
        check("sequence_no 是 identity", columns["sequence_no"].get("identity") is not None)
        check("raw_note/source 非空",
              not columns["raw_note"]["nullable"] and not columns["source"]["nullable"])

        command.downgrade(alembic_config, "base")
        inspector = inspect(test_engine)
        check("downgrade 删除 observations", "observations" not in inspector.get_table_names())
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
