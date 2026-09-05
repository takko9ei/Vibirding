#!/usr/bin/env python
"""Offline verification for v2 slice 2.2 photo preprocessing."""

from __future__ import annotations

import sys
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from pydantic import ValidationError  # noqa: E402

from vibirding.schemas import (  # noqa: E402
    BirdIdCandidate,
    BirdIdResult,
    PhotoIdentification,
    PhotoInput,
)
from vibirding.services.parse import (  # noqa: E402
    PhotoPreprocessError,
    PhotoPreprocessService,
)
from vibirding.tools.bird_id import _parse_candidates  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


def uid(number: int) -> UUID:
    return UUID(int=number)


def candidate(label: str, confidence: float, provider_id: str) -> BirdIdCandidate:
    return BirdIdCandidate(
        species_label=label,
        english_name=f"{label} English",
        scientific_name=f"{label} scientific",
        confidence=confidence,
        provider_candidate_id=provider_id,
    )


class FakeBirdIdentifier:
    def __init__(self, results: dict[str, BirdIdResult]) -> None:
        self.results = results
        self.calls: list[str] = []

    def identify(self, image_path: str) -> BirdIdResult:
        self.calls.append(image_path)
        return self.results[image_path]


# Provider rows are normalized without losing useful taxonomy inputs.
raw_targets = [
    {
        "box": [0, 0, 10, 10],
        "list": [
            [98, "灰喜鹊|Azure-winged Magpie|Cyanopica cyanus", 101, "B"],
            [75.5, "喜鹊|Oriental Magpie|Pica serica", 102, "B"],
        ],
    }
]
parsed = _parse_candidates(raw_targets)
first = parsed[0][0]
check("中文名拆分正确", first.species_label == "灰喜鹊")
check("英文名拆分正确", first.english_name == "Azure-winged Magpie")
check("学名拆分正确", first.scientific_name == "Cyanopica cyanus")
check("置信度保留 0~100 百分制", first.confidence == 98.0)
check("保留懂鸟候选 ID", first.provider_candidate_id == "101")
check("候选顺序不被重排", parsed[0][1].species_label == "喜鹊")


# More than three provider candidates are intentionally discarded per target.
many_rows = [
    {
        "list": [
            [90 - i, f"种{i}|English {i}|Scientific {i}", i, "B"]
            for i in range(5)
        ]
    }
]
check("每个目标最多保留前三候选", len(_parse_candidates(many_rows)[0]) == 3)


# Batch behavior: order, first candidate, first target, and isolated outcomes.
gray = candidate("灰喜鹊", 98.0, "101")
magpie = candidate("喜鹊", 75.5, "102")
cormorant = candidate("鸬鹚", 96.0, "201")
identifier = FakeBirdIdentifier(
    {
        "a.jpg": BirdIdResult(
            status="identified",
            targets=[[gray, magpie], [cormorant]],
        ),
        "b.jpg": BirdIdResult(
            status="unrecognized", message="没有检测到可识别鸟种"
        ),
        "c.jpg": BirdIdResult(status="failed", message="上传超时"),
        "d.jpg": BirdIdResult(status="identified", targets=[[], [cormorant]]),
    }
)
photos = [
    PhotoInput(photo_id=uid(1), image_path="a.jpg"),
    PhotoInput(photo_id=uid(2), image_path="b.jpg"),
    PhotoInput(photo_id=uid(3), image_path="c.jpg"),
    PhotoInput(photo_id=uid(4), image_path="d.jpg"),
]
results = PhotoPreprocessService(identifier).preprocess(photos)
check("每张输入照片恰有一个结果", len(results) == len(photos))
check("结果保持照片输入顺序", [r.photo_id for r in results] == [p.photo_id for p in photos])
check("每张照片只调用一次适配器", identifier.calls == ["a.jpg", "b.jpg", "c.jpg", "d.jpg"])
check("只取第一目标第一候选", results[0].candidate == gray)
check("不使用第二候选", results[0].candidate != magpie)
check("不使用照片内第二目标", results[0].candidate != cormorant)
check("未识别结果保持可见", results[1].status == "unrecognized" and results[1].candidate is None)
check("未识别原因进入 warning", results[1].warning == "没有检测到可识别鸟种")
check("单图失败不阻断后续照片", results[2].status == "failed" and results[3].photo_id == uid(4))
check("失败原因进入 warning", results[2].warning == "上传超时")
check("第一目标无候选时不偷用第二目标", results[3].status == "unrecognized" and results[3].candidate is None)


# Empty input and duplicate IDs are deterministic and make no adapter calls.
empty_identifier = FakeBirdIdentifier({})
empty = PhotoPreprocessService(empty_identifier).preprocess([])
check("空批次返回空列表", empty == [])
check("空批次不调用适配器", empty_identifier.calls == [])

duplicate_identifier = FakeBirdIdentifier({"a.jpg": BirdIdResult(status="unrecognized")})
try:
    PhotoPreprocessService(duplicate_identifier).preprocess(
        [
            PhotoInput(photo_id=uid(9), image_path="a.jpg"),
            PhotoInput(photo_id=uid(9), image_path="a.jpg"),
        ]
    )
    duplicate_failed = False
except PhotoPreprocessError:
    duplicate_failed = True
check("重复 photo_id 整批拒绝", duplicate_failed)
check("重复 ID 在调用外部适配器前发现", duplicate_identifier.calls == [])


try:
    PhotoInput(photo_id=uid(10), image_path="   ")
    blank_path_failed = False
except ValidationError:
    blank_path_failed = True
check("空白图片路径被拒绝", blank_path_failed)

check(
    "PhotoIdentification 字段与架构一致",
    set(PhotoIdentification.model_fields)
    == {"photo_id", "candidate", "status", "warning"},
)
check("批处理未加载数据库代码", not any(name.startswith("vibirding.db") for name in sys.modules))
check("批处理未加载 LLM 代码", not any(name.startswith("vibirding.llm") for name in sys.modules))


def main() -> int:
    print("=" * 72)
    print("v2 2.2 照片预处理验证 — 离线、无网络、无数据库、无真实图片")
    print("=" * 72)
    passed = 0
    for name, ok, detail in _RESULTS:
        print(
            f"  {'PASS' if ok else 'FAIL'}  {name}"
            + (f" <- {detail}" if not ok and detail else "")
        )
        passed += ok
    print("-" * 72)
    print(f"通过 {passed}/{len(_RESULTS)}")
    return 0 if passed == len(_RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
