#!/usr/bin/env python
"""Offline verification for v2 slice 2.1 text splitting.

No network, database, real model, photo API, or taxonomy data is used.
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.schemas import DraftObservation, ModelResponse, ToolCall  # noqa: E402
from vibirding.services.parse import (  # noqa: E402
    RETURN_TEXT_SPLIT_TOOL,
    TextSplitError,
    TextSplitService,
)


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def response(payload: dict, *, name: str = "return_text_split") -> ModelResponse:
    return ModelResponse(
        stop_reason="tool_use",
        tool_calls=[ToolCall(id="split-1", name=name, input=payload)],
    )


def service(payload: dict) -> TextSplitService:
    return TextSplitService(MockClient([response(payload)]))


BASE_PAYLOAD = {
    "shared_context": {
        "place": "井之头公园",
        "obs_date": "2026-09-05",
        "time_of_day": "上午",
    },
    "observations": [
        {"species_label": "灰喜鹊", "count": 3, "raw_note": "3只灰喜鹊"},
        {
            "species_label": "北长尾山雀",
            "count": 10,
            "raw_note": "一群十只左右的北长尾山雀",
        },
        {"species_label": "鸬鹚", "count": 2, "raw_note": "两只鸬鹚"},
    ],
}


# Public schema and return-tool contract.
check(
    "DraftObservation 字段与架构一致",
    set(DraftObservation.model_fields)
    == {
        "client_draft_id",
        "place",
        "obs_date",
        "time_of_day",
        "count",
        "behavior",
        "raw_note",
        "species_label",
        "species_id",
        "confidence",
        "source",
        "flags",
        "photo_ids",
        "needs_confirmation",
    },
)
check("返回工具名固定", RETURN_TEXT_SPLIT_TOOL["name"] == "return_text_split")
check("返回工具要求 shared_context 和 observations", set(RETURN_TEXT_SPLIT_TOOL["input_schema"]["required"]) == {"shared_context", "observations"})


# Main example: one note becomes three ordered drafts with inherited context.
drafts = service(BASE_PAYLOAD).split("我今天在井之头公园看到了三种鸟", date(2026, 9, 5))
check("一篇笔记拆成 3 条", len(drafts) == 3, str(len(drafts)))
check("保持物种顺序", [d.species_label for d in drafts] == ["灰喜鹊", "北长尾山雀", "鸬鹚"])
check("共享地点下发到每条", all(d.place == "井之头公园" for d in drafts))
check("共享日期下发到每条", all(d.obs_date == "2026-09-05" for d in drafts))
check("共享时段下发到每条", all(d.time_of_day == "上午" for d in drafts))
check("每条保留自己的数量", [d.count for d in drafts] == [3, 10, 2])
check("每条保留自己的原文片段", [d.raw_note for d in drafts] == ["3只灰喜鹊", "一群十只左右的北长尾山雀", "两只鸬鹚"])
check("草稿编号按响应内顺序生成", [d.client_draft_id for d in drafts] == ["draft-1", "draft-2", "draft-3"])
check("2.1 不填物种 ID", all(d.species_id is None for d in drafts))
check("2.1 不关联照片", all(d.photo_ids == [] for d in drafts))
check("文本草稿来源固定为 user", all(d.source == "user" for d in drafts))


# Per-item values override the shared context; explicit null also overrides.
override_payload = {
    "shared_context": {"place": "井之头公园", "obs_date": "2026-09-05"},
    "observations": [
        {"species_label": "灰喜鹊", "raw_note": "公园里的灰喜鹊"},
        {
            "place": "善福寺公园",
            "obs_date": "2026-09-04",
            "species_label": "翠鸟",
            "raw_note": "昨天在善福寺公园看到翠鸟",
        },
        {"place": None, "species_label": "乌鸦", "raw_note": "另有一只乌鸦，地点不确定"},
    ],
}
overrides = service(override_payload).split("mixed", date(2026, 9, 5))
check("条目自己的上下文覆盖共享值", (overrides[1].place, overrides[1].obs_date) == ("善福寺公园", "2026-09-04"))
check("显式 null 可清除共享值", overrides[2].place is None)


# Unknown species must be visible to the user even if the model forgot the flag.
unknown_payload = {
    "shared_context": {"place": "井之头公园"},
    "observations": [{"species_label": None, "raw_note": "还有一只认不出的褐色小鸟"}],
}
unknown = service(unknown_payload).split("unknown")[0]
check("未知物种强制待确认", unknown.needs_confirmation is True)


# Capture the provider-neutral request and fixed reference date.
class CapturingMock(MockClient):
    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> ModelResponse:
        self.messages = messages
        self.tools = tools
        return super().complete(messages, tools)


capturing = CapturingMock([response(BASE_PAYLOAD)])
TextSplitService(capturing).split("note", date(2024, 2, 29))
check("固定参考日期传给模型", "2024-02-29" in capturing.messages[1]["content"])
check("只声明结构化返回工具", capturing.tools == [RETURN_TEXT_SPLIT_TOOL])
check("每次拆分只调用模型一次", capturing._i == 1, str(capturing._i))
check("解析模块未加载数据库代码", not any(name.startswith("vibirding.db") for name in sys.modules))


# Invalid input or model output fails closed.
try:
    TextSplitService(MockClient([])).split("   ")
    blank_failed = False
except TextSplitError:
    blank_failed = True
check("空白输入被拒绝且不调用模型", blank_failed)

bad_responses = [
    ("没有工具调用", ModelResponse(stop_reason="end_turn", text="自由文本")),
    ("错误工具名", response(BASE_PAYLOAD, name="other_tool")),
    (
        "重复工具调用",
        ModelResponse(
            stop_reason="tool_use",
            tool_calls=[
                ToolCall(id="a", name="return_text_split", input=BASE_PAYLOAD),
                ToolCall(id="b", name="return_text_split", input=BASE_PAYLOAD),
            ],
        ),
    ),
    ("空 observations", response({"shared_context": {}, "observations": []})),
    (
        "字段类型错误",
        response(
            {
                "shared_context": {},
                "observations": [{"species_label": "灰喜鹊", "count": "三只", "raw_note": "灰喜鹊"}],
            }
        ),
    ),
    (
        "空白 raw_note",
        response(
            {
                "shared_context": {},
                "observations": [{"species_label": "灰喜鹊", "raw_note": "   "}],
            }
        ),
    ),
    (
        "非 ISO 日期",
        response(
            {
                "shared_context": {"obs_date": "今天"},
                "observations": [{"species_label": "灰喜鹊", "raw_note": "灰喜鹊"}],
            }
        ),
    ),
]
for label, bad_response in bad_responses:
    try:
        TextSplitService(MockClient([bad_response])).split("note")
        failed_closed = False
    except TextSplitError:
        failed_closed = True
    check(f"{label}时整批失败", failed_closed)


def main() -> int:
    print("=" * 72)
    print("v2 2.1 文本拆分验证 — 离线、无网络、无数据库")
    print("=" * 72)
    passed = 0
    for name, ok, detail in _RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f" <- {detail}" if not ok and detail else ""))
        passed += ok
    print("-" * 72)
    print(f"通过 {passed}/{len(_RESULTS)}")
    return 0 if passed == len(_RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
