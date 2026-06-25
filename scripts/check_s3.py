#!/usr/bin/env python
"""S3 verification suite (offline part) — range_check without any network.

Dev-time only. Fully offline: no eBird call, no real model, no API key needed.
Covers the parts we CAN test without the network — place resolution, the pure
formatter (dedup / Chinese names / empty / truncation), the unknown-place and
missing-key fallbacks, schema validation, and registry wiring. The real eBird
call and the end-to-end model run are exercised separately by scripts/run_s3.py.

As a safety net we monkeypatch httpx.get to blow up, so any case that
accidentally reaches the network fails loudly instead of going online.

Run:
    .venv/Scripts/python.exe scripts/check_s3.py

Exits non-zero if any case fails.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx  # noqa: E402

from vibirding import config  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.tools import range_check as rc  # noqa: E402
from vibirding.tools.locations import PLACE_COORDS, resolve_place  # noqa: E402
from vibirding.tools.range_check import (  # noqa: E402
    _MAX_SPECIES_SHOWN,
    RangeCheckTool,
    _format_species,
)
from vibirding.tools.registry import Tool, ToolContext, ToolRegistry  # noqa: E402


# --- offline guarantee: any real HTTP call must fail loudly ---
def _no_network(*args, **kwargs):
    raise AssertionError("network call attempted in offline check!")


httpx.get = _no_network  # range_check uses module-level httpx.get

_RESULTS: list[tuple[str, str, bool, str]] = []  # (group, name, passed, detail)


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


_CTX = ToolContext(permissions=Permissions())


# ── A. range_check satisfies the Tool protocol (§6) ──────────────────────────
tool = RangeCheckTool()
check("protocol", "满足 Tool 协议 (六件套齐全)", isinstance(tool, Tool))
check("protocol", "risk == 'read' (跳过权限闸)", tool.risk == "read")
check("protocol", "input_schema 必填 place", tool.input_schema["required"] == ["place"])


# ── B. locations.resolve_place ───────────────────────────────────────────────
check("locations", "已知地点 → 坐标元组",
      resolve_place("葛西临海公园") == PLACE_COORDS["葛西临海公园"])
check("locations", "前后空白被 strip", resolve_place("  葛西临海公园 ") is not None)
check("locations", "未知地点 → None", resolve_place("火星") is None)
check("locations", "None 输入 → None", resolve_place(None) is None)
check("locations", "空串 → None", resolve_place("") is None)


# ── C. _format_species (pure: dedup / 中文名 / 空 / 截断) ─────────────────────
fake = [
    {"speciesCode": "bkwsti", "comName": "黑翅长脚鹬", "sciName": "Himantopus himantopus"},
    {"speciesCode": "bkwsti", "comName": "黑翅长脚鹬", "sciName": "Himantopus himantopus"},  # dup
    {"speciesCode": "litegr", "comName": "小白鹭", "sciName": "Egretta garzetta"},
]
out = _format_species(fake, "葛西临海公园", "2026-06-24")
check("format", "按 speciesCode 去重 (共 2 种)", "共 2 种" in out, out[:40])
check("format", "含中文俗名", "黑翅长脚鹬" in out and "小白鹭" in out)
check("format", "含学名", "Himantopus himantopus" in out)
check("format", "回填 date", "date=2026-06-24" in out)

empty = _format_species([], "葛西临海公园", None)
check("format", "空清单 → '无记录' (合法结果)", "无记录" in empty, empty[:40])

many = [
    {"speciesCode": f"sp{i:03d}", "comName": f"鸟{i}", "sciName": f"Genus species{i}"}
    for i in range(_MAX_SPECIES_SHOWN + 20)
]
big = _format_species(many, "某地", "2026-06-24")
check("format", f"超 {_MAX_SPECIES_SHOWN} 种 → 截断且报总数",
      f"共 {_MAX_SPECIES_SHOWN + 20} 种" in big and "未列出" in big)
check("format", "截断后展示数 == 上限",
      big.count("（Genus species") == _MAX_SPECIES_SHOWN, str(big.count("（Genus species")))


# ── D. run() pre-network branches (no network reached) ───────────────────────
reg = ToolRegistry()
reg.register(tool)

# unknown place -> graceful degrade, ok=True (NOT an error)
res = reg.execute("range_check", {"place": "火星", "date": "2026-06-24"}, _CTX)
check("degrade", "未知地点 → ok=True + 引导文本",
      res.ok is True and "未知地点" in res.output, res.output[:48])

# missing key on a KNOWN place -> ok=False before any network call
_orig = config.load_ebird_api_key
config.load_ebird_api_key = lambda: None  # type: ignore[assignment]
try:
    res = reg.execute("range_check", {"place": "葛西临海公园", "date": "2026-06-24"}, _CTX)
finally:
    config.load_ebird_api_key = _orig  # type: ignore[assignment]
check("degrade", "缺 key (已知地点) → ok=False + 提示",
      res.ok is False and "EBIRD_API_KEY" in res.output, res.output[:48])


# ── E. schema validation via registry (place 必填) ───────────────────────────
res = reg.execute("range_check", {}, _CTX)  # no place
check("registry", "缺 place → ok=False + 'invalid input'",
      res.ok is False and "invalid input" in res.output, res.output[:48])
check("registry", "specs() 含 range_check",
      any(s["name"] == "range_check" for s in reg.specs()))


# ── print table ──────────────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("S3 验证套件（离线部分）— 无网络、无 key、无真实模型")
    print("=" * 72)
    cur = None
    passed = 0
    for group, name, ok, detail in _RESULTS:
        if group != cur:
            print(f"\n[{group}]")
            cur = group
        mark = "PASS" if ok else "FAIL"
        line = f"  {mark}  {name}"
        if not ok and detail:
            line += f"   <- {detail}"
        print(line)
        passed += ok
    total = len(_RESULTS)
    print("\n" + "-" * 72)
    print(f"通过 {passed}/{total}")
    print("-" * 72)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
