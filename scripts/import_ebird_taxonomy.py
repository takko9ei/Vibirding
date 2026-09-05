#!/usr/bin/env python
"""Fetch the current eBird species taxonomy and upsert it into PostgreSQL."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.db.session import build_session_factory  # noqa: E402
from vibirding.services.taxonomy import (  # noqa: E402
    EbirdTaxonomyAdapter,
    TaxonomyService,
)


def main() -> int:
    entries = EbirdTaxonomyAdapter().fetch_entries()
    records = TaxonomyService(build_session_factory()).import_entries(entries)
    print(f"eBird 物种名录导入完成：{len(records)} 条 species。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
