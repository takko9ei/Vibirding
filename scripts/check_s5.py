#!/usr/bin/env python
"""S5 verification suite (offline) — memory/log + append_log + permission gate.

Dev-time only. Fully offline: no network, no real model, no API key. Every case
uses a throwaway temp-dir JSONL (never the real data/observations.jsonl) and an
INJECTED auto-policy approver (allow / deny / always) — never stdin. The real
end-to-end model run is covered separately by scripts/run_s5.py.

Run:
    .venv/Scripts/python.exe scripts/check_s5.py

Exits non-zero if any case fails.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import Observation  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.registry import Tool, ToolContext, ToolManager  # noqa: E402

_RESULTS: list[tuple[str, str, bool, str]] = []
_BASE = Path(tempfile.mkdtemp(prefix="vibirding_s5_"))  # one throwaway dir per run
_N = 0  # unique-path counter


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


def _new_path(sub: bool = False) -> Path:
    """A fresh, not-yet-existing JSONL path under the temp dir.

    sub=True nests it under a not-yet-created subdir (to test auto-create).
    """
    global _N
    _N += 1
    return (_BASE / f"sub_{_N}" / "log.jsonl") if sub else (_BASE / f"log_{_N}.jsonl")


def _inp(**over) -> dict:
    """An append_log input dict (Observation fields MINUS id/timestamp)."""
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
    """A full Observation (machine fields filled) for direct Log.append tests."""
    data = _inp(**over)
    data.setdefault("id", "testid01")
    data.setdefault("timestamp", "2025-06-01T00:00:00+00:00")
    return Observation.model_validate(data)


def _lines(path: Path) -> int:
    if not path.exists():
        return 0
    return len([ln for ln in path.read_text(encoding="utf-8").splitlines() if ln.strip()])


def _allow(*a, **k) -> str:
    return "allow"


def _deny(*a, **k) -> str:
    return "deny"


# ── A. append_log Tool protocol ──────────────────────────────────────────────
tool = AppendLogTool(Log(_new_path()))
check("protocol", "满足 Tool 协议 (六件套)", isinstance(tool, Tool))
check("protocol", "risk == 'write'", tool.risk == "write")
check("protocol", "input_schema 必填 raw_note+source",
      tool.input_schema["required"] == ["raw_note", "source"])
check("protocol", "input_schema 不暴露 id/timestamp",
      "id" not in tool.input_schema["properties"]
      and "timestamp" not in tool.input_schema["properties"])


# ── B. Log append / query round-trip + filters ───────────────────────────────
log = Log(_new_path())
log.append(_obs(species="黑翅长脚鹬", place="葛西临海公园", obs_date="2025-06-01"))
log.append(_obs(species="白鹭", place="城北湿地", obs_date="2024-01-15"))
allrows = log.query()
check("log", "往返：写2条 → query 取回2条", len(allrows) == 2, str(len(allrows)))
check("log", "字段一致 (species 回得来)",
      {r.species for r in allrows} == {"黑翅长脚鹬", "白鹭"})
check("log", "按 place 子串过滤", [r.species for r in log.query(place="城北")] == ["白鹭"])
check("log", "按 species 子串过滤", [r.place for r in log.query(species="长脚")] == ["葛西临海公园"])
check("log", "按 date_range 过滤 (只取2025)",
      [r.species for r in log.query(date_range="2025-01-01..2025-12-31")] == ["黑翅长脚鹬"])
check("log", "无匹配 → []", log.query(place="火星") == [])
check("log", "文件不存在 → []", Log(_new_path()).query() == [])


# ── C. append-only guarantee ─────────────────────────────────────────────────
log = Log(_new_path())
log.append(_obs(species="苍鹰", id="first001"))
first_line = log.path.read_text(encoding="utf-8")  # exactly one line so far
log.append(_obs(species="蓝矶鸫", id="second02"))
after = log.path.read_text(encoding="utf-8").splitlines()
check("append-only", "历史首行逐字节不变", after[0] + "\n" == first_line, after[0][:30])
check("append-only", "写2条 → 共2行", len(after) == 2, str(len(after)))


# ── D. directory auto-create ─────────────────────────────────────────────────
nested = Log(_new_path(sub=True))
check("autocreate", "目标父目录原本不存在", not nested.path.parent.exists())
nested.append(_obs())
check("autocreate", "append 后文件已建", nested.path.exists())


# ── E. append_log via registry (allow) + machine fields filled ───────────────
log = Log(_new_path())
reg = ToolManager()
reg.register(AppendLogTool(log))
ctx_allow = ToolContext(permissions=Permissions(approver=_allow))
res = reg.execute("append_log", _inp(species="戴胜"), ctx_allow)
check("append_log", "允许 → ok=True + '已写入'", res.ok and "已写入" in res.output, res.output[:40])
check("append_log", "确实落盘 1 行", _lines(log.path) == 1, str(_lines(log.path)))
back = log.query()[0]
check("append_log", "工具补了 id (非空)", bool(back.id))
check("append_log", "工具补了 timestamp (非空)", bool(back.timestamp))
check("append_log", "model 字段写对 (species=戴胜)", back.species == "戴胜")


# ── F. permission DENY path (registry write→permissions branch fires) ────────
log = Log(_new_path())
reg = ToolManager()
reg.register(AppendLogTool(log))
ctx_deny = ToolContext(permissions=Permissions(approver=_deny))
res = reg.execute("append_log", _inp(), ctx_deny)
check("deny", "拒绝 → ok=False + 'permission denied'",
      (not res.ok) and "permission denied" in res.output, res.output[:40])
check("deny", "拒绝后未写盘 (0 行)", _lines(log.path) == 0, str(_lines(log.path)))


# ── G. permission ALWAYS (本回合一直允许，只问一次) ──────────────────────────
log = Log(_new_path())
reg = ToolManager()
reg.register(AppendLogTool(log))
_calls = {"n": 0}


def _always(name, risk, inp):
    _calls["n"] += 1
    return "always"


ctx_always = ToolContext(permissions=Permissions(approver=_always))
r1 = reg.execute("append_log", _inp(species="A"), ctx_always)
r2 = reg.execute("append_log", _inp(species="B"), ctx_always)
check("always", "两次写入都成功", r1.ok and r2.ok)
check("always", "共写 2 行", _lines(log.path) == 2, str(_lines(log.path)))
check("always", "回调只被调用 1 次 (后续不再问)", _calls["n"] == 1, str(_calls["n"]))


# ── H. fail-closed default + read→allow ──────────────────────────────────────
check("default", "无回调 write → deny", Permissions().check("append_log", "write", {}) == "deny")
check("default", "read → allow", Permissions().check("read_log", "read", {}) == "allow")


# ── I. read_log real read ────────────────────────────────────────────────────
log = Log(_new_path())
log.append(_obs(species="黑翅长脚鹬", place="葛西临海公园"))
rl = ReadLogTool(log)
ctx_read = ToolContext(permissions=Permissions())
hit = rl.run({"place": "葛西"}, ctx_read)
miss = rl.run({"place": "火星"}, ctx_read)
check("read_log", "命中 → 含已写入的种", hit.ok and "黑翅长脚鹬" in hit.output, hit.output[:40])
check("read_log", "无匹配 → 占位文本", miss.ok and "无匹配" in miss.output, miss.output[:40])


# ── J. input validation via registry ─────────────────────────────────────────
reg = ToolManager()
reg.register(AppendLogTool(Log(_new_path())))
res = reg.execute("append_log", {}, ctx_allow)  # missing required raw_note+source
check("validate", "缺 raw_note/source → 'invalid input'",
      (not res.ok) and "invalid input" in res.output, res.output[:40])
check("validate", "specs() 含 append_log", any(s["name"] == "append_log" for s in reg.specs()))


# ── print table + cleanup ────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("S5 验证套件（离线）— 无网络、无 key、无真实模型、临时目录 jsonl")
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
    shutil.rmtree(_BASE, ignore_errors=True)  # remove the throwaway temp dir
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
