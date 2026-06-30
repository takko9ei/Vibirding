#!/usr/bin/env python
"""S4 verification suite (offline part) — bird_id without any network.

Dev-time only. Fully offline: no 懂鸟 call, no real model, no API key needed. We
stub httpx.post to hand back canned [code, payload] arrays, exercising every
branch run() must normalize (upload ok / non-1000 / HTTP error; poll 1000 /
1001-retry / 1001-timeout / 1008 / 1009 / bad structure / bad JSON), plus the
local prechecks and the pure parsers/formatters. The real 懂鸟 call and the
end-to-end model run are covered separately by scripts/run_s4.py.

As a safety net httpx.post defaults to "blow up", so any case that forgets to set
up a stub fails loudly instead of going online. time.sleep is patched out so the
poll-timeout case doesn't actually wait.

Run:
    .venv/Scripts/python.exe scripts/check_s4.py

Exits non-zero if any case fails.
"""

from __future__ import annotations

import json
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
from vibirding.harness.permissions import Permissions  # noqa: E402
from vibirding.tools import bird_id as bid  # noqa: E402
from vibirding.tools.bird_id import (  # noqa: E402
    BirdIdTool,
    _HhoError,
    _check_image,
    _format_candidates,
    _parse_array,
)
from vibirding.tools.registry import Tool, ToolContext, ToolManager  # noqa: E402


# --- offline guarantee + no real sleeping ---
def _no_network(*args, **kwargs):
    raise AssertionError("network call attempted in offline check!")


httpx.post = _no_network
bid.time.sleep = lambda *a, **k: None  # poll retries must not actually wait

_CTX = ToolContext(permissions=Permissions())
_RESULTS: list[tuple[str, str, bool, str]] = []


def check(group: str, name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((group, name, bool(passed), detail))


class _FakeResp:
    """Minimal stand-in for httpx.Response: .json() + .raise_for_status()."""

    def __init__(self, payload, status: int = 200, bad_json: bool = False) -> None:
        self._payload = payload
        self._status = status
        self._bad_json = bad_json

    def json(self):
        if self._bad_json:
            raise json.JSONDecodeError("bad", "", 0)
        return self._payload

    def raise_for_status(self):
        if self._status >= 400:
            req = httpx.Request("POST", "http://x")
            raise httpx.HTTPStatusError(
                "err", request=req, response=httpx.Response(self._status, request=req)
            )


def _scripted(responses):
    """Return an httpx.post stub that pops the given responses in order."""
    seq = list(responses)

    def _post(*args, **kwargs):
        return seq.pop(0)

    return _post


def _run_with(responses, image_path):
    """Run bird_id with httpx.post scripted, then restore the network guard."""
    httpx.post = _scripted(responses)
    try:
        return BirdIdTool().run({"image_path": image_path}, _CTX)
    finally:
        httpx.post = _no_network


# A tiny real file to act as the image (content is irrelevant — upload is stubbed).
_TMP = Path(tempfile.gettempdir()) / "vibirding_check_s4.jpg"
_TMP.write_bytes(b"\xff\xd8\xff\xe0fake-jpg-bytes")
IMG = str(_TMP)

# A realistic 懂鸟 poll payload (one target, one candidate) — the user's sample.
_TARGETS = [
    {"box": [301, 52, 722, 876],
     "list": [[100.0, "北鹰鸮|Northern Boobook|Ninox japonica", 2548, "B"]]},
]


# ── A. Tool protocol ─────────────────────────────────────────────────────────
tool = BirdIdTool()
check("protocol", "满足 Tool 协议 (六件套)", isinstance(tool, Tool))
check("protocol", "risk == 'read'", tool.risk == "read")
check("protocol", "input_schema 必填 image_path", tool.input_schema["required"] == ["image_path"])


# ── B. _check_image (local precheck) ─────────────────────────────────────────
check("precheck", "空路径 → 报错", _check_image("") is not None)
check("precheck", "文件不存在 → 报错", _check_image("nope/does_not_exist.jpg") is not None)
check("precheck", "存在且不超限 → None", _check_image(IMG) is None)
_orig_max = config.HHO_MAX_IMAGE_BYTES
config.HHO_MAX_IMAGE_BYTES = 0  # force oversize
try:
    msg = _check_image(IMG)
finally:
    config.HHO_MAX_IMAGE_BYTES = _orig_max
check("precheck", "超2M → '过大'", msg is not None and "过大" in msg, str(msg))


# ── C. _parse_array (array/structure validation) ─────────────────────────────
def _expect_hho(fn) -> bool:
    try:
        fn()
        return False
    except _HhoError:
        return True


check("parse", "[code,payload] → (code,payload)", _parse_array(_FakeResp([1000, "rid"])) == (1000, "rid"))
check("parse", "非数组(dict) → _HhoError", _expect_hho(lambda: _parse_array(_FakeResp({"a": 1}))))
check("parse", "长度<2 → _HhoError", _expect_hho(lambda: _parse_array(_FakeResp([1000]))))
check("parse", "code 非整数 → _HhoError", _expect_hho(lambda: _parse_array(_FakeResp(["x", "y"]))))
check("parse", "坏JSON → _HhoError", _expect_hho(lambda: _parse_array(_FakeResp(None, bad_json=True))))


# ── D. _format_candidates (pure: 中文名切分 / 0~100 / top3 / 多目标 / 空) ─────
out = _format_candidates(_TARGETS)
check("format", "含中文名(切|第一段)", "北鹰鸮" in out and "Ninox" not in out)
check("format", "置信度 0~100 原样", "100.0%" in out)

many = [{"box": [0, 0, 1, 1], "list": [[90.0 - i, f"种{i}|E{i}|L{i}", i, "B"] for i in range(6)]}]
big = _format_candidates(many)
check("format", "每目标最多 top3 (种0..种2 在、种3 不在)",
      "种0" in big and "种2" in big and "种3" not in big, big)

multi = _format_candidates(_TARGETS + _TARGETS)
check("format", "多目标加 '目标N' 前缀", "目标1" in multi and "目标2" in multi)

empty = _format_candidates([{"box": [0, 0, 1, 1], "list": []}])
check("format", "无候选 → 提示文本", "没有给出候选种" in empty, empty[:30])


# ── E. run() via stubbed httpx.post ──────────────────────────────────────────
# happy: upload 1000 -> poll 1000 -> candidates
r = _run_with([_FakeResp([1000, "rid-1"]), _FakeResp([1000, _TARGETS])], IMG)
check("run", "上传+取结果成功 → ok=True + 候选", r.ok and "北鹰鸮" in r.output, r.output[:40])

# upload non-1000 (1002 格式)
r = _run_with([_FakeResp([1002, "x"])], IMG)
check("run", "上传非1000 → ok=False + 原因", (not r.ok) and "格式" in r.output, r.output[:40])

# poll 1008 / 1009 -> 未能识别, ok=True
r = _run_with([_FakeResp([1000, "rid"]), _FakeResp([1008, None])], IMG)
check("run", "1008 没检测到 → ok=True + 未能识别", r.ok and "未能识别" in r.output, r.output[:40])
r = _run_with([_FakeResp([1000, "rid"]), _FakeResp([1009, None])], IMG)
check("run", "1009 认不出 → ok=True + 未能识别", r.ok and "未能识别" in r.output, r.output[:40])

# poll 1001 then 1000 -> retry works
r = _run_with([_FakeResp([1000, "rid"]), _FakeResp([1001, None]), _FakeResp([1000, _TARGETS])], IMG)
check("run", "1001→重试→1000 成功", r.ok and "北鹰鸮" in r.output, r.output[:40])

# poll 1001 x HHO_POLL_MAX -> timeout, ok=False
r = _run_with([_FakeResp([1000, "rid"])] + [_FakeResp([1001, None])] * config.HHO_POLL_MAX, IMG)
check("run", "1001 耗尽轮询 → ok=False 超时", (not r.ok) and "超时" in r.output, r.output[:40])

# poll bad structure (dict) -> ok=False 定制
r = _run_with([_FakeResp([1000, "rid"]), _FakeResp({"x": 1})], IMG)
check("run", "取结果坏结构 → ok=False 定制", (not r.ok) and "结构" in r.output, r.output[:40])

# poll bad JSON -> ok=False
r = _run_with([_FakeResp([1000, "rid"]), _FakeResp(None, bad_json=True)], IMG)
check("run", "取结果坏JSON → ok=False", (not r.ok) and "JSON" in r.output, r.output[:40])

# upload HTTP 500 -> ok=False HTTP
r = _run_with([_FakeResp(None, status=500)], IMG)
check("run", "上传 HTTP 500 → ok=False", (not r.ok) and "HTTP 500" in r.output, r.output[:40])


# ── F. no-network branches (httpx.post stays the boom guard) ─────────────────
# missing key (valid file) -> ok=False before any network
_orig_key = config.load_hho_api_key
config.load_hho_api_key = lambda: None  # type: ignore[assignment]
try:
    r = BirdIdTool().run({"image_path": IMG}, _CTX)
finally:
    config.load_hho_api_key = _orig_key  # type: ignore[assignment]
check("nonet", "缺 key → ok=False + 提示", (not r.ok) and "HHO_API_KEY" in r.output, r.output[:40])

# file not exist -> ok=False before any network
r = BirdIdTool().run({"image_path": "nope/x.jpg"}, _CTX)
check("nonet", "文件不存在 → ok=False", (not r.ok) and "不存在" in r.output, r.output[:40])


# ── G. registry wiring ───────────────────────────────────────────────────────
reg = ToolManager()
reg.register(tool)
res = reg.execute("bird_id", {}, _CTX)  # missing required image_path
check("registry", "缺 image_path → 'invalid input'", (not res.ok) and "invalid input" in res.output, res.output[:40])
check("registry", "specs() 含 bird_id", any(s["name"] == "bird_id" for s in reg.specs()))


# ── print table + cleanup ────────────────────────────────────────────────────
def main() -> int:
    print("=" * 72)
    print("S4 验证套件（离线部分）— 无网络、无 key、无真实模型")
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
    try:
        _TMP.unlink()
    except OSError:
        pass
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(main())
