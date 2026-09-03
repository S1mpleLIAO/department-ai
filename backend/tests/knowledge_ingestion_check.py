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

    def fake_send(request, timeout, label):
        captured["body"] = request.data.decode()
        return {"choices": [{"message": {"content": '{"suggestedPurposeId":"generation-template"}'}}]}

    purposes = [
        {"id": "generation-template", "name": "生成模板", "description": "", "canGenerateTemplate": True, "chunkBody": False},
        {"id": "reference-knowledge", "name": "参考知识", "description": "", "canGenerateTemplate": False, "chunkBody": True},
        {"id": "template-reference", "name": "模板＋参考知识", "description": "", "canGenerateTemplate": True, "chunkBody": True},
    ]
    with patch("app.features.documents.service._send", fake_send):
        metadata = analyze_metadata("合同.docx", "甲方：____ 乙方：____", purposes, "https://metadata.example", "key", "model")
    system_prompt = json.loads(captured["body"])["messages"][0]["content"]
    assert metadata["suggestedPurposeId"] == "generation-template"
    assert "空白/去主体化合同必须建议为 generation-template" in system_prompt
    assert "真实主体、金额或签章等已签合同必须建议为 template-reference" in system_prompt
    assert "制度、规范、历史经验必须建议为 reference-knowledge" in system_prompt
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
