#!/usr/bin/env python
"""S1 verification suite — one case per contract/edge, printed as a PASS/FAIL table.

Dev-time only (scripts/ is for temporary smoke/verification scripts). Fully
offline: no network, no real model. Run:

    python scripts/check_s1.py

Exits non-zero if any case fails.
"""

from __future__ import annotations

import inspect
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pydantic import BaseModel  # noqa: E402

from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    ModelResponse,
    Observation,
    ToolCall,
    ToolResult,
    TraceEvent,
)
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.registry import ToolContext, ToolRegistry  # noqa: E402

_RESULTS: list[tuple[str, str, bool, str]] = []  # (group, name, passed, detail)


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


def _reg_readlog() -> ToolRegistry:
    r = ToolRegistry()
    r.register(ReadLogTool())
    return r


def _trace(rid: str) -> TraceWriter:
    tw = TraceWriter(run_id=rid, to_console=False)
    if tw.path.exists():
        tw.path.unlink()  # start each case clean
    return tw


# ── A. schemas match architecture §4 ──────────────────────────────────────────
def _fields(m) -> set[str]:
    return set(m.model_fields.keys())


check("schemas", "ToolCall 字段 = id/name/input", _fields(ToolCall) == {"id", "name", "input"})
check("schemas", "ToolResult 字段 = ok/output", _fields(ToolResult) == {"ok", "output"})
check(
    "schemas",
    "ModelResponse 字段 = text/tool_calls/stop_reason/usage",
    _fields(ModelResponse) == {"text", "tool_calls", "stop_reason", "usage"},
)
check(
    "schemas",
    "Observation 字段 (12 项) 与 §4 一致",
    _fields(Observation)
    == {
        "id", "timestamp", "place", "obs_date", "time_of_day", "species",
        "count", "behavior", "raw_note", "confidence", "source", "flags",
    },
)
check("schemas", "TraceEvent 字段 = step/timestamp/kind/summary/detail",
      _fields(TraceEvent) == {"step", "timestamp", "kind", "summary", "detail"})


# ── B. signatures locked to §6 ────────────────────────────────────────────────
loop_sig = list(inspect.signature(run_agent_turn).parameters)
check(
    "contracts",
    "run_agent_turn 签名锁定",
    loop_sig == ["messages", "tools", "llm", "permissions", "budget", "trace", "on_event"],
    str(loop_sig),
)
mock_sig = list(inspect.signature(MockClient.complete).parameters)
check("contracts", "MockClient.complete(messages, tools=None)",
      mock_sig == ["self", "messages", "tools"], str(mock_sig))


# ── C. happy path: model→tool→model→end_turn ─────────────────────────────────
reg = _reg_readlog()
script = [
    ModelResponse(stop_reason="tool_use",
                  tool_calls=[ToolCall(id="c1", name="read_log", input={"place": "卡西临海公园"})]),
    ModelResponse(stop_reason="end_turn", text="整理完成：约20只，疑似黑翅长脚鹬。"),
]
ev: list = []
msgs = [{"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": "上午卡西临海公园，约20只黑头红腿涉禽"}]
fm, ft = run_agent_turn(msgs, reg, MockClient(script), Permissions(), Budget(8),
                        _trace("chk_happy"), on_event=ev.append)
kinds = [e.kind for e in ev]
check("happy", "事件序列 = model_call,tool_call,tool_result,model_call,final",
      kinds == ["model_call", "tool_call", "tool_result", "model_call", "final"], str(kinds))
check("happy", "read_log 执行成功 (ok=True)",
      any(e.kind == "tool_result" and e.detail.get("ok") for e in ev))
check("happy", "final_text 非空", bool(ft), repr(ft))
check("happy", "消息角色序列正确",
      [m["role"] for m in fm] == ["system", "user", "assistant", "tool", "assistant"],
      str([m["role"] for m in fm]))


# ── D. budget guard: 工具调不停 → budget_stop ─────────────────────────────────
reg = _reg_readlog()
loop_script = [ModelResponse(stop_reason="tool_use",
               tool_calls=[ToolCall(id="cx", name="read_log", input={})]) for _ in range(20)]
ev = []
b = Budget(3)
fm, ft = run_agent_turn([{"role": "user", "content": "x"}], reg, MockClient(loop_script),
                        Permissions(), b, _trace("chk_budget"), on_event=ev.append)
check("budget", "以 budget_stop 收尾", ev[-1].kind == "budget_stop", ev[-1].detail.get("stop_reason"))
check("budget", "恰好 max_steps(3) 次 model_call", sum(1 for e in ev if e.kind == "model_call") == 3)
check("budget", "final_text 为 None", ft is None)


# ── E. tool error normalized + 循环不崩 ───────────────────────────────────────
class _BoomIn(BaseModel):
    pass


class BoomTool:
    name = "boom"; description = "always raises"
    input_schema = {"type": "object", "properties": {}}
    schema = _BoomIn; risk = "read"

    def run(self, input, ctx):
        raise ValueError("kaboom")


reg = ToolRegistry(); reg.register(BoomTool())
res = reg.execute("boom", {}, ToolContext(permissions=Permissions()))
check("tool-error", "异常归一化为 ok=False", res.ok is False, res.output)
check("tool-error", "错误信息含工具名 boom", "boom" in res.output)
script = [ModelResponse(stop_reason="tool_use", tool_calls=[ToolCall(id="c1", name="boom", input={})]),
          ModelResponse(stop_reason="end_turn", text="工具报错也能继续收尾")]
ev = []
fm, ft = run_agent_turn([{"role": "user", "content": "x"}], reg, MockClient(script),
                        Permissions(), Budget(8), _trace("chk_boom"), on_event=ev.append)
check("tool-error", "循环不崩、仍能 final", ft is not None and ev[-1].kind == "final", repr(ft))


# ── F. unknown tool / input validation ───────────────────────────────────────
reg = _reg_readlog(); ctx = ToolContext(permissions=Permissions())
res = reg.execute("nope", {}, ctx)
check("registry", "未知工具 → ok=False + 'unknown tool'",
      res.ok is False and "unknown tool" in res.output, res.output)
res = reg.execute("read_log", {"place": ["不是字符串"]}, ctx)  # place must be str|None
check("registry", "非法输入 → ok=False + 'invalid input'",
      res.ok is False and "invalid input" in res.output, res.output[:48])


# ── G. write gate (thin permissions, fail-closed) ────────────────────────────
class _WIn(BaseModel):
    x: int


class WriteTool:
    name = "fake_write"; description = "pretend write"
    input_schema = {"type": "object", "properties": {"x": {"type": "integer"}}}
    schema = _WIn; risk = "write"

    def run(self, input, ctx):
        return ToolResult(ok=True, output="WROTE (must NOT happen in S1)")


reg = ToolRegistry(); reg.register(WriteTool())
res = reg.execute("fake_write", {"x": 1}, ToolContext(permissions=Permissions()))
check("permissions", "写操作被拒 (fail-closed)",
      res.ok is False and "permission denied" in res.output, res.output)
check("permissions", "run() 未被调用 (无 WROTE)", "WROTE" not in res.output)
check("permissions", "read→allow / write→deny",
      Permissions().check("read_log", "read", {}) == "allow"
      and Permissions().check("append_log", "write", {}) == "deny")


# ── H. read_log filtering (fake) ─────────────────────────────────────────────
reg = _reg_readlog(); ctx = ToolContext(permissions=Permissions())
hit = reg.execute("read_log", {"place": "卡西临海公园"}, ctx).output
miss = reg.execute("read_log", {"place": "火星"}, ctx).output
check("read_log", "命中地点返回历史观测", "黑翅长脚鹬" in hit)
check("read_log", "无匹配返回占位文本", "无匹配" in miss)


# ── I. offline / provider-neutral ────────────────────────────────────────────
used_google = [m for m in sys.modules if m.split(".")[0] == "google"]
check("offline", "全程未加载 google-genai", not used_google, str(used_google))


# ── J. trace JSONL well-formed ───────────────────────────────────────────────
tw = _trace("chk_trace"); reg = _reg_readlog()
script = [ModelResponse(stop_reason="tool_use",
          tool_calls=[ToolCall(id="c1", name="read_log", input={"place": "卡西临海公园"})]),
          ModelResponse(stop_reason="end_turn", text="ok")]
ev = []
run_agent_turn([{"role": "user", "content": "x"}], reg, MockClient(script),
               Permissions(), Budget(8), tw, on_event=ev.append)
lines = tw.path.read_text(encoding="utf-8").strip().splitlines()
parsed = [json.loads(line) for line in lines]
check("trace", "JSONL 行数 == 事件数", len(lines) == len(ev), f"{len(lines)} vs {len(ev)}")
check("trace", "每行均可被 json 解析", len(parsed) == len(lines))
check("trace", "每行含 step/kind/summary/detail",
      all({"step", "kind", "summary", "detail"}.issubset(p) for p in parsed))


# ── print table + cleanup ────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("S1 验证套件 — 离线、无网络、无真实模型")
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

    # remove this suite's throwaway trace files (keep s1_smoke.jsonl)
    for f in (ROOT / "data" / "traces").glob("chk_*.jsonl"):
        f.unlink()

    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
