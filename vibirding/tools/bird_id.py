"""bird_id — a READ-ONLY tool: visual bird identification via the 懂鸟/hholove API.

Fills species-source branch 3 (architecture section 8): when the note gives NO
species name but DOES come with a photo, the model calls this tool to get
candidate species (Chinese name + confidence) and picks from them.

The 懂鸟 API is ASYNC two-step + polling, and its responses are ARRAYS, not dicts:
    step 1  upload image      -> [code, payload]  ; 1000 => payload is a result id
    step 2  poll for result   -> [code, payload]  ; 1000 => payload is a target list
                                                    1001 => not ready, retry
                                                    1008 => nothing detected
                                                    1009 => detected but unknown
All of that async complexity is fully wrapped inside run(): the loop and the model
only ever see ONE normalized ToolResult, never the polling.

Every failure mode is normalized inside run() — missing key / no file / >2MB /
upload timeout / non-1000 / poll timeout / 1008-1009 / network / malformed
structure — so a raw exception never escapes into the agent loop (we do NOT rely
on the registry's blanket backstop for the known cases; that was the S3 lesson).
"1008/1009 (not recognized)" is a LEGITIMATE outcome -> ok=True with guidance text,
mirroring range_check's "unknown place / empty list" semantics.

Satisfies the Tool protocol (tools/registry.py):
    name / description / input_schema / schema / risk / run(input, ctx)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

from .. import config
from ..schemas import ToolResult
from .failures import tool_failure
from .registry import ToolContext

# How many candidate species (per detected target) to show the model.
_TOP_CANDIDATES = 3
# Recovery hint shown to the model whenever bird_id can't answer (ok=False).
_FALLBACK = "改用外形描述推断 + range_check 核验（裁决第4条），必要时给 species 标 low_confidence。"

# Upload error codes -> human-readable reason (architecture/plan-confirmed facts).
_UPLOAD_ERR = {
    1001: "图片大小不符合要求",
    1002: "图片格式不支持",
    1003: "设备ID(did)不合法",
    1004: "识别种类(class)不支持",
    1005: "地区不支持",
}


class _HhoError(Exception):
    """A failed bird_id outcome carrying a ready user-facing message (-> ok=False)."""


class _Unrecognized(Exception):
    """'Recognized nothing' (codes 1008/1009) -> ok=True with guidance text."""


class BirdIdInput(BaseModel):
    """Our-side validation: a local image file path is required."""

    image_path: str


class BirdIdTool:
    """The bird_id tool instance registered into the ToolRegistry."""

    name = "bird_id"
    description = (
        "对本地鸟类照片做视觉鉴种（懂鸟服务）。当用户【没给出种名但提供了图片】时，"
        "用本工具上传图片，得到候选鸟种（中文名 + 置信度），你再据此定种。"
        "入参 image_path 是本地图片文件路径（不是 URL）。"
    )
    # JSON Schema handed to the model as the function-declaration parameters.
    input_schema = {
        "type": "object",
        "properties": {
            "image_path": {
                "type": "string",
                "description": "本地鸟类图片文件路径（jpg，≤2MB）",
            },
        },
        "required": ["image_path"],
    }
    schema = BirdIdInput
    risk = "read"

    def run(self, input: dict, ctx: ToolContext) -> ToolResult:
        image_path = input.get("image_path", "")

        # 1. local precheck (cheap; avoids a pointless upload). ok=False on failure.
        err = _check_image(image_path)
        if err is not None:
            return ToolResult(ok=False, output=tool_failure("bird_id", err, _FALLBACK))

        # 2. need the API key; missing key is a real failure.
        key = config.load_hho_api_key()
        if not key:
            return ToolResult(
                ok=False,
                output=tool_failure(
                    "bird_id",
                    "HHO_API_KEY 未设置：请在项目根 .env 写入 HHO_API_KEY=<your-key>。",
                    _FALLBACK,
                ),
            )

        # 3. upload -> poll -> format, normalizing EVERY failure here (no bare stack).
        #    _upload/_poll convert httpx + structure errors into _HhoError, and 1008/
        #    1009 into _Unrecognized; the final (Key/Index/Type/Value)Error clause is
        #    a custom-message net for malformed rows during formatting.
        try:
            result_id = _upload(image_path, key)
            targets = _poll(result_id, key)
            output = _format_candidates(targets)
        except _Unrecognized as e:
            return ToolResult(ok=True, output=str(e))
        except _HhoError as e:
            return ToolResult(ok=False, output=tool_failure("bird_id", str(e), _FALLBACK))
        except (KeyError, IndexError, TypeError, ValueError) as e:
            return ToolResult(
                ok=False,
                output=tool_failure("bird_id", f"懂鸟返回结构异常，无法解析候选：{e}", _FALLBACK),
            )
        return ToolResult(ok=True, output=output)


# ── helpers ──────────────────────────────────────────────────────────────────
def _check_image(image_path: str) -> str | None:
    """Local precheck: return an error message, or None if the file looks OK."""
    if not image_path:
        return "未提供图片路径 image_path。"
    p = Path(image_path)
    if not p.is_file():
        return f"图片文件不存在：{image_path}"
    size = p.stat().st_size
    if size > config.HHO_MAX_IMAGE_BYTES:
        return f"图片过大（{size / 1024 / 1024:.1f}MB，上限 2MB）：请压缩后再试。"
    return None


def _endpoint() -> str:
    return f"{config.HHO_BASE_URL}{config.HHO_PATH}"


def _parse_array(resp: httpx.Response) -> tuple[int, object]:
    """Parse the 懂鸟 [code, payload] array; raise _HhoError on bad JSON / shape."""
    try:
        data = resp.json()
    except (json.JSONDecodeError, ValueError) as e:
        raise _HhoError("懂鸟返回的不是合法 JSON，无法解析。") from e
    if not isinstance(data, list) or len(data) < 2:
        raise _HhoError(f"懂鸟返回结构非预期数组 [code, payload]：{str(data)[:80]}")
    code = data[0]
    if not isinstance(code, int):
        raise _HhoError(f"懂鸟返回的 code 非整数：{str(data)[:80]}")
    return code, data[1]


def _upload(image_path: str, key: str) -> str:
    """Step 1: upload the image, return the recognition id. Failures -> _HhoError.

    Overseas uploads are slow, so httpx's ~5s default WOULD raise WriteTimeout —
    we use a long write/read timeout (the plan-confirmed fix).
    """
    try:
        img_bytes = Path(image_path).read_bytes()
    except OSError as e:
        raise _HhoError(f"无法读取图片文件：{e}") from e

    files = {"image": (Path(image_path).name, img_bytes, "image/jpeg")}
    data = {"upload": "1", "did": config.HHO_DID, "class": config.HHO_CLASS}
    try:
        resp = httpx.post(
            _endpoint(),
            headers={"api_key": key},
            data=data,
            files=files,
            timeout=httpx.Timeout(**config.HHO_UPLOAD_TIMEOUT),
        )
        resp.raise_for_status()
    except httpx.TimeoutException as e:
        raise _HhoError("上传图片到懂鸟超时（海外上传较慢，请稍后重试）。") from e
    except httpx.HTTPStatusError as e:
        raise _HhoError(f"懂鸟上传返回 HTTP {e.response.status_code}。") from e
    except httpx.RequestError as e:
        raise _HhoError("网络连接懂鸟失败（上传阶段）。") from e

    code, payload = _parse_array(resp)
    if code != 1000:
        reason = _UPLOAD_ERR.get(code, f"未知错误码 {code}")
        raise _HhoError(f"懂鸟上传失败：{reason}（code={code}）。")
    if not isinstance(payload, str) or not payload:
        raise _HhoError("懂鸟上传返回的识别ID异常。")
    return payload


def _poll(result_id: str, key: str) -> list:
    """Step 2: poll for the result; return the detection-target list.

    1000 -> targets; 1001 -> sleep & retry (bounded by HHO_POLL_MAX); 1008/1009 ->
    _Unrecognized; any other code or transport failure -> _HhoError.
    """
    # Poll the result with a urlencoded form field (the tested-working call).
    data = {"resultid": result_id}
    for _ in range(config.HHO_POLL_MAX):
        try:
            resp = httpx.post(
                _endpoint(),
                headers={"api_key": key},
                data=data,
                timeout=config.HHO_RESULT_TIMEOUT_S,
            )
            resp.raise_for_status()
        except httpx.TimeoutException as e:
            raise _HhoError("取识别结果超时。") from e
        except httpx.HTTPStatusError as e:
            raise _HhoError(f"懂鸟取结果返回 HTTP {e.response.status_code}。") from e
        except httpx.RequestError as e:
            raise _HhoError("网络连接懂鸟失败（取结果阶段）。") from e

        code, payload = _parse_array(resp)
        if code == 1000:
            if not isinstance(payload, list):
                raise _HhoError("懂鸟结果 payload 非预期的目标数组。")
            return payload
        if code == 1001:  # not finished yet — wait and retry
            time.sleep(config.HHO_POLL_INTERVAL_S)
            continue
        if code in (1008, 1009):
            raise _Unrecognized(
                "懂鸟未能识别这张图片里的鸟种（未检测到目标或无法判定）；"
                "请改用外形描述推断，或让用户人工指定。"
            )
        raise _HhoError(f"懂鸟取结果返回异常码 {code}。")

    raise _HhoError(
        f"懂鸟识别超时：轮询 {config.HHO_POLL_MAX} 次仍未出结果，请稍后重试。"
    )


def _format_candidates(targets: list, top: int = _TOP_CANDIDATES) -> str:
    """Render top candidates (Chinese name + confidence) per detected target.

    Each target: {"box":[...], "list":[[conf, "中文名|英文名|拉丁名", id, cls], ...]}.
    Confidence is 0~100 (NOT 0~1); the species field is pipe-joined, take the first
    segment (Chinese name). `list` is already sorted by confidence descending.
    """
    multi = len(targets) > 1
    lines: list[str] = []
    for i, target in enumerate(targets, 1):
        candidates = target.get("list") or []
        parts = []
        for row in candidates[:top]:
            conf = row[0]  # 0~100
            cn = str(row[1]).split("|")[0] or "?"  # 中文名|英文名|拉丁名 -> 中文名
            parts.append(f"{cn} {conf}%")
        if parts:
            prefix = f"目标{i}：" if multi else ""
            lines.append(prefix + "、".join(parts))

    if not lines:
        return "懂鸟检测到目标但没有给出候选种。"
    return "懂鸟视觉鉴种候选（置信度为 0~100 百分制，已按置信度排序）：\n" + "\n".join(lines)
