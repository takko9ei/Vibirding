#!/usr/bin/env python
"""End-to-end API acceptance for v2 slice 3.8 over a real Uvicorn socket."""

from __future__ import annotations

import socket
import sys
import threading
import time
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import UUID, uuid4

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

import httpx  # noqa: E402
import uvicorn  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402

from scripts.db_test_support import temporary_schema  # noqa: E402
from vibirding.api.app import create_app  # noqa: E402
from vibirding.db.models import (  # noqa: E402
    ObservationRow,
    PhotoRow,
    SessionRow,
)
from vibirding.db.session import build_engine  # noqa: E402
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


def business_counts(session_factory) -> tuple[int, int, int]:
    with session_factory() as session:
        return (
            session.scalar(select(func.count()).select_from(ObservationRow)) or 0,
            session.scalar(select(func.count()).select_from(SessionRow)) or 0,
            session.scalar(select(func.count()).select_from(PhotoRow)) or 0,
        )


def acceptance_schema_count() -> int:
    engine = build_engine()
    try:
        with engine.connect() as connection:
            return (
                connection.execute(
                    text(
                        "select count(*) from information_schema.schemata "
                        "where schema_name like 'api_acceptance_%'"
                    )
                ).scalar()
                or 0
            )
    finally:
        engine.dispose()


class FakeBirdIdentifier:
    """Return deterministic candidates from the exact uploaded JPEG bytes."""

    def __init__(self, results_by_bytes: dict[bytes, BirdIdResult]) -> None:
        self._results_by_bytes = results_by_bytes
        self.call_count = 0

    def identify(self, image_path: str) -> BirdIdResult:
        self.call_count += 1
        return self._results_by_bytes[Path(image_path).read_bytes()]


def split_response() -> ModelResponse:
    return ModelResponse(
        tool_calls=[
            ToolCall(
                id="acceptance-split",
                name="return_text_split",
                input={
                    "shared_context": {
                        "place": "井之头公园",
                        "obs_date": "2026-09-07",
                        "time_of_day": "上午",
                    },
                    "observations": [
                        {
                            "species_label": "灰喜鹊",
                            "count": 3,
                            "behavior": "在树梢活动",
                            "raw_note": "看见三只灰喜鹊",
                        }
                    ],
                },
            )
        ],
        stop_reason="tool_use",
    )


def start_uvicorn(app):
    """Start Uvicorn on an OS-assigned loopback port and return its controls."""
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen(2048)
    port = listener.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=2,
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.02)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=2)
        listener.close()
        raise RuntimeError("Uvicorn did not start within 10 seconds")
    return server, thread, listener, f"http://127.0.0.1:{port}"


jpeg_grey = b"\xff\xd8\xff\xe0acceptance-grey-treepie\xff\xd9"
jpeg_cormorant = b"\xff\xd8\xff\xe1acceptance-cormorant\xff\xd9"
schema_count_before = acceptance_schema_count()
temp_media_path: Path | None = None

with TemporaryDirectory(prefix="vibirding-api-acceptance-") as temp_dir:
    temp_media_path = Path(temp_dir)
    with temporary_schema("api_acceptance") as session_factory:
        grey, cormorant = TaxonomyService(session_factory).import_entries(
            [
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="azwmag1",
                    canonical_chinese_name="灰喜鹊",
                    scientific_name="Cyanopica cyanus",
                    aliases=["山喜鹊"],
                ),
                SpeciesCatalogEntry(
                    taxonomy_source="ebird",
                    taxonomy_key="grecor",
                    canonical_chinese_name="普通鸬鹚",
                    scientific_name="Phalacrocorax carbo",
                    aliases=["鸬鹚"],
                ),
            ]
        )
        llm = MockClient([split_response()])
        bird_identifier = FakeBirdIdentifier(
            {
                jpeg_grey: BirdIdResult(
                    status="identified",
                    targets=[
                        [
                            BirdIdCandidate(
                                species_label="灰喜鹊",
                                scientific_name="Cyanopica cyanus",
                                confidence=97,
                                provider_candidate_id="offline-grey",
                            )
                        ]
                    ],
                ),
                jpeg_cormorant: BirdIdResult(
                    status="identified",
                    targets=[
                        [
                            BirdIdCandidate(
                                species_label="普通鸬鹚",
                                scientific_name="Phalacrocorax carbo",
                                confidence=93,
                                provider_candidate_id="offline-cormorant",
                            )
                        ]
                    ],
                ),
            }
        )
        taxonomy = TaxonomyService(session_factory)
        parse_service = ParsePreviewService(
            session_factory=session_factory,
            text_splitter=TextSplitService(llm),
            photo_preprocessor=PhotoPreprocessService(bird_identifier),
            assembly=ParseAssemblyService(DryRunMatchingService(taxonomy)),
        )
        app = create_app(
            session_factory=session_factory,
            media_dir=temp_media_path,
            parse_service=parse_service,
        )
        server, thread, listener, base_url = start_uvicorn(app)
        check("真实 Uvicorn 已监听 loopback 端口", server.started)

        try:
            with httpx.Client(base_url=base_url, timeout=10) as client:
                openapi_response = client.get("/openapi.json")
                docs_response = client.get("/docs")
                check("OpenAPI 与 Swagger 文档可访问", openapi_response.status_code == 200 and docs_response.status_code == 200)
                openapi = openapi_response.json()
                expected_operations = {
                    ("/api/media", "post"),
                    ("/api/parse", "post"),
                    ("/api/observations", "post"),
                    ("/api/observations", "get"),
                    ("/api/observations/{observation_id}", "get"),
                    ("/api/observations/{observation_id}", "patch"),
                    ("/api/observations/{observation_id}", "delete"),
                    ("/api/species", "get"),
                }
                actual_operations = {
                    (path, method)
                    for path, path_item in openapi["paths"].items()
                    for method in path_item
                    if method in {"get", "post", "patch", "delete"}
                }
                check("OpenAPI 恰好登记 3.1–3.7 八个方法/路径", actual_operations == expected_operations, str(actual_operations))
                expected_schemas = {
                    "MediaUploadResponse",
                    "ParseRequest",
                    "ParseResult",
                    "ObservationCreateRequest",
                    "BatchWriteResult",
                    "ObservationListResponse",
                    "ObservationDetail",
                    "ObservationUpdateRequest",
                    "SpeciesSearchResponse",
                }
                actual_schemas = set(openapi["components"]["schemas"])
                check("OpenAPI 包含全部关键公开 schema", expected_schemas <= actual_schemas)
                check("OpenAPI 声明确认写入 201 与删除 204", "201" in openapi["paths"]["/api/observations"]["post"]["responses"] and "204" in openapi["paths"]["/api/observations/{observation_id}"]["delete"]["responses"])

                uploads = []
                for filename, content in [
                    ("grey.jpg", jpeg_grey),
                    ("cormorant.jpg", jpeg_cormorant),
                ]:
                    response = client.post(
                        "/api/media",
                        files={"photo": (filename, content, "image/jpeg")},
                    )
                    check(f"上传 {filename} 返回 201", response.status_code == 201, response.text)
                    uploads.append(response.json())
                duplicate = client.post(
                    "/api/media",
                    files={"photo": ("same-grey.jpg", jpeg_grey, "image/jpeg")},
                )
                check("重复媒体返回 200 并复用 media_id", duplicate.status_code == 200 and duplicate.json()["media_id"] == uploads[0]["media_id"])
                check("上传后仅新增两条 photos", business_counts(session_factory) == (0, 0, 2))

                parse_request = {
                    "text": "今天在井之头公园看见三只灰喜鹊",
                    "media_ids": [item["media_id"] for item in uploads],
                }
                parsed = client.post("/api/parse", json=parse_request)
                check("图文解析预览返回 200", parsed.status_code == 200, parsed.text)
                preview = parsed.json()
                drafts = preview["draft_observations"]
                check("预览包含文本草稿和未匹配照片草稿", len(drafts) == 2 and drafts[0]["client_draft_id"] == "draft-1" and drafts[1]["client_draft_id"].startswith("photo-draft-"))
                check("灰喜鹊照片匹配文字、鸬鹚照片自动建草稿", drafts[0]["photo_ids"] == [uploads[0]["media_id"]] and drafts[1]["photo_ids"] == [uploads[1]["media_id"]])
                check("正式拆分与照片预处理各调用预期次数", llm._i == 1 and bird_identifier.call_count == 2)
                check("parse 保持数据库零 observation/session 写入", business_counts(session_factory) == (0, 0, 2))

                unknown_parse = client.post(
                    "/api/parse",
                    json={"text": "无效媒体", "media_ids": [str(uuid4())]},
                )
                check("未知媒体 parse 返回 404 且不调用 provider", unknown_parse.status_code == 404 and llm._i == 1 and bird_identifier.call_count == 2)

                confirmation = {
                    "text": parse_request["text"],
                    "media_ids": parse_request["media_ids"],
                    "observations": drafts,
                    "confirmed": False,
                }
                unconfirmed = client.post("/api/observations", json=confirmation)
                check("未确认写入返回 400", unconfirmed.status_code == 400)
                check("未确认保持零 observation/session", business_counts(session_factory) == (0, 0, 2))

                confirmation["confirmed"] = True
                confirmed = client.post("/api/observations", json=confirmation)
                check("确认批次返回 201", confirmed.status_code == 201, confirmed.text)
                write_result = confirmed.json()
                check("确认完整创建两条且无失败", len(write_result["created"]) == 2 and write_result["failed"] == [])
                created_by_draft = {
                    item["client_draft_id"]: item["observation_id"]
                    for item in write_result["created"]
                }
                grey_observation_id = created_by_draft["draft-1"]
                cormorant_draft_id = drafts[1]["client_draft_id"]
                cormorant_observation_id = created_by_draft[cormorant_draft_id]
                check("确认后数据库关系数量正确", business_counts(session_factory) == (2, 1, 2))

                listed = client.get("/api/observations")
                listed_ids = [item["observation_id"] for item in listed.json()["items"]]
                check("列表返回两条且最新优先", listed.status_code == 200 and listed_ids == [cormorant_observation_id, grey_observation_id])
                grey_detail = client.get(f"/api/observations/{grey_observation_id}")
                check("详情返回照片与 completed session", grey_detail.status_code == 200 and grey_detail.json()["photo_count"] == 1 and grey_detail.json()["session"]["status"] == "completed")
                check("两个媒体 URL 均可读取", all(client.get(item["url"]).status_code == 200 for item in uploads))

                species_response = client.get(
                    "/api/species", params={"q": "山喜鹊"}
                )
                species_items = species_response.json()["items"]
                check("物种别名联想返回规范灰喜鹊", species_response.status_code == 200 and len(species_items) == 1 and species_items[0]["species_id"] == str(grey.id))

                patched = client.patch(
                    f"/api/observations/{grey_observation_id}",
                    json={
                        "place": "葛西临海公园",
                        "count": 5,
                        "species_id": species_items[0]["species_id"],
                    },
                )
                patched_detail = patched.json()
                check("PATCH 返回更新后的完整详情", patched.status_code == 200 and patched_detail["place"] == "葛西临海公园" and patched_detail["count"] == 5 and patched_detail["species_label"] == "灰喜鹊")
                check("编辑保持照片和 session 关系", patched_detail["photos"][0]["media_id"] == uploads[0]["media_id"] and patched_detail["session"]["session_id"] == write_result["session_id"])

                deleted = client.delete(
                    f"/api/observations/{grey_observation_id}"
                )
                check("DELETE 返回 204 空响应", deleted.status_code == 204 and deleted.content == b"")
                check("删除后详情与再次删除均为 404", client.get(f"/api/observations/{grey_observation_id}").status_code == 404 and client.delete(f"/api/observations/{grey_observation_id}").status_code == 404)
                remaining = client.get("/api/observations").json()["items"]
                check("删除后仅保留另一条 observation", [item["observation_id"] for item in remaining] == [cormorant_observation_id])

                with session_factory() as session:
                    photos = list(
                        session.scalars(
                            select(PhotoRow).order_by(PhotoRow.content_hash)
                        )
                    )
                    session_row = session.get(
                        SessionRow, UUID(write_result["session_id"])
                    )
                    grey_photo = next(
                        photo
                        for photo in photos
                        if photo.id == UUID(uploads[0]["media_id"])
                    )
                    cormorant_photo = next(
                        photo
                        for photo in photos
                        if photo.id == UUID(uploads[1]["media_id"])
                    )
                    check("删除仅解除目标照片的 observation 关联", grey_photo.observation_id is None and grey_photo.session_id == session_row.id)
                    check("另一照片和 observation 关系保持不变", cormorant_photo.observation_id == UUID(cormorant_observation_id) and cormorant_photo.session_id == session_row.id)
                    check("删除后 session 审计仍为 completed", session_row.status == "completed" and session_row.raw_text == parse_request["text"])
                check("删除 observation 后两个媒体仍可读取", all(client.get(item["url"]).content in {jpeg_grey, jpeg_cormorant} for item in uploads))
                check("完整链路最终业务数量正确", business_counts(session_factory) == (1, 1, 2))
        finally:
            server.should_exit = True
            thread.join(timeout=10)
            listener.close()
            check("Uvicorn 已正常停止", not thread.is_alive())

check("临时 schema 已清理", acceptance_schema_count() == schema_count_before)
check(
    "临时媒体目录已清理",
    temp_media_path is not None and not temp_media_path.exists(),
)


for name, passed, detail in _RESULTS:
    marker = "PASS" if passed else "FAIL"
    suffix = f" — {detail}" if detail and not passed else ""
    print(f"[{marker}] {name}{suffix}")

passed_count = sum(1 for _, passed, _ in _RESULTS if passed)
print(f"\n{passed_count}/{len(_RESULTS)} checks passed")
if passed_count != len(_RESULTS):
    raise SystemExit(1)
