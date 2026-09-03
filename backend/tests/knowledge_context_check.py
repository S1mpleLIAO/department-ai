from pydantic import ValidationError

from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.store import map_document


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
    print("knowledge-context-check: ok")


if __name__ == "__main__":
    main()
