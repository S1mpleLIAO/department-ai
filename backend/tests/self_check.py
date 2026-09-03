from datetime import datetime, timezone
import os
from pathlib import Path
from tempfile import TemporaryDirectory

from app.core.config import PROJECT_DIR, Settings, get_settings
from app.core.database import ConflictError, NotFoundError, StoreError, vector_literal
from app.core.schemas import ChunkingSettings, Identifier, NonEmpty, ShortText, StrictModel
from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.service import (
    cleanup_previews,
    chunk_document,
    decode_upload,
    document_profile,
    uploaded_document_path,
)
from app.features.documents.store import map_document
from app.features.catalog.schemas import CategoryInput, CategoryOrderInput, KnowledgePurposeInput
from app.features.processes.schemas import ProcessInput
from app.features.search.service import search_keywords
from app.features.settings.schemas import DepartmentSettingsInput
from app.features.skills.schemas import SkillInput, SkillResourceInput
from app.features.skills.service import (
    delete_skill,
    delete_skill_resource,
    list_skills,
    read_skill_resource,
    save_skill,
    save_skill_resource,
)
from app.main import web_dir


def main() -> None:
    assert vector_literal([0.1, 0.25]) == "[0.1,0.25]"
    assert PROJECT_DIR.name == "backend"
    assert web_dir == PROJECT_DIR.parent / "frontend"

    harness_environment = {
        "DEPARTMENT_DATABASE_URL": "postgresql://test:test@127.0.0.1/test",
        "DEPARTMENT_HARNESS_URL": "https://example.test/department-deepseekharness",
        "DEPARTMENT_HARNESS_HEALTH_URL": "http://127.0.0.1:3080/",
    }
    previous_environment = {key: os.environ.get(key) for key in harness_environment}
    try:
        os.environ.update(harness_environment)
        harness_settings = get_settings()
        assert harness_settings.harness_url == harness_environment["DEPARTMENT_HARNESS_URL"]
        assert harness_settings.harness_health_url == harness_environment["DEPARTMENT_HARNESS_HEALTH_URL"]
    finally:
        for key, value in previous_environment.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    row = {
        "id": "doc-1",
        "title": "销售合同补充协议",
        "category_id": "it",
        "original_name": "补充协议.docx",
        "original_path": "/tmp/补充协议.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "status": "effective",
        "is_generation_template": True,
        "is_reference_knowledge": True,
        "purpose_id": "template-reference",
        "purpose_name": "模板＋参考知识",
        "document_type": "合同补充协议",
        "keywords": ["销售", "补充协议"],
        "outline": ["合同主体", "变更内容"],
        "template_family": "合同补充协议",
        "template_variant": "销售合同补充协议",
        "version": "V1.0",
        "applicable_process_id": "procurement",
        "applicable_step_id": "contract",
        "applicable_scenario": "销售合同变更",
        "summary": "用于销售合同变更。",
        "chunk_settings": {"mode": "structure"},
        "chunk_count": 6,
        "indexed": True,
        "document_embedding": [0.1],
        "created_at": datetime(2026, 8, 23, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 23, tzinfo=timezone.utc),
    }
    document = map_document(row)
    assert document["documentPurpose"] == "both"
    assert document["purposeId"] == "template-reference"
    assert document["keywords"] == ["销售", "补充协议"]
    assert document["chunkCount"] == 6
    assert document["indexed"] is True
    assert document["documentIndexed"] is True
    assert document["updatedAt"].endswith("Z")

    process = ProcessInput.model_validate(
        {
            "name": "测试流程",
            "steps": [
                {
                    "name": "第一步",
                    "objective": "完成测试",
                    "requiredInputs": [" 输入文件 "],
                }
            ],
        }
    )
    assert process.id
    assert process.steps[0].id
    assert process.description == ""
    assert process.steps[0].requiredInputs == ["输入文件"]

    category = CategoryInput.model_validate({"name": "测试目录"})
    category_order = CategoryOrderInput.model_validate({"ids": ["category-1"]})
    purpose = KnowledgePurposeInput.model_validate(
        {
            "name": "测试用途",
            "chunkSettings": {
                "mode": "structure",
                "delimiter": "\n\n",
                "maxTokens": 800,
                "overlapTokens": 80,
                "parentMaxTokens": 1500,
                "childMaxTokens": 300,
                "childOverlapTokens": 30,
            },
        }
    )
    assert category.parentId is None
    assert category_order.parentId is None
    assert purpose.chunkBody is True

    settings = DepartmentSettingsInput.model_validate(
        {
            "assistant": {
                "role": "测试助手",
                "principles": ["先查询真实数据，再给出结论。"],
                "defaultLanguage": "zh-CN",
                "draftByDefault": True,
                "askWhenMissing": True,
            },
            "chunking": {
                "mode": "structure",
                "delimiter": "\n\n",
                "maxTokens": 800,
                "overlapTokens": 80,
                "parentMaxTokens": 1500,
                "childMaxTokens": 300,
                "childOverlapTokens": 30,
            },
            "retrieval": {
                "vectorRecall": 20,
                "rerankTopN": 8,
                "recommendCount": 3,
                "scoreThreshold": None,
            },
            "embeddingModel": "BAAI/bge-m3",
            "rerankModel": "BAAI/bge-reranker-v2-m3",
        }
    )
    assert settings.retrieval.recommendCount == 3
    try:
        DepartmentSettingsInput.model_validate(
            {
                **settings.model_dump(),
                "chunking": {**settings.chunking.model_dump(), "overlapTokens": 800},
            }
        )
        raise AssertionError("无效的重叠 Token 应被拒绝")
    except ValueError:
        pass

    decoded, name = decode_upload("5Lit5paH", "../测试.txt", 100)
    assert decoded.decode() == "中文"
    assert name == "测试.txt"
    chunks = chunk_document(
        "# 第一章\n\n这是第一段。\n\n这是第二段。",
        settings.chunking.model_dump(),
    )
    assert chunks[0]["sectionPath"] == "第一章"
    assert chunks[0]["enabled"] is True

    confirmed = KnowledgeIndexInput.model_validate(
        {
            "title": "销售合同补充协议",
            "purposeId": "template-reference",
            "templateFamily": "合同补充协议",
            "keywords": ["销售合同", "补充协议"],
        }
    )
    profile = document_profile(
        {
            **confirmed.model_dump(exclude={"chunks", "id"}),
            "purposeName": "模板＋参考知识",
            "parsedText": "合同正文",
        }
    )
    assert "关键词：销售合同、补充协议" in profile
    assert search_keywords("RoCE 组网方案", ["GPU"]) == ["GPU", "RoCE", "组网方案"]

    with TemporaryDirectory() as directory:
        root = Path(directory)
        skill_input = SkillInput.model_validate(
            {
                "name": "contract-review",
                "description": "按部门规则审查合同。用户要求识别合同风险时使用。",
                "instructions": "## 操作步骤\n1. 先识别合同主体，再逐条检查风险。",
                "enabled": True,
            }
        )
        resource_input = SkillResourceInput.model_validate({"contentBase64": "YQ=="})
        assert resource_input.contentBase64 == "YQ=="
        skill = save_skill(
            root / "skills",
            skill_input.model_dump(),
        )
        assert skill["id"] == "contract-review"
        assert len(list_skills(root / "skills")) == 1
        skill_file = root / "skills" / skill["id"] / "SKILL.md"
        assert sorted(path.name for path in skill_file.parent.iterdir()) == ["SKILL.md"]
        assert "name: contract-review" in skill_file.read_text(encoding="utf-8")
        assert "whenToUse" not in skill_file.read_text(encoding="utf-8")
        assert "# 合同审查" not in skill_file.read_text(encoding="utf-8")
        assert "disable-model-invocation" not in skill_file.read_text(encoding="utf-8")
        disabled = save_skill(
            root / "skills",
            {**skill, "enabled": False},
            skill["id"],
        )
        assert disabled["enabled"] is False
        assert "disable-model-invocation: true" in skill_file.read_text(encoding="utf-8")
        assert "user-invocable: false" in skill_file.read_text(encoding="utf-8")

        skill_file.write_text(
            skill_file.read_text(encoding="utf-8").replace(
                "---\n\n## 操作步骤",
                "metadata:\n  owner: department-ai\n---\n\n## 操作步骤",
            ),
            encoding="utf-8",
        )
        preserved = save_skill(
            root / "skills",
            {**disabled, "description": "更新后的技能说明"},
            skill["id"],
        )
        assert preserved["description"] == "更新后的技能说明"
        assert "metadata:" in skill_file.read_text(encoding="utf-8")
        assert "  owner: department-ai" in skill_file.read_text(encoding="utf-8")

        saved_script = save_skill_resource(
            root / "skills",
            skill["id"],
            "scripts/review.py",
            b"print('ok')\n",
        )
        assert saved_script["path"] == "scripts/review.py"
        assert saved_script["kind"] == "scripts"
        saved_asset = save_skill_resource(
            root / "skills",
            skill["id"],
            "assets/template.docx",
            b"PK\x03\x04binary",
        )
        assert read_skill_resource(root / "skills", skill["id"], saved_asset["path"]).read_bytes() == b"PK\x03\x04binary"
        resources = list_skills(root / "skills")[0]["resources"]
        assert [item["path"] for item in resources] == ["assets/template.docx", "scripts/review.py"]
        assert list_skills(root / "skills")[0]["resourceCounts"] == {
            "scripts": 1,
            "references": 0,
            "assets": 1,
        }
        try:
            save_skill_resource(root / "skills", skill["id"], "scripts/../SKILL.md", b"bad")
            raise AssertionError("技能资源路径穿越应被拒绝")
        except StoreError:
            pass
        delete_skill_resource(root / "skills", skill["id"], "scripts/review.py")
        assert not (skill_file.parent / "scripts" / "review.py").exists()

        outside_skill = root / "outside-skill"
        outside_skill.mkdir()
        (outside_skill / "SKILL.md").write_text(
            "---\nname: linked-skill\ndescription: outside\n---\n\noutside\n",
            encoding="utf-8",
        )
        (root / "skills" / "linked-skill").symlink_to(outside_skill, target_is_directory=True)
        assert all(item["id"] != "linked-skill" for item in list_skills(root / "skills"))

        delete_skill(root / "skills", skill["id"])
        assert list_skills(root / "skills") == []

        preview = root / "previews" / "expired.json"
        preview.parent.mkdir()
        preview.write_text("{}", encoding="utf-8")
        os.utime(preview, (0, 0))
        assert cleanup_previews(root, 1) == 1
        assert not preview.exists()

        upload = root / "uploads" / "合同.txt"
        upload.parent.mkdir()
        upload.write_text("合同正文", encoding="utf-8")
        assert uploaded_document_path(str(upload), 100) == upload.resolve()
        outside = root / "outside.txt"
        outside.write_text("不应读取", encoding="utf-8")
        try:
            uploaded_document_path(str(outside), 100)
            raise AssertionError("uploads 目录外的文件应被拒绝")
        except StoreError:
            pass
    print("self-check: ok")


if __name__ == "__main__":
    main()
