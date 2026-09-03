from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from pydantic import ValidationError

import app.features.documents.router as documents_router
from app.core.database import NotFoundError
from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.store import map_document, save_document, update_document
from app.features.catalog.store import ensure_knowledge_purpose_schema
from app.features.processes.store import validate_process_step


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
    print("knowledge-context-check: ok")


if __name__ == "__main__":
    main()
