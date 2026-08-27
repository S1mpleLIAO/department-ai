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
    assert metadata["suggestedPurposeId"] == "generation-template"
    assert "空白范本" in captured["body"]
    assert "真实甲乙方" in captured["body"]
    assert "签章" in captured["body"]
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
