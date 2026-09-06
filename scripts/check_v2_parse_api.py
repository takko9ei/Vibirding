#!/usr/bin/env python
"""HTTP verification for v2 slice 3.2 side-effect-free parse previews."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.api.app import create_app  # noqa: E402
from vibirding.db.models import ObservationRow, PhotoRow, SessionRow  # noqa: E402
from vibirding.llm.mock import MockClient  # noqa: E402
from vibirding.schemas import (  # noqa: E402
    BirdIdCandidate,
    BirdIdResult,
    ModelResponse,
    SpeciesCatalogEntry,
    ToolCall,
)
from vibirding.services.assembly import ParseAssemblyService  # noqa: E402
from vibirding.services.matching import DryRunMatchingService  # noqa: E402
from vibirding.services.parse import (  # noqa: E402
    PhotoPreprocessService,
    TextSplitService,
)
from vibirding.services.preview import ParsePreviewService  # noqa: E402
from vibirding.services.taxonomy import TaxonomyService  # noqa: E402


_RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, passed: bool, detail: str = "") -> None:
    _RESULTS.append((name, bool(passed), detail))


class FakeBirdIdentifier:
    """Return deterministic provider results based on uploaded file bytes."""

    def __init__(self, results_by_bytes: dict[bytes, BirdIdResult]) -> None:
        self._results_by_bytes = results_by_bytes
        self.seen_paths: list[str] = []

    def identify(self, image_path: str) -> BirdIdResult:
        self.seen_paths.append(image_path)
        path = Path(image_path)
        if not path.is_file():
            return BirdIdResult(status="failed", message="媒体文件不存在。")
        return self._results_by_bytes[path.read_bytes()]


def split_response(*observations: dict) -> ModelResponse:
    return ModelResponse(
        tool_calls=[
            ToolCall(
                id=f"split-{uuid4()}",
                name="return_text_split",
                input={
                    "shared_context": {
                        "place": "井之头公园",
                        "obs_date": "2026-09-06",
                        "time_of_day": "上午",
                    },
                    "observations": list(observations),
                },
            )
        ],
        stop_reason="tool_use",
    )


def build_preview_service(
    session_factory,
    llm: MockClient,
    bird_identifier: FakeBirdIdentifier,
) -> ParsePreviewService:
    taxonomy = TaxonomyService(session_factory)
    return ParsePreviewService(
        session_factory=session_factory,
        text_splitter=TextSplitService(llm),
        photo_preprocessor=PhotoPreprocessService(bird_identifier),
        assembly=ParseAssemblyService(DryRunMatchingService(taxonomy)),
    )


jpeg_matched = b"\xff\xd8\xff\xe0matched-grey-treepie\xff\xd9"
jpeg_unmatched = b"\xff\xd8\xff\xe1unmatched-cormorant\xff\xd9"
jpeg_failed = b"\xff\xd8\xff\xe2failed-photo\xff\xd9"

matched_result = BirdIdResult(
    status="identified",
    targets=[
        [
            BirdIdCandidate(
                species_label="灰喜鹊",
                scientific_name="Cyanopica cyanus",
                confidence=97.2,
                provider_candidate_id="hho-grey",
            )
        ]
    ],
)
unmatched_result = BirdIdResult(
    status="identified",
    targets=[
        [
            BirdIdCandidate(
                species_label="普通鸬鹚",
                scientific_name="Phalacrocorax carbo",
                confidence=91.0,
                provider_candidate_id="hho-cormorant",
            )
        ]
    ],
)
failed_result = BirdIdResult(status="failed", message="模拟懂鸟暂时不可用。")


with TemporaryDirectory(prefix="vibirding-parse-api-") as temp_dir:
    media_dir = Path(temp_dir)
    with temporary_schema("parse_api") as session_factory:
        taxonomy = TaxonomyService(session_factory)
        taxonomy.import_entries(
            [
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="azwmag1",
                    canonical_chinese_name="灰喜鹊",
                    scientific_name="Cyanopica cyanus",
                ),
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="lottit1",
                    canonical_chinese_name="北长尾山雀",
                    scientific_name="Aegithalos caudatus",
                ),
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="grecor",
                    canonical_chinese_name="普通鸬鹚",
                    scientific_name="Phalacrocorax carbo",
                ),
            ]
        )

        llm = MockClient(
            [
                split_response(
                    {
                        "species_label": "灰喜鹊",
                        "count": 3,
                        "raw_note": "看到了3只灰喜鹊",
                    },
                    {
                        "species_label": "北长尾山雀",
                        "count": 10,
                        "raw_note": "一群十只左右的北长尾山雀",
                    },
                ),
                split_response(
                    {
                        "species_label": "北长尾山雀",
                        "count": 2,
                        "raw_note": "两只北长尾山雀",
                    }
                ),
            ]
        )
        bird_identifier = FakeBirdIdentifier(
            {
                jpeg_matched: matched_result,
                jpeg_unmatched: unmatched_result,
                jpeg_failed: failed_result,
            }
        )
        preview_service = build_preview_service(
            session_factory,
            llm,
            bird_identifier,
        )
        app = create_app(
            session_factory=session_factory,
            media_dir=media_dir,
            parse_service=preview_service,
        )

        with TestClient(app) as client:
            def upload(name: str, content: bytes) -> dict:
                response = client.post(
                    "/api/media",
                    files={"photo": (name, content, "image/jpeg")},
                )
                check(f"测试媒体 {name} 上传成功", response.status_code == 201)
                return response.json()

            matched_media = upload("matched.jpg", jpeg_matched)
            unmatched_media = upload("unmatched.jpg", jpeg_unmatched)
            failed_media = upload("failed.jpg", jpeg_failed)
            ordered_media_ids = [
                failed_media["media_id"],
                unmatched_media["media_id"],
                matched_media["media_id"],
            ]

            parsed = client.post(
                "/api/parse",
                json={
                    "text": (
                        "我今天在井之头公园看到了3只灰喜鹊，"
                        "一群十只左右的北长尾山雀"
                    ),
                    "media_ids": ordered_media_ids,
                },
            )
            payload = parsed.json()
            check("图文解析返回 200", parsed.status_code == 200, parsed.text)
            check(
                "响应字段与 ParseResult 一致",
                set(payload)
                == {
                    "draft_observations",
                    "unmatched_photos",
                    "warnings",
                    "job_status",
                },
            )
            check("同步任务状态为 completed", payload["job_status"] == "completed")
            check("两条文本加一条照片草稿", len(payload["draft_observations"]) == 3)

            drafts = {
                draft["client_draft_id"]: draft
                for draft in payload["draft_observations"]
            }
            check(
                "共享地点日期时段下发",
                all(
                    draft["place"] == "井之头公园"
                    and draft["obs_date"] == "2026-09-06"
                    and draft["time_of_day"] == "上午"
                    for draft in drafts.values()
                ),
            )
            check(
                "匹配照片归入灰喜鹊文本草稿",
                drafts["draft-1"]["photo_ids"] == [matched_media["media_id"]],
            )
            check(
                "文字数量不被照片覆盖",
                drafts["draft-1"]["count"] == 3,
            )
            check(
                "未匹配鸬鹚生成照片草稿",
                drafts["photo-draft-1"]["species_label"] == "普通鸬鹚"
                and drafts["photo-draft-1"]["photo_ids"]
                == [unmatched_media["media_id"]],
            )
            check(
                "自动照片草稿强制待确认",
                drafts["photo-draft-1"]["needs_confirmation"] is True
                and drafts["photo-draft-1"]["source"] == "bird_id",
            )
            check(
                "unmatched_photos 保留照片到草稿映射",
                payload["unmatched_photos"]
                == [
                    {
                        "photo_id": unmatched_media["media_id"],
                        "client_draft_id": "photo-draft-1",
                    }
                ],
            )
            check(
                "单张懂鸟失败只产生 warning",
                any("模拟懂鸟暂时不可用" in item for item in payload["warnings"]),
            )
            check(
                "照片按请求 media_ids 顺序处理",
                [Path(path).read_bytes() for path in bird_identifier.seen_paths]
                == [jpeg_failed, jpeg_unmatched, jpeg_matched],
            )

            Path(bird_identifier.seen_paths[0]).unlink()
            missing_file = client.post(
                "/api/parse",
                json={"text": "", "media_ids": [failed_media["media_id"]]},
            )
            check("已登记但文件缺失仍返回预览", missing_file.status_code == 200)
            check(
                "文件缺失作为照片 warning 返回",
                any(
                    "媒体文件不存在" in item
                    for item in missing_file.json()["warnings"]
                ),
            )

            calls_before_photo_only = llm._i
            photo_only = client.post(
                "/api/parse",
                json={"text": "   ", "media_ids": [matched_media["media_id"]]},
            )
            photo_only_payload = photo_only.json()
            check("纯照片解析返回 200", photo_only.status_code == 200)
            check("纯照片不调用 LLM", llm._i == calls_before_photo_only)
            check(
                "纯照片自动生成一条待确认草稿",
                len(photo_only_payload["draft_observations"]) == 1
                and photo_only_payload["draft_observations"][0]["source"]
                == "bird_id",
            )

            photo_calls_before_text_only = len(bird_identifier.seen_paths)
            text_only = client.post(
                "/api/parse",
                json={"text": "两只北长尾山雀", "media_ids": []},
            )
            check("纯文本解析返回 200", text_only.status_code == 200)
            check(
                "纯文本不调用懂鸟",
                len(bird_identifier.seen_paths) == photo_calls_before_text_only,
            )
            check(
                "纯文本仍完成名录规范化",
                text_only.json()["draft_observations"][0]["species_id"]
                is not None,
            )

            external_counts = (llm._i, len(bird_identifier.seen_paths))
            unknown_id = str(uuid4())
            unknown = client.post(
                "/api/parse",
                json={"text": "不应调用模型", "media_ids": [unknown_id]},
            )
            check("未知媒体返回 404", unknown.status_code == 404, unknown.text)
            check("404 明确列出未知媒体", unknown_id in unknown.json()["detail"])
            check(
                "未知媒体在任何外部调用前拒绝",
                (llm._i, len(bird_identifier.seen_paths)) == external_counts,
            )

            invalid_requests = [
                (
                    "文本和媒体同时为空返回 422",
                    {"text": "  ", "media_ids": []},
                ),
                (
                    "重复媒体返回 422",
                    {
                        "text": "记录",
                        "media_ids": [
                            matched_media["media_id"],
                            matched_media["media_id"],
                        ],
                    },
                ),
                (
                    "非法 UUID 返回 422",
                    {"text": "记录", "media_ids": ["not-a-uuid"]},
                ),
                (
                    "额外请求字段返回 422",
                    {"text": "记录", "media_ids": [], "confirmed": True},
                ),
            ]
            for name, body in invalid_requests:
                response = client.post("/api/parse", json=body)
                check(name, response.status_code == 422, response.text)
            check(
                "422 请求不触发外部调用",
                (llm._i, len(bird_identifier.seen_paths)) == external_counts,
            )

        invalid_model_service = build_preview_service(
            session_factory,
            MockClient(
                [
                    ModelResponse(
                        text="自由文本，没有结构化工具调用",
                        stop_reason="end_turn",
                    )
                ]
            ),
            FakeBirdIdentifier(
                {
                    jpeg_matched: matched_result,
                    jpeg_unmatched: unmatched_result,
                    jpeg_failed: failed_result,
                }
            ),
        )
        invalid_model_app = create_app(
            session_factory=session_factory,
            media_dir=media_dir,
            parse_service=invalid_model_service,
        )
        with TestClient(invalid_model_app) as client:
            upstream_failure = client.post(
                "/api/parse",
                json={"text": "模型返回坏结构", "media_ids": []},
            )
            check(
                "模型结构失败返回 502",
                upstream_failure.status_code == 502,
                upstream_failure.text,
            )
            check("502 包含可诊断错误", bool(upstream_failure.json().get("detail")))

        with patch("vibirding.api.app._build_parse_service") as builder:
            lazy_app = create_app(
                session_factory=session_factory,
                media_dir=media_dir,
            )
            with TestClient(lazy_app) as client:
                openapi = client.get("/openapi.json")
            check("默认应用可在未初始化 AI provider 时启动", openapi.status_code == 200)
            check("未请求 parse 时不创建 AI 流水线", builder.call_count == 0)

        with session_factory() as session:
            photos = session.scalars(select(PhotoRow).order_by(PhotoRow.id)).all()
            observation_count = session.scalar(
                select(func.count()).select_from(ObservationRow)
            )
            session_count = session.scalar(
                select(func.count()).select_from(SessionRow)
            )
        check("测试只保留三条上传媒体", len(photos) == 3)
        check(
            "parse 不缓存或修改照片识别字段",
            all(
                row.species_label is None
                and row.scientific_name is None
                and row.confidence is None
                and row.provider_candidate_id is None
                and row.species_id is None
                and row.session_id is None
                and row.observation_id is None
                for row in photos
            ),
        )
        check(
            "parse 不写 observations/sessions",
            [observation_count, session_count] == [0, 0],
        )


def main() -> int:
    print("=" * 72)
    print("v2 3.2 FastAPI 解析预览验证 — 离线 provider、临时 schema/目录")
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
