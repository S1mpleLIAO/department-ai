import json
from unittest.mock import patch

from pydantic import ValidationError

from app.features.documents.schemas import KnowledgeIndexInput, KnowledgePreviewInput
from app.features.documents.service import analyze_metadata


def main() -> None:
    # Real request validation: unclassified uploads use JSON null, never a blank Identifier.
    index_body = {"title": "未分类文档", "purposeId": "reference", "categoryId": None, "chunks": []}
    assert KnowledgeIndexInput.model_validate(index_body).categoryId is None
    try:
        KnowledgeIndexInput.model_validate({**index_body, "categoryId": ""})
    except ValidationError as error:
        assert error.errors()[0]["loc"] == ("categoryId",)
    else:
        raise AssertionError("Blank native-select values must be normalized before request validation")
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
    assert "template-reference" not in system_prompt

    # A configurable purpose list must never be overridden by a stale hard-coded purpose id.
    def fake_signed_contract_send(request, timeout, label):
        body = json.loads(request.data.decode())
        prompt = body["messages"][0]["content"]
        suggested_purpose = "template-reference" if "template-reference" in prompt else "reference-knowledge"
        return {"choices": [{"message": {"content": json.dumps({"suggestedPurposeId": suggested_purpose})}}]}

    with patch("app.features.documents.service._send", fake_signed_contract_send):
        signed_contract = analyze_metadata(
            "已签销售合同.docx",
            "甲方：中科算力有限公司；合同金额：72万元；双方已盖章。",
            purposes[:2],
            "https://metadata.example",
            "key",
            "model",
        )
    assert signed_contract["suggestedPurposeId"] == "reference-knowledge"
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
