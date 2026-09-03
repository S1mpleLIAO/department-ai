import json
from unittest.mock import patch

from app.features.documents.schemas import KnowledgePreviewInput
from app.features.documents.service import analyze_metadata


def main() -> None:
    upload = KnowledgePreviewInput.model_validate({
        "fileName": "合同.docx",
        "fileBase64": "UEsDBA==",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })
    assert not hasattr(upload, "chunkSettings")

    captured = {}
    responses = [
        '{"suggestedPurposeId":"generation-template","suggestedScopeType":"process","applicableProcessId":"procurement","applicableStepId":"contract","applicableScenario":"设备采购"}',
        '{"suggestedPurposeId":"generation-template","suggestedScopeType":"process","applicableProcessId":"other","applicableStepId":"missing","applicableScenario":""}',
        '{"suggestedPurposeId":"generation-template","suggestedScopeType":"task","applicableProcessId":"invented-process","applicableStepId":"invented-step","applicableScenario":"合同审查"}',
        '{"suggestedPurposeId":"generation-template","suggestedScopeType":"other","applicableProcessId":"invented-process","applicableStepId":"invented-step","applicableScenario":"残留场景"}',
    ]

    def fake_send(request, timeout, label):
        captured["body"] = request.data.decode()
        return {"choices": [{"message": {"content": responses.pop(0)}}]}

    purposes = [
        {"id": "generation-template", "name": "生成模板", "description": "", "canGenerateTemplate": True, "chunkBody": False},
        {"id": "reference-knowledge", "name": "参考知识", "description": "", "canGenerateTemplate": False, "chunkBody": True},
        {"id": "template-reference", "name": "模板＋参考知识", "description": "", "canGenerateTemplate": True, "chunkBody": True},
    ]
    processes = [
        {
            "id": "procurement",
            "name": "采购流程",
            "description": "完成采购合同签订。",
            "steps": [
                {
                    "id": "contract",
                    "name": "合同签订",
                    "objective": "完成采购合同签订。",
                    "requiredInputs": ["采购申请"],
                    "requiredOutputs": ["已签合同"],
                    "completionCriteria": ["合同已归档"],
                    "instructions": "确认合同条款。",
                }
            ],
        }
    ]
    with patch("app.features.documents.service._send", fake_send):
        metadata = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes, processes,
            "https://metadata.example", "key", "model",
        )
        invalid_metadata = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes, processes,
            "https://metadata.example", "key", "model",
        )
        task_metadata = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes, processes,
            "https://metadata.example", "key", "model",
        )
        unknown_metadata = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes, processes,
            "https://metadata.example", "key", "model",
        )
    system_prompt = json.loads(captured["body"])["messages"][0]["content"]
    assert metadata["suggestedPurposeId"] == "generation-template"
    assert metadata["suggestedScopeType"] == "process"
    assert metadata["applicableProcessId"] == "procurement"
    assert metadata["applicableStepId"] == "contract"
    assert invalid_metadata["suggestedScopeType"] == ""
    assert invalid_metadata["applicableProcessId"] == ""
    assert invalid_metadata["applicableStepId"] == ""
    assert task_metadata["suggestedScopeType"] == "task"
    assert task_metadata["applicableProcessId"] == ""
    assert task_metadata["applicableStepId"] == ""
    assert task_metadata["applicableScenario"] == "合同审查"
    assert unknown_metadata["suggestedScopeType"] == ""
    assert unknown_metadata["applicableProcessId"] == ""
    assert unknown_metadata["applicableStepId"] == ""
    assert unknown_metadata["applicableScenario"] == ""
    assert "空白/去主体化合同必须建议为 generation-template" in system_prompt
    assert "真实主体、金额或签章等已签合同必须建议为 template-reference" in system_prompt
    assert "制度、规范、历史经验必须建议为 reference-knowledge" in system_prompt
    assert "suggestedScopeType" in system_prompt
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
