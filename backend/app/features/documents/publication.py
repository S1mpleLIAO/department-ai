"""Prepare reviewed uploads without extracting text or chunking a second time."""
from uuid import uuid4
from app.core.database import StoreError
from app.features.catalog.store import get_purpose
from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.service import document_profile, embed_texts, estimate_tokens
from app.features.documents.store import save_document, update_document, _validate_document_links
from app.core.database import vector_literal
from app.features.settings.store import get_department_settings


def validate_metadata(pool, raw):
    data = KnowledgeIndexInput.model_validate(raw).model_dump()
    purpose = get_purpose(pool, data["purposeId"])
    if purpose["canGenerateTemplate"] and not data["templateFamily"]:
        raise StoreError("生成模板必须填写模板家族")
    chunks = data.get("chunks") or []
    if purpose["chunkBody"]:
        if not any(c["enabled"] for c in chunks):
            raise StoreError("参考知识至少需要一个启用的分块")
        for index, chunk in enumerate(chunks):
            if chunk["parentIndex"] is not None and chunk["parentIndex"] >= index:
                raise StoreError("父分块必须位于子分块之前")
    with pool.connection() as conn:
        _validate_document_links(conn, data)
    return data


def publish_reviewed_document(pool, runtime, payload, path):
    data = validate_metadata(pool, payload["metadata"])
    purpose = get_purpose(pool, data["purposeId"])
    config = get_department_settings(pool)
    # Purpose semantics are frozen in the reviewed snapshot.
    if payload["purposeFlags"] != [purpose["canGenerateTemplate"], purpose["chunkBody"]]:
        raise StoreError("文档用途配置已变化，请驳回后重新确认用途再审核")
    raw_chunks = data.pop("chunks") or []
    chunks = raw_chunks if purpose["chunkBody"] else []
    document = {**data, "id": payload["resourceId"], "status": "effective",
                "originalName": payload["fileName"], "originalPath": str(path),
                "mimeType": payload["mimeType"], "isGenerationTemplate": purpose["canGenerateTemplate"],
                "isReferenceKnowledge": purpose["chunkBody"], "purposeName": purpose["name"],
                "applicableProcessId": "", "applicableStepId": "",
                "parsedText": payload["parsedText"], "chunkSettings": payload["chunkSettings"]}
    vectors = embed_texts([document_profile(document), *(c["content"] for c in chunks if c["enabled"])],
                         runtime.siliconflow_base_url, runtime.siliconflow_api_key, config["embeddingModel"])
    ids = [str(uuid4()) for _ in chunks]
    stored, offset = [], 1
    for index, chunk in enumerate(chunks):
        vector = vectors[offset] if chunk["enabled"] else None
        offset += int(chunk["enabled"])
        stored.append({**chunk, "id": ids[index], "parentChunkId": None if chunk["parentIndex"] is None else ids[chunk["parentIndex"]],
                       "chunkIndex": index, "tokenCount": estimate_tokens(chunk["content"]), "embedding": vector})
    save_document(pool, document, stored, vectors[0], config["embeddingModel"])


def publish_document_edit(pool, runtime, payload, base):
    """Keep existing chunk IDs/vectors for directory and metadata-only changes."""
    data = validate_metadata(pool,payload["metadata"])
    purpose = get_purpose(pool,data["purposeId"])
    if payload["purposeFlags"] != [purpose["canGenerateTemplate"],purpose["chunkBody"]]:
        raise StoreError("文档用途配置已变化，请驳回后重新确认用途再审核")
    document = {**data,"status":"effective","purposeName":purpose["name"],"parsedText":payload["parsedText"]}
    old = {**base["metadata"],"purposeName":get_purpose(pool,base["metadata"]["purposeId"])["name"],
           "parsedText":base["parsedText"]}
    def chunks_of(value):
        return [{k:c[k] for k in ("content","enabled","parentIndex","sectionPath")} for c in value or []]
    chunks = chunks_of(data["chunks"]) if purpose["chunkBody"] else []
    previous = chunks_of(base["metadata"]["chunks"]) if base["purposeFlags"][1] else []
    changed_chunks = chunks != previous or payload["purposeFlags"] != base["purposeFlags"]
    config = get_department_settings(pool)
    profile_changed = document_profile(document) != document_profile(old)
    inputs = ([document_profile(document)] if profile_changed else []) + (
        [c["content"] for c in chunks if c["enabled"]] if changed_chunks else [])
    vectors = embed_texts(inputs,runtime.siliconflow_base_url,runtime.siliconflow_api_key,config["embeddingModel"]) if inputs else []
    update_document(pool,payload["resourceId"],document,vectors[0] if profile_changed else None,
                    config["embeddingModel"] if profile_changed else None)
    with pool.connection() as conn:
        conn.execute("""UPDATE knowledge_documents SET purpose_id=%s,is_generation_template=%s,
                        is_reference_knowledge=%s WHERE id=%s""",
                     (data["purposeId"],*payload["purposeFlags"],payload["resourceId"]))
        if not changed_chunks:
            return
        conn.execute("DELETE FROM knowledge_chunks WHERE document_id=%s",(payload["resourceId"],))
        ids = [str(uuid4()) for _ in chunks]
        offset = int(profile_changed)
        for index,chunk in enumerate(chunks):
            vector = vectors[offset] if chunk["enabled"] else None
            offset += int(chunk["enabled"])
            conn.execute("""INSERT INTO knowledge_chunks(id,document_id,parent_chunk_id,chunk_index,section_path,
                            content,token_count,enabled,embedding,embedding_model)
                            VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)""",
                         (ids[index],payload["resourceId"],None if chunk["parentIndex"] is None else ids[chunk["parentIndex"]],
                          index,chunk["sectionPath"],chunk["content"],estimate_tokens(chunk["content"]),chunk["enabled"],
                          vector_literal(vector) if vector is not None else None,config["embeddingModel"]))
