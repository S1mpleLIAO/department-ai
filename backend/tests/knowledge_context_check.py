from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

import app.features.documents.router as documents_router
import app.features.search.service as search_service
from app.core.database import NotFoundError
from app.features.documents.schemas import KnowledgeDocumentUpdate, KnowledgeIndexInput
from app.features.documents.store import map_document, save_document, update_document
from app.features.catalog.store import ensure_knowledge_purpose_schema
from app.features.processes.store import validate_process_step
from app.features.search.schemas import TemplateSearchInput
from app.features.search.service import context_match, prioritize_ranked, selection_reason
from app.features.search.store import (
    scoped_chunk_candidates,
    scoped_reference_documents,
    scoped_template_candidates,
)


class FakeResult:
    def __init__(self, row: dict | None) -> None:
        self.row = row

    def fetchone(self) -> dict | None:
        return self.row


class RecordingConnection:
    def __init__(self) -> None:
        self.statements: list[tuple[str, tuple]] = []

    def __enter__(self) -> "RecordingConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: tuple = ()) -> FakeResult:
        self.statements.append((statement, params))
        if "FROM process_steps" in statement:
            return FakeResult(None)
        if "FROM knowledge_documents WHERE id = %s FOR UPDATE" in statement:
            return FakeResult({"id": "doc-1"})
        if "FROM knowledge_documents WHERE id = %s" in statement:
            return FakeResult(None)
        if "FROM knowledge_purposes" in statement:
            return FakeResult({"id": "generation-template"})
        return FakeResult(None)


class FakePool:
    def __init__(self) -> None:
        self.connection_value = RecordingConnection()

    def connection(self) -> RecordingConnection:
        return self.connection_value


class SearchResult:
    def __init__(self, rows: list[dict]) -> None:
        self.rows = rows

    def fetchall(self) -> list[dict]:
        return self.rows


class SearchConnection:
    def __init__(self, rows: list[dict]) -> None:
        self.statements: list[tuple[str, tuple]] = []
        self.rows = rows

    def __enter__(self) -> "SearchConnection":
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, statement: str, params: tuple = ()) -> SearchResult:
        self.statements.append((statement, params))
        rows = self.rows
        if "d.applicable_process_id = ''" in statement:
            rows = [
                row
                for row in rows
                if not row["applicable_process_id"] and not row["applicable_step_id"]
            ]
        elif "d.applicable_process_id = %s" in statement:
            rows = [row for row in rows if row["applicable_process_id"] == params[0]]
            if "d.updated_at DESC" in statement:
                rows = sorted(rows, key=lambda row: row["updated_at"], reverse=True)
            if "CASE WHEN d.applicable_step_id = %s THEN 0 ELSE 1 END" in statement:
                rows = sorted(rows, key=lambda row: row["applicable_step_id"] != params[1])
        if params and isinstance(params[-1], int):
            rows = rows[: params[-1]]
        return SearchResult(rows)


class SearchPool:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.connection_value = SearchConnection(rows or [])
        self.connection_count = 0

    def connection(self) -> SearchConnection:
        self.connection_count += 1
        return self.connection_value


def expect_not_found(action) -> None:
    try:
        action()
        raise AssertionError("无效流程步骤必须被拒绝")
    except NotFoundError:
        pass


def document_payload() -> dict:
    return {
        "id": "doc-1",
        "title": "采购合同模板",
        "categoryId": None,
        "originalName": "采购合同.docx",
        "originalPath": "/tmp/采购合同.docx",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "status": "effective",
        "purposeId": "generation-template",
        "isGenerationTemplate": True,
        "isReferenceKnowledge": False,
        "documentType": "合同",
        "keywords": [],
        "outline": [],
        "templateFamily": "采购合同",
        "templateVariant": "",
        "version": "V1.0",
        "applicableProcessId": "procurement",
        "applicableStepId": "contract",
        "applicableScenario": "设备采购",
        "summary": "",
        "parsedText": "合同正文",
        "chunkSettings": {},
    }


def check_process_validation_and_scope_persistence() -> None:
    pool = FakePool()
    expect_not_found(lambda: validate_process_step(pool, "procurement", "missing"))
    expect_not_found(lambda: validate_process_step(pool, "other", "contract"))
    validation_params = [
        params for statement, params in pool.connection_value.statements
        if "FROM process_steps" in statement
    ]
    assert validation_params == [("procurement", "missing"), ("other", "contract")]

    document = document_payload()
    insert_pool = FakePool()
    save_document(insert_pool, document, [], [0.1], "BAAI/bge-m3")
    insert_params = next(
        params for statement, params in insert_pool.connection_value.statements
        if "INSERT INTO knowledge_documents" in statement
    )
    assert insert_params[16:19] == ("procurement", "contract", "设备采购")

    update_pool = FakePool()
    update_document(update_pool, "doc-1", document, [0.1], "BAAI/bge-m3")
    update_params = next(
        params for statement, params in update_pool.connection_value.statements
        if "UPDATE knowledge_documents SET" in statement
    )
    assert update_params[9:12] == ("procurement", "contract", "设备采购")


def check_catalog_preserves_process_scope() -> None:
    pool = FakePool()
    ensure_knowledge_purpose_schema(pool)
    assert all(
        "SET applicable_process_id" not in statement
        for statement, _ in pool.connection_value.statements
    )


def check_router_scope_validation_precedes_side_effects() -> None:
    update = KnowledgeIndexInput.model_validate({
        "title": "采购合同模板", "purposeId": "generation-template", "scopeType": "process",
        "applicableProcessId": "procurement", "applicableStepId": "contract",
        "templateFamily": "采购合同",
    })
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=FakePool(), settings=SimpleNamespace(data_dir=Path("/tmp/knowledge-context-check")),
    )))
    effects: list[str] = []

    def reject(*_: object) -> None:
        raise NotFoundError("业务流程步骤不存在或不属于所选流程")

    with (
        patch.object(documents_router, "get_document", return_value={"isGenerationTemplate": False}),
        patch.object(documents_router, "validate_process_step", reject),
        patch.object(documents_router, "embed_texts", side_effect=lambda *_: effects.append("embed")),
        patch.object(documents_router, "update_document", side_effect=lambda *_: effects.append("update")),
        patch.object(documents_router, "get_department_settings", return_value={"embeddingModel": "BAAI/bge-m3"}),
    ):
        expect_not_found(lambda: documents_router.document_update("doc-1", request, update))
    assert effects == []

    with TemporaryDirectory() as directory:
        root = Path(directory)
        source = root / "previews" / "preview-1.docx"
        source.parent.mkdir()
        source.write_text("合同正文", encoding="utf-8")
        index_request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
            pool=FakePool(), settings=SimpleNamespace(data_dir=root),
        )))
        index_effects: list[str] = []
        preview = {
            "id": "preview-1", "fileName": "采购合同.docx",
            "mimeType": "application/octet-stream", "parsedText": "合同正文",
        }
        with (
            patch.object(documents_router, "read_preview", return_value=preview),
            patch.object(documents_router, "get_purpose", return_value={"canGenerateTemplate": False, "chunkBody": False, "name": "生成模板"}),
            patch.object(documents_router, "validate_process_step", reject),
            patch.object(documents_router, "embed_texts", side_effect=lambda *_: index_effects.append("embed") or [[0.1]]),
            patch.object(documents_router, "save_document", side_effect=lambda *_: index_effects.append("save")),
            patch.object(documents_router, "get_department_settings", return_value={"embeddingModel": "BAAI/bge-m3", "chunking": {}}),
        ):
            expect_not_found(lambda: documents_router.knowledge_index("preview-1", index_request, update))
        assert index_effects == []
        assert source.exists()


def check_document_update_keeps_purpose_owned_fields() -> None:
    current = {
        **document_payload(),
        "purposeName": "生成模板",
        "chunks": [],
        "scopeType": "global",
    }
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        pool=FakePool(),
        settings=SimpleNamespace(
            siliconflow_base_url="https://embedding.example",
            siliconflow_api_key="key",
        ),
    )))
    stored: list[dict] = []
    validated: list[tuple[str, str]] = []

    def capture_store(_: object, document_id: str, document: dict, *__: object) -> None:
        assert document_id == "doc-1"
        assert document["purposeId"] == "generation-template"
        assert document["purposeName"] == "生成模板"
        assert document["isGenerationTemplate"] is True
        assert document["isReferenceKnowledge"] is False
        stored.append(document)

    def capture_validation(_: object, process_id: str, step_id: str) -> None:
        validated.append((process_id, step_id))

    task_update = KnowledgeDocumentUpdate.model_validate({
        "title": "采购合同模板", "status": "effective", "templateFamily": "采购合同",
        "scopeType": "task", "applicableScenario": "合同审查",
    })
    process_update = KnowledgeDocumentUpdate.model_validate({
        "title": "采购合同模板", "status": "effective", "templateFamily": "采购合同",
        "scopeType": "process", "applicableProcessId": "procurement",
        "applicableStepId": "contract", "applicableScenario": "设备采购",
    })
    with (
        patch.object(documents_router, "get_document", return_value=current),
        patch.object(documents_router, "get_department_settings", return_value={"embeddingModel": "BAAI/bge-m3"}),
        patch.object(documents_router, "embed_texts", return_value=[[0.1]]),
        patch.object(documents_router, "update_document", capture_store),
        patch.object(documents_router, "validate_process_step", capture_validation),
    ):
        task_result = documents_router.document_update("doc-1", request, task_update)
        process_result = documents_router.document_update("doc-1", request, process_update)
    assert task_result["saved"] is True
    assert process_result["saved"] is True
    assert stored[0]["scopeType"] == "task"
    assert stored[0]["applicableScenario"] == "合同审查"
    assert stored[1]["scopeType"] == "process"
    assert stored[1]["applicableProcessId"] == "procurement"
    assert stored[1]["applicableStepId"] == "contract"
    assert validated == [("procurement", "contract")]


def check_scoped_candidate_queries() -> None:
    empty_pool = SearchPool()
    assert scoped_template_candidates(empty_pool, None, None, "", 8) == []
    assert scoped_reference_documents(empty_pool, None, None, "", 8) == []
    assert scoped_chunk_candidates(empty_pool, None, None, "", 8) == []
    assert empty_pool.connection_count == 0

    process_pool = SearchPool()
    assert scoped_template_candidates(
        process_pool, "procurement", "contract", "", 8
    ) == []
    process_sql, process_params = process_pool.connection_value.statements[0]
    assert "d.applicable_process_id = %s" in process_sql
    assert "AND d.applicable_step_id = %s" not in process_sql
    assert "d.is_generation_template = true" in process_sql
    assert "CASE WHEN d.applicable_step_id = %s THEN 0 ELSE 1 END" in process_sql
    assert process_params == ("procurement", "contract", 8)

    task_pool = SearchPool(
        [
            search_document_row("task", scenario="编写设计方案"),
            search_document_row(
                "process",
                process_id="procurement",
                step_id="contract",
                scenario="编写设计方案",
            ),
        ]
    )
    task_candidates = scoped_reference_documents(
        task_pool, None, None, " 编写设计方案 ", 8
    )
    assert [item["id"] for item in task_candidates] == ["task"]
    task_sql, task_params = task_pool.connection_value.statements[0]
    assert "lower(trim(d.applicable_scenario)) = lower(trim(%s))" in task_sql
    assert "d.is_reference_knowledge = true" in task_sql
    assert task_params == ("编写设计方案", 8)

    chunk_pool = SearchPool()
    assert scoped_chunk_candidates(
        chunk_pool, "procurement", "contract", "", 8
    ) == []
    chunk_sql, chunk_params = chunk_pool.connection_value.statements[0]
    assert "d.applicable_process_id" in chunk_sql
    assert "d.applicable_step_id" in chunk_sql
    assert "d.applicable_scenario" in chunk_sql
    assert "d.is_reference_knowledge = true" in chunk_sql
    assert "c.enabled = true" in chunk_sql
    assert "CASE WHEN d.applicable_step_id = %s THEN 0 ELSE 1 END" in chunk_sql
    assert chunk_params == ("procurement", "contract", 8)


def search_document_row(
    document_id: str,
    process_id: str = "",
    step_id: str = "",
    scenario: str = "",
    updated_at: str = "2026-09-03T00:00:00Z",
) -> dict:
    return {
        "id": document_id,
        "title": document_id,
        "category_id": None,
        "original_name": f"{document_id}.txt",
        "original_path": f"/tmp/{document_id}.txt",
        "mime_type": "text/plain",
        "status": "effective",
        "is_generation_template": True,
        "is_reference_knowledge": True,
        "purpose_id": "template-reference",
        "purpose_name": "模板＋参考知识",
        "document_type": "方案",
        "keywords": [],
        "outline": [],
        "template_family": document_id,
        "template_variant": "",
        "version": "V1.0",
        "applicable_process_id": process_id,
        "applicable_step_id": step_id,
        "applicable_scenario": scenario,
        "summary": "",
        "chunk_settings": {},
        "chunk_count": 0,
        "indexed": True,
        "document_embedding": [0.1],
        "created_at": "2026-09-03T00:00:00Z",
        "updated_at": updated_at,
        "parsed_text": "共同检索短语",
        "score": 0.0,
    }


def search_chunk_row(document: dict, chunk_index: int) -> dict:
    return {
        "id": f"chunk-{document['id']}",
        "document_id": document["id"],
        "parent_chunk_id": None,
        "chunk_index": chunk_index,
        "section_path": "正文",
        "content": "共同检索短语",
        "token_count": 10,
        "enabled": True,
        "title": document["title"],
        "original_name": document["original_name"],
        "applicable_process_id": document["applicable_process_id"],
        "applicable_step_id": document["applicable_step_id"],
        "applicable_scenario": document["applicable_scenario"],
        "updated_at": document["updated_at"],
        "score": 0.0,
    }


def check_process_scope_keeps_exact_before_limit() -> None:
    rows = [
        search_document_row(
            "same-new-1", "procurement", "compare", updated_at="2026-09-03T00:00:00Z"
        ),
        search_document_row(
            "same-new-2", "procurement", "approve", updated_at="2026-09-02T00:00:00Z"
        ),
        search_document_row(
            "exact-old", "procurement", "contract", updated_at="2025-01-01T00:00:00Z"
        ),
    ]
    template_ids = [
        item["id"]
        for item in scoped_template_candidates(
            SearchPool(rows), "procurement", "contract", "", 2
        )
    ]
    reference_ids = [
        item["id"]
        for item in scoped_reference_documents(
            SearchPool(rows), "procurement", "contract", "", 2
        )
    ]
    chunk_ids = [
        item["documentId"]
        for item in scoped_chunk_candidates(
            SearchPool(
                [search_chunk_row(document, index) for index, document in enumerate(rows)]
            ),
            "procurement",
            "contract",
            "",
            2,
        )
    ]
    assert template_ids == ["exact-old", "same-new-1"]
    assert reference_ids == ["exact-old", "same-new-1"]
    assert chunk_ids == ["exact-old", "same-new-1"]


def check_search_validates_process_context() -> None:
    options = {
        "query": "采购合同",
        "keywords": [],
        "limit": None,
        "documentId": None,
        "processId": "procurement",
        "stepId": "contract",
        "taskScenario": "",
    }
    effects: list[str] = []

    def reject(*_: object) -> None:
        raise NotFoundError("业务流程步骤不存在或不属于所选流程")

    with (
        patch.object(search_service, "validate_process_step", reject),
        patch.object(
            search_service,
            "get_department_settings",
            side_effect=lambda *_: effects.append("settings"),
        ),
        patch.object(
            search_service,
            "embed_texts",
            side_effect=lambda *_: effects.append("embed"),
        ),
    ):
        expect_not_found(
            lambda: search_service.search_templates(FakePool(), SimpleNamespace(), options)
        )
        expect_not_found(
            lambda: search_service.search_knowledge(FakePool(), SimpleNamespace(), options)
        )
    assert effects == []


def search_document(
    document_id: str,
    process_id: str = "",
    step_id: str = "",
    scenario: str = "",
) -> dict:
    return {
        "id": document_id,
        "title": document_id,
        "purposeName": "生成模板",
        "documentType": "方案",
        "keywords": ["共同检索短语"],
        "outline": [],
        "templateFamily": document_id,
        "templateVariant": "",
        "version": "V1.0",
        "updatedAt": "2026-09-03T00:00:00Z",
        "applicableProcessId": process_id,
        "applicableStepId": step_id,
        "applicableScenario": scenario,
        "summary": document_id,
        "originalName": f"{document_id}.txt",
        "parsedText": "共同检索短语",
    }


def search_chunk(document: dict) -> dict:
    return {
        "id": f"chunk-{document['id']}",
        "documentId": document["id"],
        "parentChunkId": None,
        "sectionPath": "正文",
        "content": "共同检索短语",
        "title": document["title"],
        "source": document["originalName"],
        "applicableProcessId": document["applicableProcessId"],
        "applicableStepId": document["applicableStepId"],
        "applicableScenario": document["applicableScenario"],
    }


def check_contextual_search_results() -> None:
    semantic = search_document("semantic", scenario="其他")
    global_document = search_document("global")
    below_threshold = search_document("below", scenario="编写设计方案")
    exact = search_document("exact", scenario=" 编写设计方案 ")
    settings = {
        "embeddingModel": "embedding",
        "rerankModel": "rerank",
        "retrieval": {
            "vectorRecall": 8,
            "rerankTopN": 8,
            "scoreThreshold": 0.5,
            "recommendCount": 8,
        },
    }
    runtime = SimpleNamespace(
        siliconflow_base_url="https://example.test",
        siliconflow_api_key="key",
    )
    options = {
        "query": "共同检索短语",
        "keywords": [],
        "limit": None,
        "processId": None,
        "stepId": None,
        "taskScenario": "编写设计方案",
    }
    with (
        patch.object(search_service, "get_department_settings", return_value=settings),
        patch.object(search_service, "embed_texts", return_value=[[0.1]]),
        patch.object(
            search_service,
            "vector_template_candidates",
            return_value=[semantic, global_document, below_threshold],
        ),
        patch.object(search_service, "keyword_template_candidates", return_value=[]),
        patch.object(search_service, "scoped_template_candidates", return_value=[exact]),
        patch.object(
            search_service,
            "rerank",
            return_value=[
                {"index": 0, "score": 0.95},
                {"index": 1, "score": 0.90},
                {"index": 2, "score": 0.10},
                {"index": 3, "score": 0.70},
            ],
        ),
    ):
        result = search_service.search_templates(FakePool(), runtime, options)
    assert [item["id"] for item in result["results"]] == ["exact", "global", "semantic"]
    assert [item["score"] for item in result["results"]] == [0.70, 0.90, 0.95]
    assert result["results"][0]["contextMatch"] == "exact"
    assert result["results"][0]["selectionReason"] == "直接关联独立任务场景“编写设计方案”"
    assert result["results"][0]["applicableScenario"].strip() == "编写设计方案"

    chunk_semantic = search_chunk(semantic)
    chunk_global = search_chunk(global_document)
    chunk_exact = search_chunk(exact)
    knowledge_options = {**options, "documentId": None}
    with (
        patch.object(search_service, "get_department_settings", return_value=settings),
        patch.object(search_service, "embed_texts", return_value=[[0.1]]),
        patch.object(
            search_service,
            "vector_chunk_candidates",
            return_value=[chunk_semantic, chunk_global],
        ),
        patch.object(search_service, "keyword_chunk_candidates", return_value=[]),
        patch.object(search_service, "scoped_chunk_candidates", return_value=[chunk_exact]),
        patch.object(
            search_service,
            "vector_reference_documents",
            return_value=[semantic, global_document],
        ),
        patch.object(search_service, "keyword_reference_documents", return_value=[]),
        patch.object(search_service, "scoped_reference_documents", return_value=[exact]),
        patch.object(search_service, "parent_chunk_contents", return_value={}),
        patch.object(
            search_service,
            "rerank",
            side_effect=[
                [
                    {"index": 0, "score": 0.95},
                    {"index": 1, "score": 0.90},
                    {"index": 2, "score": 0.70},
                ],
                [
                    {"index": 0, "score": 0.95},
                    {"index": 1, "score": 0.90},
                    {"index": 2, "score": 0.70},
                ],
            ],
        ),
    ):
        result = search_service.search_knowledge(FakePool(), runtime, knowledge_options)
    assert [item["documentId"] for item in result["results"]] == [
        "exact",
        "global",
        "semantic",
    ]
    assert [item["id"] for item in result["documents"]] == [
        "exact",
        "global",
        "semantic",
    ]
    for item in (result["results"][0], result["documents"][0]):
        assert item["score"] == 0.70
        assert item["contextMatch"] == "exact"
        assert item["selectionReason"] == "直接关联独立任务场景“编写设计方案”"
        assert item["applicableScenario"].strip() == "编写设计方案"


def check_knowledge_limit_applies_after_context_priority() -> None:
    semantic = search_document("semantic", scenario="其他")
    exact = search_document("exact", scenario="编写设计方案")
    settings = {
        "embeddingModel": "embedding",
        "rerankModel": "rerank",
        "retrieval": {
            "vectorRecall": 8,
            "rerankTopN": 8,
            "scoreThreshold": 0.5,
            "recommendCount": 1,
        },
    }
    runtime = SimpleNamespace(
        siliconflow_base_url="https://example.test",
        siliconflow_api_key="key",
    )

    def limited_rerank(
        _query: str,
        _documents: list[str],
        top_n: int,
        *_: object,
    ) -> list[dict[str, float | int]]:
        return [
            {"index": 0, "score": 0.95},
            {"index": 1, "score": 0.70},
        ][:top_n]

    with (
        patch.object(search_service, "get_department_settings", return_value=settings),
        patch.object(search_service, "embed_texts", return_value=[[0.1]]),
        patch.object(
            search_service,
            "vector_chunk_candidates",
            return_value=[search_chunk(semantic)],
        ),
        patch.object(search_service, "keyword_chunk_candidates", return_value=[]),
        patch.object(
            search_service,
            "scoped_chunk_candidates",
            return_value=[search_chunk(exact)],
        ),
        patch.object(
            search_service,
            "vector_reference_documents",
            return_value=[semantic],
        ),
        patch.object(search_service, "keyword_reference_documents", return_value=[]),
        patch.object(search_service, "scoped_reference_documents", return_value=[exact]),
        patch.object(search_service, "parent_chunk_contents", return_value={}),
        patch.object(search_service, "rerank", side_effect=limited_rerank),
    ):
        result = search_service.search_knowledge(
            FakePool(),
            runtime,
            {
                "query": "共同检索短语",
                "keywords": [],
                "documentId": None,
                "limit": 1,
                "processId": None,
                "stepId": None,
                "taskScenario": "编写设计方案",
            },
        )
    assert [(item["documentId"], item["score"]) for item in result["results"]] == [
        ("exact", 0.70)
    ]
    assert [(item["id"], item["score"]) for item in result["documents"]] == [
        ("exact", 0.70)
    ]


def check_knowledge_limit_can_expand_rerank_window() -> None:
    settings = {
        "embeddingModel": "embedding",
        "rerankModel": "rerank",
        "retrieval": {
            "vectorRecall": 12,
            "rerankTopN": 8,
            "scoreThreshold": 0.5,
            "recommendCount": 1,
        },
    }
    runtime = SimpleNamespace(
        siliconflow_base_url="https://example.test",
        siliconflow_api_key="key",
    )
    scores = [0.99, 0.98, 0.97, 0.96, 0.95, 0.94, 0.93, 0.92, 0.91, 0.70]

    def run(task_scenario: str) -> tuple[dict, list[int]]:
        semantic_count = 9 if task_scenario else 10
        semantic = [
            search_document(f"semantic-{index}", scenario="其他")
            for index in range(semantic_count)
        ]
        exact = search_document("exact", scenario=task_scenario)
        rerank_windows: list[int] = []

        def windowed_rerank(
            _query: str,
            documents: list[str],
            top_n: int,
            *_: object,
        ) -> list[dict[str, float | int]]:
            if not documents:
                return []
            rerank_windows.append(top_n)
            return [
                {"index": index, "score": scores[index]}
                for index in range(min(top_n, len(documents)))
            ]

        with (
            patch.object(search_service, "get_department_settings", return_value=settings),
            patch.object(search_service, "embed_texts", return_value=[[0.1]]),
            patch.object(
                search_service,
                "vector_chunk_candidates",
                return_value=[search_chunk(document) for document in semantic],
            ),
            patch.object(search_service, "keyword_chunk_candidates", return_value=[]),
            patch.object(
                search_service,
                "scoped_chunk_candidates",
                return_value=[] if not task_scenario else [search_chunk(exact)],
            ),
            patch.object(search_service, "vector_reference_documents", return_value=[]),
            patch.object(search_service, "keyword_reference_documents", return_value=[]),
            patch.object(search_service, "scoped_reference_documents", return_value=[]),
            patch.object(search_service, "parent_chunk_contents", return_value={}),
            patch.object(search_service, "rerank", side_effect=windowed_rerank),
        ):
            result = search_service.search_knowledge(
                FakePool(),
                runtime,
                {
                    "query": "共同检索短语",
                    "keywords": [],
                    "documentId": None,
                    "limit": 10,
                    "processId": None,
                    "stepId": None,
                    "taskScenario": task_scenario,
                },
            )
        return result, rerank_windows

    no_context, no_context_windows = run("")
    assert no_context_windows == [10]
    assert len(no_context["results"]) == 10
    assert no_context["results"][0]["documentId"] == "semantic-0"

    contextual, contextual_windows = run("编写设计方案")
    assert contextual_windows == [10]
    assert len(contextual["results"]) == 10
    assert contextual["results"][0]["documentId"] == "exact"
    assert contextual["results"][0]["score"] == 0.70


def expect_invalid(payload: dict) -> None:
    try:
        KnowledgeIndexInput.model_validate({
            "title": "测试文档",
            "purposeId": "reference-knowledge",
            **payload,
        })
        raise AssertionError("无效适用范围必须被拒绝")
    except ValidationError:
        pass


def main() -> None:
    expect_search_invalid = [
        {"query": "合同", "processId": "procurement"},
        {"query": "合同", "stepId": "contract"},
        {
            "query": "合同",
            "processId": "procurement",
            "stepId": "contract",
            "taskScenario": "编写合同",
        },
    ]
    for payload in expect_search_invalid:
        try:
            TemplateSearchInput.model_validate(payload)
            raise AssertionError("冲突或不完整检索上下文必须被拒绝")
        except ValidationError:
            pass

    process_options = {
        "processId": "procurement",
        "stepId": "contract",
        "taskScenario": "",
    }
    candidates = [
        {
            "id": "semantic",
            "applicableProcessId": "",
            "applicableStepId": "",
            "applicableScenario": "其他",
        },
        {
            "id": "global",
            "applicableProcessId": "",
            "applicableStepId": "",
            "applicableScenario": "",
        },
        {
            "id": "same",
            "applicableProcessId": "procurement",
            "applicableStepId": "compare",
            "applicableScenario": "",
        },
        {
            "id": "exact",
            "applicableProcessId": "procurement",
            "applicableStepId": "contract",
            "applicableScenario": "",
        },
    ]
    ranked = [
        {"index": 0, "score": 0.95},
        {"index": 1, "score": 0.90},
        {"index": 2, "score": 0.80},
        {"index": 3, "score": 0.70},
    ]
    ordered = prioritize_ranked(candidates, ranked, process_options)
    assert [item["document"]["id"] for item in ordered] == [
        "exact",
        "same",
        "global",
        "semantic",
    ]
    assert [item["score"] for item in ordered] == [0.70, 0.80, 0.90, 0.95]
    assert [item["contextMatch"] for item in ordered] == [
        "exact",
        "same-process",
        "global",
        "semantic",
    ]

    task_options = {
        "processId": None,
        "stepId": None,
        "taskScenario": " 编写设计方案 ",
    }
    assert context_match(
        {
            "applicableProcessId": "",
            "applicableStepId": "",
            "applicableScenario": "编写设计方案",
        },
        task_options,
    ) == "exact"
    assert context_match(
        {
            "applicableProcessId": "",
            "applicableStepId": "",
            "applicableScenario": "",
        },
        task_options,
    ) == "global"
    assert selection_reason("exact", process_options) == "直接关联当前流程步骤"
    assert selection_reason("exact", task_options) == "直接关联独立任务场景“编写设计方案”"
    assert selection_reason("same-process", process_options) == "关联当前业务流程"
    assert selection_reason("global", process_options) == "全局通用知识"
    assert selection_reason("semantic", process_options) == "与当前需求语义相关"
    no_context = {"processId": None, "stepId": None, "taskScenario": ""}
    no_context_order = prioritize_ranked(
        [candidates[0], candidates[1]],
        [{"index": 0, "score": 0.20}, {"index": 1, "score": 0.90}],
        no_context,
    )
    assert [item["document"]["id"] for item in no_context_order] == [
        "semantic",
        "global",
    ]

    expect_invalid({"scopeType": "task", "applicableScenario": ""})
    expect_invalid({"scopeType": "process", "applicableProcessId": "procurement"})
    expect_invalid({"scopeType": "process", "applicableStepId": "contract"})
    global_scope = KnowledgeIndexInput.model_validate({
        "title": "公司介绍", "purposeId": "reference-knowledge", "scopeType": "global",
        "applicableProcessId": "procurement", "applicableStepId": "contract",
        "applicableScenario": "旧客户端遗留值",
    })
    assert global_scope.scopeType == "global"
    assert global_scope.applicableProcessId == ""
    assert global_scope.applicableStepId == ""
    assert global_scope.applicableScenario == ""

    task_scope = KnowledgeIndexInput.model_validate({
        "title": "设计方案模板", "purposeId": "generation-template",
        "scopeType": "task", "applicableScenario": " 编写设计方案 ",
        "applicableProcessId": "procurement", "applicableStepId": "contract",
    })
    assert task_scope.applicableScenario == "编写设计方案"
    assert task_scope.applicableProcessId == ""
    assert task_scope.applicableStepId == ""

    process_scope = KnowledgeIndexInput.model_validate({
        "title": "采购合同模板", "purposeId": "generation-template",
        "scopeType": "process", "applicableProcessId": "procurement",
        "applicableStepId": "contract", "applicableScenario": "设备采购",
    })
    assert process_scope.applicableProcessId == "procurement"
    assert process_scope.applicableStepId == "contract"

    row = {
        "id": "doc-1", "title": "采购合同模板", "category_id": None,
        "original_name": "采购合同.docx", "original_path": "/tmp/采购合同.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "status": "effective", "is_generation_template": True,
        "is_reference_knowledge": False, "purpose_id": "generation-template",
        "purpose_name": "生成模板", "document_type": "合同", "keywords": [], "outline": [],
        "template_family": "采购合同", "template_variant": "", "version": "V1.0",
        "applicable_process_id": "procurement", "applicable_step_id": "contract",
        "applicable_scenario": "设备采购", "summary": "", "chunk_settings": {},
        "chunk_count": 0, "indexed": True, "document_embedding": [0.1],
        "created_at": "2026-09-03T00:00:00Z", "updated_at": "2026-09-03T00:00:00Z",
    }
    mapped = map_document(row)
    assert mapped["scopeType"] == "process"
    assert mapped["applicableProcessId"] == "procurement"
    assert mapped["applicableStepId"] == "contract"
    check_process_validation_and_scope_persistence()
    check_catalog_preserves_process_scope()
    check_router_scope_validation_precedes_side_effects()
    check_document_update_keeps_purpose_owned_fields()
    check_scoped_candidate_queries()
    check_process_scope_keeps_exact_before_limit()
    check_search_validates_process_context()
    check_contextual_search_results()
    check_knowledge_limit_applies_after_context_priority()
    check_knowledge_limit_can_expand_rerank_window()
    print("knowledge-context-check: ok")


if __name__ == "__main__":
    main()
