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

    captured_bodies = []

    def fake_send(request, timeout, label):
        captured_bodies.append(request.data.decode())
        suggested_category = ',"suggestedCategoryId":"crm"' if len(captured_bodies) == 2 else ""
        return {"choices": [{"message": {"content": '{"suggestedPurposeId":"generation-template"' + suggested_category + '}'}}]}

    purposes = [
        {"id": "generation-template", "name": "生成模板", "description": "", "canGenerateTemplate": True, "chunkBody": False},
        {"id": "reference-knowledge", "name": "参考知识", "description": "", "canGenerateTemplate": False, "chunkBody": True},
        {"id": "template-reference", "name": "模板＋参考知识", "description": "", "canGenerateTemplate": True, "chunkBody": True},
    ]
    categories = [
        {"id": "product", "parentId": None, "name": "产品知识"},
        {"id": "crm", "parentId": "product", "name": "CRM"},
    ]
    with patch("app.features.documents.service._send", fake_send):
        without_category = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes,
            "https://metadata.example", "key", "model",
        )
        with_category = analyze_metadata(
            "合同.docx", "甲方：____ 乙方：____", purposes,
            "https://metadata.example", "key", "model", categories=categories,
        )
    system_prompt = json.loads(captured_bodies[0])["messages"][0]["content"]
    assert without_category["suggestedPurposeId"] == "generation-template"
    assert without_category["suggestedCategoryId"] == ""
    assert "可选知识目录" not in captured_bodies[0]
    assert with_category["suggestedCategoryId"] == "crm"
    assert "产品知识 / CRM" in captured_bodies[1]
    assert "空白/去主体化合同必须建议为 generation-template" in system_prompt
    assert "真实主体、金额或签章等已签合同必须建议为 template-reference" in system_prompt
    assert "制度、规范、历史经验必须建议为 reference-knowledge" in system_prompt
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
