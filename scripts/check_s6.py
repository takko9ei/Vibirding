#!/usr/bin/env python
"""S6 verification suite (offline) — budget + tool error-tolerance + graceful stop.

Dev-time only. Fully offline: no network, no real model, no API key. We stub
httpx.get/post to inject faults (bad JSON, timeout, bad upload code), drive the
real run_agent_turn with a scripted MockClient to hit max_steps / max_tokens, and
feed memory/log a corrupt line. Assertions: every failure normalizes (no bare
stack), the loop always ends gracefully (budget_stop), there is no dead-loop, and
failure messages share the unified "⚠ <tool> 暂不可用" shape.

As a safety net httpx.get/post default to "blow up", so any case that forgets a
stub fails loudly instead of going online. time.sleep is patched out.

Run:
    .venv/Scripts/python.exe scripts/check_s6.py

Exits non-zero if any case fails.
"""

from __future__ import annotations

import json
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

import httpx  # noqa: E402

from vibirding import config  # noqa: E402
from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import ModelResponse, Observation, ToolCall  # noqa: E402
from vibirding.tools import bird_id as bid  # noqa: E402
from vibirding.tools.bird_id import BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolContext, ToolManager  # noqa: E402


# ── offline guards + fake keys (suite is throwaway; no need to restore) ───────
def _no_net(*args, **kwargs):
    raise AssertionError("network call attempted in offline check!")


httpx.get = _no_net
httpx.post = _no_net
bid.time.sleep = lambda *a, **k: None
config.load_ebird_api_key = lambda: "fake-ebird"  # type: ignore[assignment]
config.load_hho_api_key = lambda: "fake-hho"  # type: ignore[assignment]

_RESULTS: list[tuple[str, str, bool, str]] = []
_BASE = Path(tempfile.mkdtemp(prefix="vibirding_s6_"))
_N = 0
_CTX = ToolContext(permissions=Permissions())

_TMP_IMG = _BASE / "x.jpg"
_TMP_IMG.write_bytes(b"\xff\xd8\xff\xe0fake-jpg")
IMG = str(_TMP_IMG)


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


def _new_path() -> Path:
    global _N
    _N += 1
    return _BASE / f"log_{_N}.jsonl"


def _obs(**over) -> Observation:
    data = {
        "place": "葛西临海公园", "obs_date": "2025-06-01", "species": "黑翅长脚鹬",
        "count": 5, "raw_note": "n", "source": "inferred",
    }
    data.update(over)
    data.setdefault("id", "tid")
    data.setdefault("timestamp", "2025-06-01T00:00:00+00:00")
    return Observation.model_validate(data)


class _FakeResp:
    """Minimal httpx.Response stand-in: .json() + .raise_for_status()."""

    def __init__(self, payload, status: int = 200, bad_json: bool = False) -> None:
        self._payload, self._status, self._bad_json = payload, status, bad_json

    def json(self):
        if self._bad_json:
            raise json.JSONDecodeError("bad", "", 0)
        return self._payload

    def raise_for_status(self):
        if self._status >= 400:
            req = httpx.Request("GET", "http://x")
            raise httpx.HTTPStatusError(
                "err", request=req, response=httpx.Response(self._status, request=req)
            )


def _scripted(responses):
    """An httpx stub that pops the given responses in order."""
    seq = list(responses)
    return lambda *a, **k: seq.pop(0)


def _safe_loop(script, budget):
    """Drive run_agent_turn with a scripted model; return (events, final, error)."""
    reg = ToolManager()
    reg.register(ReadLogTool(Log(_new_path())))  # hermetic empty log; read always ok
    trace = TraceWriter(run_id=f"s6_{_N}", traces_dir=_BASE, to_console=False)
    ev: list = []
    try:
        _, ft = run_agent_turn(
            [{"role": "user", "content": "x"}], reg, MockClient(script),
            Permissions(), budget, trace, on_event=ev.append,
        )
        return ev, ft, None
    except Exception as e:  # a crash here is exactly what S6 must prevent
        return ev, None, e


def _tool_call(name="read_log"):
    return ToolCall(id="c", name=name, input={})


# ── A. budget unit: observe + tick caps ──────────────────────────────────────
b = Budget(max_steps=5, max_tokens=100)
b.observe({"input_tokens": 10, "output_tokens": 5})
check("budget", "observe 累加 input+output = 15", b.tokens_used == 15, str(b.tokens_used))
b.observe(None)
b.observe({})
check("budget", "observe(None/空) 不变", b.tokens_used == 15, str(b.tokens_used))

b = Budget(max_steps=99, max_tokens=100)
b.observe({"input_tokens": 60, "output_tokens": 60})  # 120 >= 100
check("budget", "token 触顶 → tick False", b.tick() is False)
check("budget", "token 触顶 → stop_reason max_tokens", b.stop_reason() == "max_tokens")

b = Budget(max_steps=2)  # no token cap (back-compatible)
check("budget", "max_steps: tick,tick=True 第三次 False",
      b.tick() and b.tick() and (not b.tick()))
check("budget", "max_steps → stop_reason max_steps", b.stop_reason() == "max_steps")


# ── B. loop graceful stop on max_steps ───────────────────────────────────────
script = [ModelResponse(stop_reason="tool_use", tool_calls=[_tool_call()]) for _ in range(10)]
ev, ft, err = _safe_loop(script, Budget(max_steps=3))
check("loop-steps", "无异常 (不抛裸栈)", err is None, repr(err))
check("loop-steps", "以 budget_stop 收尾", bool(ev) and ev[-1].kind == "budget_stop")
check("loop-steps", "恰好 3 次 model_call (不死循环)",
      sum(1 for e in ev if e.kind == "model_call") == 3)
check("loop-steps", "final_text 为 None", ft is None)


# ── C. loop graceful stop on max_tokens ──────────────────────────────────────
script = [
    ModelResponse(stop_reason="tool_use", tool_calls=[_tool_call()],
                  usage={"input_tokens": 40, "output_tokens": 40})
    for _ in range(10)
]
ev, ft, err = _safe_loop(script, Budget(max_steps=99, max_tokens=100))
check("loop-tokens", "无异常 (不抛裸栈)", err is None, repr(err))
check("loop-tokens", "以 budget_stop 收尾", bool(ev) and ev[-1].kind == "budget_stop")
check("loop-tokens", "stop_reason == max_tokens",
      any(e.kind == "budget_stop" and e.detail.get("stop_reason") == "max_tokens" for e in ev))


# ── D. range_check fault tolerance + unified message ─────────────────────────
def _run_range(get_stub, place="葛西临海公园"):
    httpx.get = get_stub
    try:
        reg = ToolManager(); reg.register(RangeCheckTool())
        return reg.execute("range_check", {"place": place, "date": "2026-06-27"}, _CTX)
    finally:
        httpx.get = _no_net


def _raise_timeout(*a, **k):
    raise httpx.TimeoutException("boom")


r = _run_range(lambda *a, **k: _FakeResp(None, bad_json=True))  # 200 but bad JSON
check("range_check", "坏 JSON → ok=False (非-httpx 被显式接)", not r.ok, r.output[:50])
check("range_check", "坏 JSON → 含'无法解析'，不抛裸栈", "无法解析" in r.output, r.output[:50])
check("range_check", "坏 JSON → 统一前缀 '⚠ range_check'", r.output.startswith("⚠ range_check"))

r = _run_range(_raise_timeout)
check("range_check", "超时 → ok=False + '超时' (回归)", (not r.ok) and "超时" in r.output, r.output[:50])
check("range_check", "超时 → 统一前缀", r.output.startswith("⚠ range_check"))


# ── E. log.query skips a corrupt line ────────────────────────────────────────
p = _new_path()
log = Log(p)
log.append(_obs(species="甲"))
with open(p, "a", encoding="utf-8") as f:
    f.write("{这是一行坏 json\n")  # corrupt middle line
log.append(_obs(species="乙"))
try:
    rows = log.query()
    q_err = None
except Exception as e:
    rows, q_err = [], e
check("log", "坏行不抛异常", q_err is None, repr(q_err))
check("log", "坏行跳过，仍取回 2 条好记录",
      len(rows) == 2 and {r.species for r in rows} == {"甲", "乙"}, str(len(rows)))


# ── F. bird_id fault tolerance + unified message ─────────────────────────────
def _run_bird(post_responses):
    httpx.post = _scripted(post_responses)
    try:
        reg = ToolManager(); reg.register(BirdIdTool())
        return reg.execute("bird_id", {"image_path": IMG}, _CTX)
    finally:
        httpx.post = _no_net


r = _run_bird([_FakeResp([1002, "x"])])  # upload non-1000 (format unsupported)
check("bird_id", "上传非1000 → ok=False + '格式' (回归)", (not r.ok) and "格式" in r.output, r.output[:50])
check("bird_id", "上传非1000 → 统一前缀 '⚠ bird_id'", r.output.startswith("⚠ bird_id"))

_TARGETS = [{"box": [0, 0, 1, 1], "list": [[99.0, "北鹰鸮|Northern Boobook|Ninox", 1, "B"]]}]
r = _run_bird([_FakeResp([1000, "rid"]), _FakeResp([1000, _TARGETS])])  # happy (regression)
check("bird_id", "正常路径 ok=True + 候选 (未被波及)", r.ok and "北鹰鸮" in r.output, r.output[:50])
r = _run_bird([_FakeResp([1000, "rid"]), _FakeResp([1008, None])])  # unrecognized -> ok=True
check("bird_id", "1008 未识别 → ok=True (不当失败)", r.ok and "未能识别" in r.output, r.output[:50])


# ── print table + cleanup ────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("S6 验证套件（离线）— budget + 工具容错 + 优雅收尾（打桩造故障）")
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
    shutil.rmtree(_BASE, ignore_errors=True)
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
