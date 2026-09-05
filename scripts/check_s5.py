#!/usr/bin/env python
"""S5 compatibility verification against isolated PostgreSQL schemas.

The suite is offline with respect to models and external APIs, but it requires
the local PostgreSQL container and DATABASE_URL. Every Log gets a fresh schema;
no case can read or mutate development observations.
"""

from __future__ import annotations

import sys
import uuid
from datetime import datetime
from pathlib import Path

from sqlalchemy.exc import IntegrityError

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from scripts.db_test_support import new_test_log  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.schemas import Observation  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.registry import Tool, ToolContext, ToolManager  # noqa: E402

_RESULTS: list[tuple[str, str, bool, str]] = []


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


def _inp(**over) -> dict:
    base = {
        "place": "葛西临海公园",
        "obs_date": "2025-06-01",
        "species": "黑翅长脚鹬",
        "count": 5,
        "raw_note": "原始笔记",
        "source": "inferred",
    }
    base.update(over)
    return base


def _obs(**over) -> Observation:
    data = _inp(**over)
    data.setdefault("id", str(uuid.uuid4()))
    data.setdefault("timestamp", "2025-06-01T00:00:00+00:00")
    return Observation.model_validate(data)


def _allow(*args, **kwargs) -> str:
    return "allow"


def _deny(*args, **kwargs) -> str:
    return "deny"


# ── A. append_log Tool protocol remains unchanged ───────────────────────────
tool = AppendLogTool(new_test_log("s5_protocol"))
check("protocol", "满足 Tool 协议 (六件套)", isinstance(tool, Tool))
check("protocol", "risk == 'write'", tool.risk == "write")
check("protocol", "input_schema 必填 raw_note+source",
      tool.input_schema["required"] == ["raw_note", "source"])
check("protocol", "input_schema 不暴露 id/timestamp",
      "id" not in tool.input_schema["properties"]
      and "timestamp" not in tool.input_schema["properties"])


# ── B. Log round-trip and exact legacy filtering semantics ──────────────────
log = new_test_log("s5_query")
log.append(_obs(species="黑翅长脚鹬", place="葛西%_临海公园", obs_date="2025-06-01"))
log.append(_obs(species="白鹭", place="城北湿地", obs_date="2024-01-15"))
allrows = log.query()
check("log", "往返：写2条 → query 取回2条", len(allrows) == 2, str(len(allrows)))
check("log", "字段一致", {r.species for r in allrows} == {"黑翅长脚鹬", "白鹭"})
check("log", "维持插入顺序", [r.species for r in allrows] == ["黑翅长脚鹬", "白鹭"])
check("log", "按 place 子串过滤", [r.species for r in log.query(place="城北")] == ["白鹭"])
check("log", "按 species 子串过滤", [r.place for r in log.query(species="长脚")] == ["葛西%_临海公园"])
check("log", "按 date_range 过滤",
      [r.species for r in log.query(date_range="2025-01-01..2025-12-31")]
      == ["黑翅长脚鹬"])
check("log", "无 '..' 不做日期过滤", len(log.query(date_range="2025")) == 2)
check("log", "无匹配 → []", log.query(place="火星") == [])
check("log", "空库 → []", new_test_log("s5_empty").query() == [])
check("log", "%/_ 按普通字符匹配",
      len(log.query(place="%_")) == 1 and log.query(place="%_")[0].species == "黑翅长脚鹬")
edge_log = new_test_log("s5_query_edges")
edge_log.append(_obs(place="Kasai", obs_date=None, species="Sparrow"))
check("log", "子串过滤大小写敏感", edge_log.query(place="kasai") == [])
check("log", "真实日期范围排除 NULL obs_date",
      edge_log.query(date_range="2025-01-01..2025-12-31") == [])


# ── C. PostgreSQL types and transaction rollback ────────────────────────────
typed = new_test_log("s5_types")
typed.append(_obs(flags=["season_unusual", "low_confidence"]))
back = typed.query()[0]
check("database", "UUID 完整往返", str(uuid.UUID(back.id)) == back.id)
check("database", "flags JSONB 列表往返", back.flags == ["season_unusual", "low_confidence"])
check("database", "TIMESTAMPTZ 往返", datetime.fromisoformat(back.timestamp).tzinfo is not None)

transactional = new_test_log("s5_transaction")
same_id = str(uuid.uuid4())
transactional.append(_obs(id=same_id, species="甲"))
try:
    transactional.append(_obs(id=same_id, species="重复"))
    duplicate_failed = False
except IntegrityError:
    duplicate_failed = True
check("transaction", "重复 UUID 事务失败", duplicate_failed)
check("transaction", "失败事务未污染已有记录",
      [r.species for r in transactional.query()] == ["甲"])
transactional.append(_obs(species="乙"))
check("transaction", "失败后仍可开启新事务",
      [r.species for r in transactional.query()] == ["甲", "乙"])


# ── D. append_log via registry, including full machine UUID ─────────────────
log = new_test_log("s5_append_tool")
registry = ToolManager(); registry.register(AppendLogTool(log))
ctx_allow = ToolContext(permissions=Permissions(approver=_allow))
result = registry.execute("append_log", _inp(species="戴胜"), ctx_allow)
check("append_log", "允许 → ok=True + '已写入'", result.ok and "已写入" in result.output)
check("append_log", "确实落库 1 条", len(log.query()) == 1)
back = log.query()[0]
check("append_log", "工具补了完整 UUID", str(uuid.UUID(back.id)) == back.id)
check("append_log", "工具补了 timestamp", bool(back.timestamp))
check("append_log", "模型字段写对", back.species == "戴胜")


# ── E. permission behavior remains unchanged ────────────────────────────────
log = new_test_log("s5_deny")
registry = ToolManager(); registry.register(AppendLogTool(log))
ctx_deny = ToolContext(permissions=Permissions(approver=_deny))
result = registry.execute("append_log", _inp(), ctx_deny)
check("deny", "拒绝 → ok=False + permission denied",
      (not result.ok) and "permission denied" in result.output)
check("deny", "拒绝后未落库", log.query() == [])

log = new_test_log("s5_always")
registry = ToolManager(); registry.register(AppendLogTool(log))
calls = {"n": 0}


def _always(name, risk, inp):
    calls["n"] += 1
    return "always"


ctx_always = ToolContext(permissions=Permissions(approver=_always))
r1 = registry.execute("append_log", _inp(species="A"), ctx_always)
r2 = registry.execute("append_log", _inp(species="B"), ctx_always)
check("always", "两次写入都成功", r1.ok and r2.ok)
check("always", "共写 2 条", len(log.query()) == 2)
check("always", "回调只调用 1 次", calls["n"] == 1)

check("default", "无回调 write → deny",
      Permissions().check("append_log", "write", {}) == "deny")
check("default", "read → allow",
      Permissions().check("read_log", "read", {}) == "allow")


# ── F. read_log formatting and registry validation remain unchanged ─────────
log = new_test_log("s5_read")
log.append(_obs(species="黑翅长脚鹬", place="葛西临海公园"))
read_tool = ReadLogTool(log)
ctx_read = ToolContext(permissions=Permissions())
hit = read_tool.run({"place": "葛西"}, ctx_read)
miss = read_tool.run({"place": "火星"}, ctx_read)
check("read_log", "命中 → 含已写入的种", hit.ok and "黑翅长脚鹬" in hit.output)
check("read_log", "无匹配 → 占位文本", miss.ok and "无匹配" in miss.output)

registry = ToolManager(); registry.register(AppendLogTool(new_test_log("s5_validate")))
result = registry.execute("append_log", {}, ctx_allow)
check("validate", "缺 raw_note/source → invalid input",
      (not result.ok) and "invalid input" in result.output)
check("validate", "specs() 含 append_log",
      any(spec["name"] == "append_log" for spec in registry.specs()))


def main() -> int:
    print("=" * 72)
    print("S5 兼容验证 — PostgreSQL 临时 schema、无网络、无真实模型")
    print("=" * 72)
    current = None
    passed = 0
    for group, name, ok, detail in _RESULTS:
        if group != current:
            print(f"\n[{group}]")
            current = group
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
