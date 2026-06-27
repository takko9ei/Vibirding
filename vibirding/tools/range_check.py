"""range_check — a READ-ONLY tool: authoritative season/range check via eBird.

Pattern B (architecture section 7): place + date -> the species actually
recorded RECENTLY around that place, i.e. a "what plausibly occurs here this
season" list. The model then picks, from that list, the species matching the
note's physical description. This is AUTHORITATIVE distribution data (eBird), as
opposed to read_log which is only your personal weak prior.

`date` is only a SEASON HINT. eBird's geo/recent endpoint returns observations
from the last `back` days up to TODAY (<= 30 days), so we use "recently recorded"
as a proxy for "in season"; an arbitrary historical date cannot be queried.

Failures never escape as a raw exception: HTTP timeout / network / 401-403 / odd
status all normalize to ToolResult(ok=False, ...). "Unknown place" and "empty
list" are legitimate outcomes -> ToolResult(ok=True, ...) with guidance text.

Satisfies the Tool protocol (tools/registry.py):
    name / description / input_schema / schema / risk / run(input, ctx)
"""

from __future__ import annotations

import httpx
from pydantic import BaseModel

from .. import config
from ..schemas import ToolResult
from .failures import tool_failure
from .locations import resolve_place
from .registry import ToolContext

# How long to wait on the eBird HTTP call before giving up (seconds).
_HTTP_TIMEOUT = 10.0
# Cap raw observations requested from eBird (geo/recent already returns one most
# recent record per species, so this also bounds the number of species).
_MAX_RESULTS = 200
# Cap the species list shown to the model so a long menu doesn't bloat the prompt.
_MAX_SPECIES_SHOWN = 80
# Recovery hint shown to the model whenever range_check can't answer (ok=False).
_FALLBACK = "靠你自身的鸟类学知识判断该种是否合理，并酌情给 species 标 low_confidence。"


class RangeCheckInput(BaseModel):
    """Our-side validation: place is required, date is an optional season hint."""

    place: str
    date: str | None = None


class RangeCheckTool:
    """The range_check tool instance registered into the ToolRegistry."""

    name = "range_check"
    description = (
        "查某地近期 eBird 实际记录到的鸟种清单（中文名），作为该地“当季合理出现的物种”"
        "的权威分布依据：你应从清单里挑选与笔记外形描述匹配的种。"
        "与 read_log 不同——read_log 只是你的个人历史/弱先验，本工具是权威分布数据。"
        "参数 date 仅作季节提示（实际取近 N 天到今天的记录当作“当季”代理）。"
    )
    # JSON Schema handed to the model as the function-declaration parameters.
    input_schema = {
        "type": "object",
        "properties": {
            "place": {
                "type": "string",
                "description": "观测地点（用标准官方名，如 葛西临海公园）",
            },
            "date": {
                "type": "string",
                "description": "观测日期 ISO，如 2026-06-24，用于推断季节",
            },
        },
        "required": ["place"],
    }
    schema = RangeCheckInput
    risk = "read"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        place = input.get("place", "")
        date = input.get("date")

        # 1. place -> coordinates. Unknown place is a LEGITIMATE outcome (ok=True):
        #    tell the model to fall back to its own ornithological knowledge.
        coords = resolve_place(place)
        if coords is None:
            return ToolResult(
                ok=True,
                output=(
                    f"未知地点 '{place}'：不在预存坐标表中，无法做 eBird 分布核验；"
                    f"请基于你的鸟类学知识判断该种在此地此季是否合理。"
                ),
            )
        lat, lng = coords

        # 2. need the API key to call eBird; missing key is a real failure.
        key = config.load_ebird_api_key()
        if not key:
            return ToolResult(
                ok=False,
                output=tool_failure(
                    "range_check",
                    "EBIRD_API_KEY 未设置：请在项目根 .env 写入 EBIRD_API_KEY=<your-key>。",
                    _FALLBACK,
                ),
            )

        # 3. fetch + format, normalizing EVERY failure into ok=False so a flaky
        #    network / malformed response never crashes the agent loop. Non-httpx
        #    errors (200 but bad JSON, odd structure) are caught explicitly HERE
        #    too — not left to the registry's generic backstop (the S6 debt fix).
        try:
            observations = _fetch_recent(lat, lng, key)
            output = _format_species(observations, place, date)
        except httpx.TimeoutException:
            return ToolResult(ok=False, output=tool_failure(
                "range_check", "eBird 请求超时，未能取回物种清单。", _FALLBACK))
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status in (401, 403):
                return ToolResult(ok=False, output=tool_failure(
                    "range_check", "eBird API key 无效或无权限（401/403）。", _FALLBACK))
            return ToolResult(ok=False, output=tool_failure(
                "range_check", f"eBird 返回异常状态码 {status}。", _FALLBACK))
        except httpx.RequestError:
            return ToolResult(ok=False, output=tool_failure(
                "range_check", "网络连接 eBird 失败。", _FALLBACK))
        except (ValueError, KeyError, TypeError) as e:
            # 200 but unparseable JSON / unexpected shape — JSONDecodeError is a
            # ValueError subclass, so this also covers bad JSON.
            return ToolResult(ok=False, output=tool_failure(
                "range_check", f"eBird 返回内容无法解析（坏 JSON 或结构异常）：{e}", _FALLBACK))

        # 4. success: empty list is a legitimate outcome -> still ok=True.
        return ToolResult(ok=True, output=output)


def _fetch_recent(lat: float, lng: float, key: str) -> list[dict]:
    """The ONLY networked part: GET eBird recent observations near a point.

    Endpoint / params / auth header are fixed by the S3 plan — do not change them.
    eBird wants lat/lng to 2 decimal places, so we round. Raises httpx errors /
    HTTPStatusError on failure; the caller (run) normalizes them into ToolResult.
    """
    url = f"{config.EBIRD_BASE_URL}/data/obs/geo/recent"
    params = {
        "lat": round(lat, 2),
        "lng": round(lng, 2),
        "dist": config.EBIRD_DIST_KM,  # km radius, <= 50
        "back": config.EBIRD_BACK_DAYS,  # look-back days, 1..30
        # eBird obs endpoints use `sppLocale` (NOT `locale`) for common-name lang.
        "sppLocale": config.EBIRD_SPP_LOCALE,  # zh_SIM -> Simplified Chinese names
        "maxResults": _MAX_RESULTS,
    }
    headers = {"x-ebirdapitoken": key}
    resp = httpx.get(url, params=params, headers=headers, timeout=_HTTP_TIMEOUT)
    resp.raise_for_status()  # non-2xx -> HTTPStatusError (caught upstream)
    return resp.json()


def _format_species(observations: list[dict], place: str, date: str | None) -> str:
    """Dedup by species and render a compact, model-facing list (pure function)."""
    seen: set[str] = set()
    rows: list[str] = []
    for o in observations:
        code = o.get("speciesCode") or o.get("sciName") or ""
        if code in seen:
            continue
        seen.add(code)
        com = o.get("comName") or "?"  # Chinese common name (locale=zh)
        sci = o.get("sciName") or "?"  # scientific name
        rows.append(f"{com}（{sci}）")

    back = config.EBIRD_BACK_DAYS
    when = date or "未提供"
    if not rows:
        return (
            f"{place} 近 {back} 天 eBird 无记录（date={when}）；"
            f"无法据此核验，请用你的鸟类学知识判断。"
        )

    total = len(rows)
    shown = rows[:_MAX_SPECIES_SHOWN]
    header = (
        f"{place} 近 {back} 天 eBird 实际记录的鸟种"
        f"（共 {total} 种，作“当季合理出现”的代理；date={when}）：\n"
    )
    body = "、".join(shown)
    more = f"\n…（另有 {total - len(shown)} 种未列出）" if total > len(shown) else ""
    return header + body + more
