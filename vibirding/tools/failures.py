"""Shared formatter for tool FAILURE output (ok=False), so every tool reports a
failure in one consistent, model-friendly shape.

Only the failure *text* is unified here — the underlying reason string (which the
existing self-checks assert on, e.g. "超时" / "HHO_API_KEY") is passed through
verbatim, just wrapped with a uniform prefix and an optional fallback hint that
tells the model how to recover. Normal (ok=True) output is NOT touched.

Note: of the four tools only range_check and bird_id emit tool-level ok=False;
read_log/append_log failures surface at the registry level (invalid input /
permission denied / tool error) and are out of scope here.
"""

from __future__ import annotations


def tool_failure(tool: str, reason: str, fallback: str = "") -> str:
    """Build a uniform ok=False message: a "⚠ <tool> 暂不可用：<reason>" line plus
    an optional "回退建议：<fallback>" line guiding the model's next move."""
    msg = f"⚠ {tool} 暂不可用：{reason}"
    if fallback:
        msg += f"\n回退建议：{fallback}"
    return msg
