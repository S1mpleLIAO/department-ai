from __future__ import annotations

import base64
import binascii
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from app.core.config import Settings, get_settings
from app.core.database import ConflictError, NotFoundError, StoreError, create_pool
from app.core.health import docling_health, url_health
from app.core.schemas import ChunkingSettings
from app.db import (
    create_purpose,
    create_category,
    delete_category,
    delete_document,
    delete_purpose,
    delete_process,
    get_document,
    get_department_settings,
    list_categories,
    list_documents,
    list_purposes,
    list_processes,
    get_purpose,
    ensure_knowledge_purpose_schema,
    reorder_categories,
    replace_document_embeddings,
    save_department_settings,
    save_document,
    save_process,
    update_category,
    update_document,
    update_purpose,
)
from app.knowledge import (
    analyze_metadata,
    chunk_document,
    cleanup_previews,
    decode_upload,
    delete_preview,
    document_profile,
    embed_texts,
    estimate_tokens,
    parse_document,
    preview_source_path,
    read_preview,
    save_preview,
    update_preview,
)
from app.mcp_server import clear_runtime, mcp, mcp_app, set_runtime
from app.schemas import (
    CategoryInput,
    CategoryOrderInput,
    DepartmentSettingsInput,
    KnowledgePreviewInput,
    KnowledgeIndexInput,
    KnowledgePurposeInput,
    KnowledgeDocumentUpdate,
    KnowledgeSearchInput,
    ProcessInput,
    TemplateSearchInput,
    SkillInput,
    SkillResourceInput,
)
from app.search import search_knowledge, search_templates
from app.skills import (
    delete_skill,
    delete_skill_resource,
    list_skills,
    read_skill_resource,
    save_skill,
    save_skill_resource,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    (settings.data_dir / "previews").mkdir(parents=True, exist_ok=True)
    settings.skill_dir.mkdir(parents=True, exist_ok=True)
    cleanup_previews(settings.data_dir)
    pool = create_pool(settings.database_url)
    pool.open(wait=True)
    ensure_knowledge_purpose_schema(pool)
    app.state.settings = settings
    app.state.pool = pool
    set_runtime(pool, settings)
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        clear_runtime()
        pool.close()


app = FastAPI(title="部门 AI Python API", version="0.1.0", lifespan=lifespan)
web_dir = Path(__file__).resolve().parents[2] / "frontend"


@app.exception_handler(StoreError)
def store_error_handler(_request: Request, error: StoreError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


def _pool(request: Request) -> ConnectionPool:
    return request.app.state.pool


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    pool = _pool(request)
    with pool.connection() as connection:
        connection.execute("SELECT 1").fetchone()
    settings = _settings(request)
    return {
        "status": "ok",
        "database": "ok",
        "docling": "ok" if docling_health(settings.docling_base_url) else "unavailable",
        "siliconflowConfigured": settings.siliconflow_configured,
        "metadataConfigured": bool(settings.metadata_api_key and settings.metadata_model),
        "harness": "ok" if url_health(settings.harness_url) else "unavailable",
    }


@app.get("/", include_in_schema=False)
def portal_redirect() -> RedirectResponse:
    return RedirectResponse("/department")


@app.get("/department", include_in_schema=False)
def portal() -> FileResponse:
    return FileResponse(web_dir / "index.html")


@app.get("/api/processes")
def processes(request: Request) -> list[dict[str, Any]]:
    return list_processes(_pool(request))


@app.post("/api/processes", status_code=201)
def process_create(request: Request, process: ProcessInput) -> dict[str, Any]:
    data = process.model_dump()
    save_process(_pool(request), data, creating=True)
    return {"saved": True, "process": data}


@app.put("/api/processes/{process_id}")
def process_update(process_id: str, request: Request, process: ProcessInput) -> dict[str, Any]:
    data = process.model_dump()
    data["id"] = process_id
    save_process(_pool(request), data, creating=False)
    return {"saved": True, "process": data}


@app.delete("/api/processes/{process_id}")
def process_delete(process_id: str, request: Request) -> dict[str, bool]:
    delete_process(_pool(request), process_id)
    return {"deleted": True}


@app.get("/api/categories")
def categories(request: Request) -> list[dict[str, Any]]:
    return list_categories(_pool(request))


@app.get("/api/purposes")
def purposes(request: Request) -> list[dict[str, Any]]:
    return list_purposes(_pool(request))


@app.post("/api/purposes", status_code=201)
def purpose_create(request: Request, purpose: KnowledgePurposeInput) -> dict[str, Any]:
    saved = create_purpose(_pool(request), purpose.model_dump())
    return {"saved": True, "purpose": saved}


@app.put("/api/purposes/{purpose_id}")
def purpose_update(
    purpose_id: str, request: Request, purpose: KnowledgePurposeInput
) -> dict[str, Any]:
    saved = update_purpose(_pool(request), purpose_id, purpose.model_dump())
    return {"saved": True, "purpose": saved}


@app.delete("/api/purposes/{purpose_id}")
def purpose_delete(purpose_id: str, request: Request) -> dict[str, bool]:
    delete_purpose(_pool(request), purpose_id)
    return {"deleted": True}


@app.post("/api/categories", status_code=201)
def category_create(request: Request, category: CategoryInput) -> dict[str, Any]:
    saved = create_category(_pool(request), category.model_dump())
    return {"saved": True, "category": saved}


@app.put("/api/categories/order")
def category_reorder(request: Request, order: CategoryOrderInput) -> dict[str, bool]:
    reorder_categories(_pool(request), order.parentId, order.ids)
    return {"saved": True}


@app.put("/api/categories/{category_id}")
def category_update(category_id: str, request: Request, category: CategoryInput) -> dict[str, Any]:
    saved = update_category(_pool(request), category_id, category.model_dump())
    return {"saved": True, "category": saved}


@app.delete("/api/categories/{category_id}")
def category_delete(category_id: str, request: Request) -> dict[str, bool]:
    delete_category(_pool(request), category_id)
    return {"deleted": True}


@app.get("/api/documents")
def documents(request: Request) -> list[dict[str, Any]]:
    return list_documents(_pool(request))


@app.get("/api/documents/{document_id}")
def document_get(document_id: str, request: Request) -> dict[str, Any]:
    return get_document(_pool(request), document_id)


def _managed_source(request: Request, document: dict[str, Any]) -> Path:
    source = Path(document["originalPath"]).resolve()
    if not source.is_relative_to(_settings(request).data_dir.parent):
        raise ConflictError("文档文件不在受管理的数据目录中，已拒绝访问")
    return source


@app.get("/api/documents/{document_id}/source")
def document_source(document_id: str, request: Request) -> FileResponse:
    document = get_document(_pool(request), document_id)
    source = _managed_source(request, document)
    if not source.exists():
        raise NotFoundError("原始文件不存在")
    return FileResponse(source, media_type=document["mimeType"], filename=document["originalName"])


@app.put("/api/documents/{document_id}")
def document_update(
    document_id: str, request: Request, update: KnowledgeDocumentUpdate
) -> dict[str, Any]:
    runtime = _settings(request)
    current = get_document(_pool(request), document_id)
    data = update.model_dump()
    if current["isGenerationTemplate"] and not data["templateFamily"]:
        raise StoreError("生成模板必须填写模板家族")
    document = {**current, **data}
    settings = get_department_settings(_pool(request))
    embedding = embed_texts(
        [document_profile(document)],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["embeddingModel"],
    )[0]
    update_document(_pool(request), document_id, data, embedding, settings["embeddingModel"])
    return {"saved": True, "document": get_document(_pool(request), document_id)}


@app.post("/api/documents/{document_id}/reindex")
def document_reindex(document_id: str, request: Request) -> dict[str, Any]:
    runtime = _settings(request)
    document = get_document(_pool(request), document_id)
    enabled_chunks = [chunk for chunk in document["chunks"] if chunk["enabled"]]
    settings = get_department_settings(_pool(request))
    vectors = embed_texts(
        [document_profile(document), *(chunk["content"] for chunk in enabled_chunks)],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["embeddingModel"],
    )
    replace_document_embeddings(
        _pool(request),
        document_id,
        vectors[0],
        {chunk["id"]: vectors[index + 1] for index, chunk in enumerate(enabled_chunks)},
        settings["embeddingModel"],
    )
    return {"saved": True, "document": get_document(_pool(request), document_id)}


@app.delete("/api/documents/{document_id}")
def document_delete(document_id: str, request: Request) -> dict[str, bool]:
    document = get_document(_pool(request), document_id)
    source = _managed_source(request, document)
    delete_document(_pool(request), document_id)
    source.unlink(missing_ok=True)
    return {"deleted": True}


@app.get("/api/settings")
def settings(request: Request) -> dict[str, Any]:
    return get_department_settings(_pool(request))


@app.put("/api/settings")
def settings_update(request: Request, settings: DepartmentSettingsInput) -> dict[str, Any]:
    data = settings.model_dump()
    save_department_settings(_pool(request), data)
    return {"saved": True, "settings": data}


@app.get("/api/skills")
def skills(request: Request) -> list[dict[str, Any]]:
    return list_skills(_settings(request).skill_dir)


@app.post("/api/skills", status_code=201)
def skill_create(request: Request, skill: SkillInput) -> dict[str, Any]:
    saved = save_skill(_settings(request).skill_dir, skill.model_dump())
    return {"saved": True, "skill": saved}


@app.put("/api/skills/{skill_id}")
def skill_update(skill_id: str, request: Request, skill: SkillInput) -> dict[str, Any]:
    saved = save_skill(_settings(request).skill_dir, skill.model_dump(), skill_id)
    return {"saved": True, "skill": saved}


@app.delete("/api/skills/{skill_id}")
def skill_delete(skill_id: str, request: Request) -> dict[str, bool]:
    delete_skill(_settings(request).skill_dir, skill_id)
    return {"deleted": True}


@app.put("/api/skills/{skill_id}/resources/{resource_path:path}")
def skill_resource_save(
    skill_id: str,
    resource_path: str,
    request: Request,
    upload: SkillResourceInput,
) -> dict[str, Any]:
    try:
        content = base64.b64decode(upload.contentBase64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise StoreError("技能资源内容不是有效的 Base64") from error
    settings = _settings(request)
    resource = save_skill_resource(
        settings.skill_dir,
        skill_id,
        resource_path,
        content,
        settings.max_source_bytes,
    )
    return {"saved": True, "resource": resource}


@app.get("/api/skills/{skill_id}/resources/{resource_path:path}")
def skill_resource_download(skill_id: str, resource_path: str, request: Request) -> FileResponse:
    resource = read_skill_resource(_settings(request).skill_dir, skill_id, resource_path)
    return FileResponse(resource, filename=resource.name)


@app.delete("/api/skills/{skill_id}/resources/{resource_path:path}")
def skill_resource_delete(skill_id: str, resource_path: str, request: Request) -> dict[str, bool]:
    delete_skill_resource(_settings(request).skill_dir, skill_id, resource_path)
    return {"deleted": True}


@app.post("/api/knowledge/preview")
def knowledge_preview(request: Request, upload: KnowledgePreviewInput) -> dict[str, Any]:
    settings = _settings(request)
    content, file_name = decode_upload(upload.fileBase64, upload.fileName, settings.max_source_bytes)
    parsed_text = parse_document(content, file_name, upload.mimeType, settings.docling_base_url)
    chunk_settings = upload.chunkSettings.model_dump()
    chunks = chunk_document(parsed_text, chunk_settings)
    purposes = list_purposes(_pool(request))
    metadata = None
    metadata_error = ""
    try:
        metadata = analyze_metadata(
            file_name,
            parsed_text,
            purposes,
            settings.metadata_base_url,
            settings.metadata_api_key,
            settings.metadata_model,
        )
    except StoreError as error:
        metadata_error = str(error)

    preview_id = str(uuid4())
    preview = {
        "id": preview_id,
        "fileName": file_name,
        "mimeType": upload.mimeType,
        "parsedText": parsed_text,
        "settings": chunk_settings,
        "chunks": chunks,
        "metadata": metadata,
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    save_preview(settings.data_dir, preview, content)
    return {
        "id": preview_id,
        "fileName": file_name,
        "characters": len(parsed_text),
        "chunks": chunks,
        "metadata": metadata,
        "metadataError": metadata_error,
    }


@app.post("/api/knowledge/previews/{preview_id}/rechunk")
def knowledge_rechunk(
    preview_id: str, request: Request, chunk_settings: ChunkingSettings
) -> dict[str, Any]:
    settings = _settings(request)
    preview = read_preview(settings.data_dir, preview_id)
    preview["settings"] = chunk_settings.model_dump()
    preview["chunks"] = chunk_document(preview["parsedText"], preview["settings"])
    update_preview(settings.data_dir, preview)
    return {
        "id": preview_id,
        "characters": len(preview["parsedText"]),
        "chunks": preview["chunks"],
        "metadata": preview["metadata"],
    }


@app.delete("/api/knowledge/previews/{preview_id}")
def knowledge_preview_delete(preview_id: str, request: Request) -> dict[str, bool]:
    delete_preview(_settings(request).data_dir, preview_id)
    return {"deleted": True}


@app.post("/api/knowledge/previews/{preview_id}/index", status_code=201)
def knowledge_index(
    preview_id: str, request: Request, confirmed: KnowledgeIndexInput
) -> dict[str, Any]:
    runtime = _settings(request)
    preview = read_preview(runtime.data_dir, preview_id)
    data = confirmed.model_dump()
    document_id = data["id"] or f"knowledge-{uuid4()}"
    purpose = get_purpose(_pool(request), data["purposeId"])
    is_template = purpose["canGenerateTemplate"]
    is_reference = purpose["chunkBody"]
    if is_template and not data["templateFamily"]:
        raise StoreError("该文档用途允许生成模板，必须填写模板家族")
    raw_chunks = preview["chunks"] if data["chunks"] is None else data["chunks"]
    chunks: list[dict[str, Any]] = []
    if is_reference:
        for index, raw in enumerate(raw_chunks):
            parent_index = raw.get("parentIndex")
            if parent_index is not None and (not isinstance(parent_index, int) or parent_index >= index):
                raise StoreError(f"第 {index + 1} 个分块的父块必须位于它之前")
            content = str(raw.get("content", "")).strip()
            if not content:
                raise StoreError(f"第 {index + 1} 个分块内容为空")
            chunks.append(
                {
                    "parentIndex": parent_index,
                    "sectionPath": str(raw.get("sectionPath", "")),
                    "content": content,
                    "tokenCount": estimate_tokens(content),
                    "enabled": raw.get("enabled") is not False,
                }
            )
        if not any(chunk["enabled"] for chunk in chunks):
            raise StoreError("参考知识至少需要一个启用的分块")

    final_directory = runtime.data_dir / "documents"
    final_directory.mkdir(parents=True, exist_ok=True)
    source_path = preview_source_path(runtime.data_dir, preview)
    if not source_path.exists():
        raise NotFoundError("预览原文件已经不存在，请重新上传")
    final_path = final_directory / f"{document_id}{Path(preview['fileName']).suffix.lower()}"
    if final_path.exists():
        raise ConflictError("文档 ID 对应的文件已经存在")

    document = {
        **data,
        "id": document_id,
        "originalName": preview["fileName"],
        "originalPath": str(final_path),
        "mimeType": preview["mimeType"],
        "isGenerationTemplate": is_template,
        "isReferenceKnowledge": is_reference,
        "purposeName": purpose["name"],
        "applicableProcessId": "",
        "applicableStepId": "",
        "parsedText": preview["parsedText"],
        "chunkSettings": preview["settings"],
    }
    document.pop("chunks")
    settings = get_department_settings(_pool(request))
    enabled_chunks = [chunk for chunk in chunks if chunk["enabled"]]
    vectors = embed_texts(
        [document_profile(document), *(chunk["content"] for chunk in enabled_chunks)],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["embeddingModel"],
    )
    chunk_ids = [str(uuid4()) for _ in chunks]
    embedding_index = 1
    stored_chunks: list[dict[str, Any]] = []
    for index, chunk in enumerate(chunks):
        embedding = vectors[embedding_index] if chunk["enabled"] else None
        if chunk["enabled"]:
            embedding_index += 1
        stored_chunks.append(
            {
                **chunk,
                "id": chunk_ids[index],
                "parentChunkId": (
                    None if chunk["parentIndex"] is None else chunk_ids[chunk["parentIndex"]]
                ),
                "chunkIndex": index,
                "embedding": embedding,
            }
        )

    source_path.replace(final_path)
    try:
        save_document(
            _pool(request), document, stored_chunks, vectors[0], settings["embeddingModel"]
        )
    except Exception:
        final_path.replace(source_path)
        raise
    delete_preview(runtime.data_dir, preview_id)
    return {
        "saved": True,
        "id": document_id,
        "purposeId": data["purposeId"],
        "chunks": len(stored_chunks),
    }


@app.post("/api/search/templates")
def template_search(request: Request, search: TemplateSearchInput) -> dict[str, Any]:
    return search_templates(_pool(request), _settings(request), search.model_dump())


@app.post("/api/search/knowledge")
def knowledge_search(request: Request, search: KnowledgeSearchInput) -> dict[str, Any]:
    return search_knowledge(_pool(request), _settings(request), search.model_dump())


@app.get("/api/state")
def state(request: Request) -> dict[str, Any]:
    pool = _pool(request)
    settings = _settings(request)
    return {
        "processes": list_processes(pool),
        "categories": list_categories(pool),
        "purposes": list_purposes(pool),
        "documents": list_documents(pool),
        "skills": list_skills(settings.skill_dir),
        "settings": get_department_settings(pool),
        "services": {
            "database": True,
            "docling": docling_health(settings.docling_base_url),
            "siliconflow": settings.siliconflow_configured,
            "metadata": bool(settings.metadata_api_key and settings.metadata_model),
            "harness": url_health(settings.harness_url),
            "harnessUrl": settings.harness_url,
        },
    }


app.mount("/department", StaticFiles(directory=web_dir), name="department-web")

# 放在普通 API 路由之后；MCP 子应用的默认端点因此正好是 /mcp。
app.mount("/", mcp_app)
