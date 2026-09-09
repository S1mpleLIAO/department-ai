from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, Query, Request
from fastapi.responses import FileResponse
from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.core.database import ConflictError, NotFoundError, StoreError
from app.core.schemas import ChunkingSettings
from app.features.catalog.store import get_purpose, list_categories, list_purposes
from app.features.documents.schemas import (
    KnowledgeDocumentUpdate,
    KnowledgeIndexInput,
    KnowledgePreviewInput,
)
from app.features.documents.service import (
    analyze_metadata,
    chunk_document,
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
from app.features.documents.store import (
    delete_document,
    get_document,
    list_documents,
    replace_document_embeddings,
    save_document,
    update_document,
)
from app.features.settings.store import get_department_settings


router = APIRouter()


def _pool(request: Request) -> ConnectionPool:
    return request.app.state.pool


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@router.get("/api/documents")
def documents(request: Request) -> list[dict[str, Any]]:
    return list_documents(_pool(request))


@router.get("/api/documents/{document_id}")
def document_get(document_id: str, request: Request) -> dict[str, Any]:
    return get_document(_pool(request), document_id)


def _managed_source(request: Request, document: dict[str, Any]) -> Path:
    source = Path(document["originalPath"]).resolve()
    if not source.is_relative_to(_settings(request).data_dir.parent):
        raise ConflictError("文档文件不在受管理的数据目录中，已拒绝访问")
    return source


@router.get("/api/documents/{document_id}/source")
def document_source(document_id: str, request: Request) -> FileResponse:
    document = get_document(_pool(request), document_id)
    source = _managed_source(request, document)
    if not source.exists():
        raise NotFoundError("原始文件不存在")
    return FileResponse(source, media_type=document["mimeType"], filename=document["originalName"])


@router.put("/api/documents/{document_id}")
def document_update(
    document_id: str, request: Request, update: KnowledgeDocumentUpdate
) -> dict[str, Any]:
    current = get_document(_pool(request), document_id)
    data = update.model_dump()
    if current["isGenerationTemplate"] and not data["templateFamily"]:
        raise StoreError("生成模板必须填写模板家族")
    document = {**current, **data}
    embedding = None
    embedding_model = None
    if document_profile(current) != document_profile(document):
        runtime = _settings(request)
        settings = get_department_settings(_pool(request))
        embedding_model = settings["embeddingModel"]
        embedding = embed_texts(
            [document_profile(document)],
            runtime.siliconflow_base_url,
            runtime.siliconflow_api_key,
            embedding_model,
        )[0]
    update_document(_pool(request), document_id, data, embedding, embedding_model)
    return {"saved": True, "document": get_document(_pool(request), document_id)}


@router.post("/api/documents/{document_id}/reindex")
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


@router.delete("/api/documents/{document_id}")
def document_delete(document_id: str, request: Request) -> dict[str, bool]:
    document = get_document(_pool(request), document_id)
    source = _managed_source(request, document)
    delete_document(_pool(request), document_id)
    source.unlink(missing_ok=True)
    return {"deleted": True}


@router.post("/api/knowledge/preview")
def knowledge_preview(request: Request, upload: KnowledgePreviewInput) -> dict[str, Any]:
    settings = _settings(request)
    content, file_name = decode_upload(upload.fileBase64, upload.fileName, settings.max_source_bytes)
    parsed_text = parse_document(content, file_name, upload.mimeType, settings.docling_base_url)
    preview_id = str(uuid4())
    preview = {
        "id": preview_id,
        "fileName": file_name,
        "mimeType": upload.mimeType,
        "parsedText": parsed_text,
        "settings": None,
        "chunks": [],
        "createdAt": datetime.now(timezone.utc).isoformat(),
    }
    save_preview(settings.data_dir, preview, content)
    return {
        "id": preview_id,
        "fileName": file_name,
        "characters": len(parsed_text),
    }


@router.post("/api/knowledge/previews/{preview_id}/analyze")
def knowledge_analyze(
    preview_id: str,
    request: Request,
    suggest_category: Annotated[bool, Query(alias="suggestCategory")] = False,
) -> dict[str, Any]:
    runtime = _settings(request)
    preview = read_preview(runtime.data_dir, preview_id)
    metadata = analyze_metadata(
        preview["fileName"],
        preview["parsedText"],
        list_purposes(_pool(request)),
        runtime.metadata_base_url,
        runtime.metadata_api_key,
        runtime.metadata_model,
        categories=list_categories(_pool(request)) if suggest_category else None,
    )
    return {"id": preview_id, "metadata": metadata}


@router.post("/api/knowledge/previews/{preview_id}/rechunk")
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
    }


@router.delete("/api/knowledge/previews/{preview_id}")
def knowledge_preview_delete(preview_id: str, request: Request) -> dict[str, bool]:
    delete_preview(_settings(request).data_dir, preview_id)
    return {"deleted": True}


@router.post("/api/knowledge/previews/{preview_id}/index", status_code=201)
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
    raw_chunks = preview.get("chunks", []) if data["chunks"] is None else data["chunks"]
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

    department_settings = get_department_settings(_pool(request))
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
        "chunkSettings": preview.get("settings") or department_settings["chunking"],
    }
    document.pop("chunks")
    enabled_chunks = [chunk for chunk in chunks if chunk["enabled"]]
    vectors = embed_texts(
        [document_profile(document), *(chunk["content"] for chunk in enabled_chunks)],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        department_settings["embeddingModel"],
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
            _pool(request), document, stored_chunks, vectors[0], department_settings["embeddingModel"]
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
