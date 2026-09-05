#!/usr/bin/env python
"""S7 — evals: run the agent over fixed cases and print a pass rate.

Two lanes (architecture section 9):

  offline (default): MockClient + stubbed range_check / bird_id. For each case a
    synthetic "ideal model" script is built FROM the case's expected answer, so
    the real loop runs but the outcome is deterministic -> should be 100%. It
    guards the plumbing (loop -> registry -> permission gate -> Log -> read-back)
    and the comparator itself against regressions. No network, no key.

  online (--online): real low-temp DeepSeek + real tools. Measures true
    recognition quality; <100% is the honest metric. Needs DEEPSEEK_API_KEY.
    Image cases are skipped unless --online-images (protects the hholove quota,
    which has only ~50 free calls).

Every case is isolated: its own temporary PostgreSQL schema (the development
schema is NEVER touched), an injected auto-approver ("always", no stdin), and a
temp trace dir.
This reuses the whole existing stack (loop / ToolManager / real tools / Log /
Permissions / Budget / TraceWriter / MockClient) — the only eval-specific code is
the answers->script synthesizer and the two network-tool stubs, both living here.

Run:
    .venv/Scripts/python.exe evals/run_evals.py                 # offline, all
    .venv/Scripts/python.exe evals/run_evals.py --online        # real DeepSeek
    .venv/Scripts/python.exe evals/run_evals.py --ids t04,t05   # subset
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.agent.loop import run_agent_turn  # noqa: E402
from vibirding.agent.prompt import SYSTEM_PROMPT, today_hint  # noqa: E402
from vibirding.harness.budget import Budget  # noqa: E402
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.harness.trace import TraceWriter  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.memory.log import Log  # noqa: E402
from vibirding.schemas import ModelResponse, ToolCall, ToolResult  # noqa: E402
from vibirding.tools.bird_id import BirdIdInput, BirdIdTool  # noqa: E402
from vibirding.tools.log_read import ReadLogTool  # noqa: E402
from vibirding.tools.log_write import AppendLogTool  # noqa: E402
from vibirding.tools.range_check import RangeCheckInput, RangeCheckTool  # noqa: E402
from vibirding.tools.registry import ToolContext, ToolManager  # noqa: E402
from scripts.db_test_support import new_test_log  # noqa: E402

DEFAULT_TASKS = ROOT / "evals" / "tasks.yaml"
DEFAULT_ANSWERS = ROOT / "evals" / "answers.yaml"
_DEFAULT_COUNT_TOL = 5  # count_around tolerance when the case doesn't override it


# ── offline stub tools (keep the offline lane hermetic: no network) ───────────
class StubRangeCheck:
    """Offline stand-in for range_check: same protocol, canned ok=True output."""

    name = "range_check"
    description = RangeCheckTool.description
    input_schema = RangeCheckTool.input_schema
    schema = RangeCheckInput
    risk = "read"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        place = input.get("place", "?")
        return ToolResult(
            ok=True,
            output=f"（离线桩 range_check）{place} 近期物种清单：麻雀、白鹡鸰、灰椋鸟、家燕、山斑鸠…",
        )


class StubBirdId:
    """Offline stand-in for bird_id: same protocol, canned ok=True output."""

    name = "bird_id"
    description = BirdIdTool.description
    input_schema = BirdIdTool.input_schema
    schema = BirdIdInput
    risk = "read"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        return ToolResult(ok=True, output="（离线桩 bird_id）候选：麻雀 置信度 88")


# ── answers -> "ideal model" MockClient script (offline lane only) ────────────
def _pick_species(species_in: list):
    """First non-null of species_in (the offline oracle's chosen species)."""
    for s in species_in:
        if s is not None:
            return s
    return None  # only null in the list -> the model leaves species empty


def _synth_append_input(exp: dict, note: str) -> dict:
    """An append_log input dict crafted to satisfy every assertion in `exp`."""
    inp: dict = {"raw_note": note, "source": exp.get("source", "inferred")}
    if "place" in exp:
        inp["place"] = exp["place"]
    if "species_in" in exp:
        sp = _pick_species(exp["species_in"])
        if sp is not None:
            inp["species"] = sp  # only-null -> omit so species stays None
    if exp.get("count") is not None:
        inp["count"] = exp["count"]
    elif "count_around" in exp:
        inp["count"] = exp["count_around"]  # exact center is within tolerance
    if exp.get("behavior_not_null"):
        inp["behavior"] = "（有行为描述）"
    if exp.get("time_of_day_not_null"):
        inp["time_of_day"] = "（有时段）"
    if exp.get("flags_contains_any"):
        inp["flags"] = [exp["flags_contains_any"][0]]  # first token satisfies any-of
    return inp


def build_offline_script(case: dict) -> list[ModelResponse]:
    """Script the fake model: call the required read tools, then append_log, then end.

    Tool calls come from must_call_tools (minus append_log), plus range_check when
    the case asserts the unknown-place graceful path. append_log's args are
    synthesized from expected so all field assertions pass by construction.
    """
    exp = case["expected"]
    note = case["input_note"]
    pre = [t for t in exp.get("must_call_tools", []) if t != "append_log"]
    if exp.get("tool_ok_even_if_unknown_place") and "range_check" not in pre:
        pre.append("range_check")

    script: list[ModelResponse] = []
    i = 0
    for tname in pre:
        i += 1
        if tname == "range_check":
            inp = {"place": exp.get("place") or "葛西临海公园"}
        elif tname == "bird_id":
            inp = {"image_path": case.get("image_path") or "x.jpg"}
        elif tname == "read_log":
            inp = {"place": exp.get("place")}
        else:
            inp = {}
        script.append(
            ModelResponse(stop_reason="tool_use",
                          tool_calls=[ToolCall(id=f"c{i}", name=tname, input=inp)])
        )

    if not exp.get("must_not_write"):
        i += 1
        script.append(
            ModelResponse(stop_reason="tool_use",
                          tool_calls=[ToolCall(id=f"c{i}", name="append_log",
                                               input=_synth_append_input(exp, note))])
        )

    script.append(ModelResponse(stop_reason="end_turn", text="（离线理想模型）已整理并写入日志。"))
    return script


# ── comparator (architecture section 9 grading contract) ──────────────────────
def grade(exp: dict, obs, called_tools: set, rc_ok: bool) -> list[tuple[str, bool, str]]:
    """Return [(key, passed, detail), ...]; the case PASSes iff all passed."""
    out: list[tuple[str, bool, str]] = []
    wrote = obs is not None

    def add(key: str, passed: bool, detail: str = "") -> None:
        out.append((key, bool(passed), detail))

    if "place" in exp:
        actual = obs.place if wrote else "<未写入>"
        add("place", wrote and obs.place == exp["place"],
            f"期望={exp['place']!r} 实际={actual!r}")
    if "count" in exp:
        actual = obs.count if wrote else "<未写入>"
        add("count", wrote and obs.count == exp["count"],
            f"期望={exp['count']} 实际={actual}")
    if "count_around" in exp:
        n = exp["count_around"]
        tol = exp.get("count_tol", _DEFAULT_COUNT_TOL)
        actual = obs.count if wrote else None
        ok = wrote and actual is not None and abs(actual - n) <= tol
        add(f"count_around({n}±{tol})", ok, f"期望≈{n} 实际={actual}")
    if "species_in" in exp:
        actual = obs.species if wrote else "<未写入>"
        add("species_in", wrote and obs.species in exp["species_in"],
            f"允许={exp['species_in']} 实际={actual!r}")
    if "source" in exp:
        actual = obs.source if wrote else "<未写入>"
        add("source", wrote and obs.source == exp["source"],
            f"期望={exp['source']!r} 实际={actual!r}")
    if "confidence" in exp and exp["confidence"] is None:
        actual = obs.confidence if wrote else "<未写入>"
        add("confidence=null", wrote and obs.confidence is None, f"期望=null 实际={actual}")
    if exp.get("behavior_not_null"):
        actual = obs.behavior if wrote else None
        add("behavior_not_null", wrote and bool(actual), f"实际={actual!r}")
    if exp.get("time_of_day_not_null"):
        actual = obs.time_of_day if wrote else None
        add("time_of_day_not_null", wrote and bool(actual), f"实际={actual!r}")
    if "flags_contains_any" in exp:
        tokens = exp["flags_contains_any"]
        flags = obs.flags if wrote else []
        ok = any(tok in fl for tok in tokens for fl in flags)
        add("flags_contains_any", ok, f"期望含任一={tokens} 实际flags={flags}")
    if "must_call_tools" in exp:
        need = exp["must_call_tools"]
        add("must_call_tools", all(t in called_tools for t in need),
            f"期望⊆={need} 实际调用={sorted(called_tools)}")
    if exp.get("must_not_write"):
        add("must_not_write", not wrote, f"实际写入={wrote}")
    if exp.get("tool_ok_even_if_unknown_place"):
        add("tool_ok_even_if_unknown_place", rc_ok and wrote,
            f"range_check无硬失败={rc_ok} 已写入={wrote}")
    return out


# ── per-case run ──────────────────────────────────────────────────────────────
@dataclass
class CaseResult:
    id: str
    checks: list[tuple[str, bool, str]]
    obs: object
    called: set
    trace_path: Path
    tmp: Path
    error: str | None = None

    @property
    def passed(self) -> bool:
        return self.error is None and all(ok for _, ok, _ in self.checks)


def run_case(case: dict, lane: str, args, online_llm) -> CaseResult:
    """Run one case in isolation and grade it."""
    tmp = Path(tempfile.mkdtemp(prefix="vibirding_eval_"))
    log = new_test_log(f"eval_{case['id']}")

    registry = ToolManager()
    registry.register(ReadLogTool(log))
    if lane == "offline":
        registry.register(StubRangeCheck())
        registry.register(StubBirdId())
    else:
        registry.register(RangeCheckTool())
        registry.register(BirdIdTool())
    registry.register(AppendLogTool(log))

    # Injected auto-approver: writes are allowed automatically (never via stdin).
    permissions = Permissions(approver=lambda *a, **k: "always")
    trace = TraceWriter(
        run_id=f"eval_{case['id']}_{datetime.now():%H%M%S_%f}",
        traces_dir=tmp,
        to_console=False,
    )
    events: list = []

    note = case["input_note"]
    img = case.get("image_path")
    # Signal an attached image to the model the same way the S4 entry does.
    user_content = note + (f"\n（附图，本地路径：{img}）" if img else "")

    if lane == "offline":
        system = SYSTEM_PROMPT  # MockClient ignores messages; kept for parity
        script = build_offline_script(case)
        llm = MockClient(script)
        budget = Budget(max_steps=len(script) + 2)
    else:
        system = SYSTEM_PROMPT + "\n\n" + today_hint()  # runtime date anchor
        llm = online_llm
        budget = Budget(max_steps=args.max_steps)

    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_content},
    ]

    error = None
    try:
        run_agent_turn(messages, registry, llm, permissions, budget, trace,
                       on_event=events.append)
    except Exception as e:  # online: network/model failure -> case errors (fail)
        error = f"运行异常：{type(e).__name__}: {e}"

    rows = log.query()
    obs = rows[-1] if rows else None
    called = {e.detail.get("name") for e in events if e.kind == "tool_call"}
    # range_check "no hard failure": every range_check result had ok=True
    # (vacuously True when it was never called).
    rc_ok = all(
        e.detail.get("ok") for e in events
        if e.kind == "tool_result" and e.detail.get("name") == "range_check"
    )
    checks = [] if error else grade(case["expected"], obs, called, rc_ok)
    return CaseResult(case["id"], checks, obs, called, trace.path, tmp, error)


# ── loading + reporting ───────────────────────────────────────────────────────
def load_cases(tasks_path: Path, answers_path: Path) -> list[dict]:
    """Join the questions file and the answers file by id."""
    tasks = yaml.safe_load(tasks_path.read_text(encoding="utf-8")) or []
    answers = {a["id"]: a["expected"] for a in
               (yaml.safe_load(answers_path.read_text(encoding="utf-8")) or [])}
    cases: list[dict] = []
    for t in tasks:
        tid = t["id"]
        if tid not in answers:
            raise SystemExit(f"答案缺失：{tid} 在 {answers_path.name} 里没有对应 expected")
        cases.append({**t, "expected": answers[tid]})
    return cases


def _fmt_obs(obs) -> str:
    if obs is None:
        return "<未写入>"
    return f"species={obs.species!r} count={obs.count} source={obs.source!r} flags={obs.flags}"


def main() -> int:
    ap = argparse.ArgumentParser(description="S7 evals — pass rate over fixed cases")
    ap.add_argument("--online", action="store_true",
                    help="use real DeepSeek + real tools (default: offline mock)")
    ap.add_argument("--online-images", action="store_true",
                    help="in online lane, also run image cases (burns hholove quota)")
    ap.add_argument("--max-steps", type=int, default=6, help="per-case step budget (online)")
    ap.add_argument("--max-cases", type=int, default=None, help="cap number of cases run")
    ap.add_argument("--ids", default=None, help="comma-separated ids to run, e.g. t04,t05")
    ap.add_argument("--tasks", default=str(DEFAULT_TASKS))
    ap.add_argument("--answers", default=str(DEFAULT_ANSWERS))
    args = ap.parse_args()

    lane = "online" if args.online else "offline"
    cases = load_cases(Path(args.tasks), Path(args.answers))

    if args.ids:
        wanted = {s.strip() for s in args.ids.split(",") if s.strip()}
        cases = [c for c in cases if c["id"] in wanted]
    if args.max_cases is not None:
        cases = cases[: args.max_cases]

    # Online: fail fast if the key is missing; build one client, reuse it.
    online_llm = None
    if lane == "online":
        from vibirding.llm.deepseek_client import DeepSeekClient, DeepSeekError
        try:
            online_llm = DeepSeekClient()
        except DeepSeekError as e:
            print("✗ 初始化 DeepSeek 失败：", e)
            return 2

    # Guard: prove isolated eval schemas never touch development observations.
    real_log_before = _real_log_count()

    print("=" * 72)
    print(f"S7 Evals（{lane}）— 用例 {len(cases)} 条"
          + ("｜真 DeepSeek + 真工具" if lane == "online" else "｜MockClient + 桩工具，离线"))
    print("=" * 72)

    results: list[CaseResult] = []
    skipped: list[str] = []
    for case in cases:
        is_image = bool(case.get("image_path"))
        if lane == "online" and is_image and not args.online_images:
            skipped.append(case["id"])  # protect hholove quota
            print(f"SKIP  {case['id']}  （带图用例，未加 --online-images）")
            continue
        r = run_case(case, lane, args, online_llm)
        results.append(r)
        mark = "PASS" if r.passed else "FAIL"
        print(f"{mark}  {r.id}")
        if not r.passed:
            if r.error:
                print(f"        ✗ {r.error}")
            for key, ok, detail in r.checks:
                if not ok:
                    print(f"        ✗ {key:<28} {detail}")
            print(f"        actual: {_fmt_obs(r.obs)}")
            print(f"        called: {sorted(r.called)}")
            print(f"        trace : {r.trace_path}")

    # Clean up temp dirs: drop passed cases; keep failed ones for inspection.
    for r in results:
        if r.passed:
            shutil.rmtree(r.tmp, ignore_errors=True)

    passed = sum(r.passed for r in results)
    total = len(results)
    rate = f"{100 * passed / total:.1f}%" if total else "—"
    print("\n" + "-" * 72)
    print(f"通过率 {passed}/{total} ({rate})"
          + (f"   [跳过 {len(skipped)}: {skipped}]" if skipped else ""))
    if any(not r.passed for r in results):
        print("（失败用例的临时目录/trace 已保留，路径见上，便于分析）")
    print("-" * 72)

    real_log_after = _real_log_count()
    if real_log_before != real_log_after:
        print(f"⚠ 警告：开发库记录数变化 {real_log_before} -> {real_log_after}（本应不变！）")
        return 3

    return 0 if passed == total else 1


def _real_log_count() -> int:
    """Row count of the development observation schema — pollution guard."""
    return len(Log().query())


if __name__ == "__main__":
    raise SystemExit(main())
