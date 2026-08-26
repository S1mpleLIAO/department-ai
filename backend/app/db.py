from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core.database import ConflictError, NotFoundError, StoreError, vector_literal

DEFAULT_SETTINGS: dict[str, Any] = {
    "assistant": {
        "role": "你是部门内部 AI 助手，不是办公审批系统。你帮助团队按照真实业务流程完成任务、检索内部知识并形成可追溯的标准交付物。",
        "principles": [
            "用户上传当前任务文件时，先读取文件内容，再查询真实业务流程；结合内容判断最可能的流程和步骤，并说明置信度、已完成内容和缺项。",
            "用户要生成合同、方案或报告时，先提取关键词、已知流程和步骤，再检索知识库中真实存在的模板，不得虚构模板或模板选项。",
            "检索结果存在不同模板变体时，说明差异并让用户选择；同一变体默认推荐最新有效版本，用户确认后才能读取完整模板。",
            "对照流程步骤的输入、交付物和完成标准检查资料；关键事实缺失时先询问，不得猜测。",
            "需要制度、条款或历史经验时检索参考知识；用户指定文档时只在该文档内检索，并引用真实来源和章节上下文。",
            "生成结果应说明依据和仍待确认的事项。",
        ],
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
        "cleanWhitespace": True,
        "removeUrlsEmails": False,
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

DEFAULT_PURPOSES: tuple[dict[str, Any], ...] = (
    {
        "id": "generation-template",
        "name": "生成模板",
        "description": "作为整份模板推荐，用户确认后由 AI 读取完整正文。",
        "canGenerateTemplate": True,
        "chunkBody": False,
        "inheritChunking": True,
        "chunkSettings": DEFAULT_SETTINGS["chunking"],
    },
    {
        "id": "reference-knowledge",
        "name": "参考知识",
        "description": "建立正文分块索引，用于检索真实章节、条款和上下文。",
        "canGenerateTemplate": False,
        "chunkBody": True,
        "inheritChunking": True,
        "chunkSettings": DEFAULT_SETTINGS["chunking"],
    },
    {
        "id": "template-reference",
        "name": "模板＋参考知识",
        "description": "既可推荐整份模板，也可检索正文中的具体章节。",
        "canGenerateTemplate": True,
        "chunkBody": True,
        "inheritChunking": True,
        "chunkSettings": DEFAULT_SETTINGS["chunking"],
    },
)


def ensure_knowledge_purpose_schema(pool: ConnectionPool) -> None:
    """Add purpose presets without rewriting the existing knowledge schema."""
    with pool.connection() as connection:
        connection.execute(
            """CREATE TABLE IF NOT EXISTS knowledge_purposes (
                   id text PRIMARY KEY,
                   name text NOT NULL UNIQUE,
                   description text NOT NULL DEFAULT '',
                   can_generate_template boolean NOT NULL,
                   chunk_body boolean NOT NULL,
                   inherit_chunking boolean NOT NULL DEFAULT true,
                   chunk_settings jsonb NOT NULL,
                   sort_order integer NOT NULL DEFAULT 0,
                   created_at timestamptz NOT NULL DEFAULT now(),
                   updated_at timestamptz NOT NULL DEFAULT now(),
                   CHECK (can_generate_template OR chunk_body)
               )"""
        )
        for index, purpose in enumerate(DEFAULT_PURPOSES):
            connection.execute(
                """INSERT INTO knowledge_purposes
                   (id, name, description, can_generate_template, chunk_body,
                    inherit_chunking, chunk_settings, sort_order)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                   ON CONFLICT (id) DO NOTHING""",
                (
                    purpose["id"],
                    purpose["name"],
                    purpose["description"],
                    purpose["canGenerateTemplate"],
                    purpose["chunkBody"],
                    purpose["inheritChunking"],
                    Jsonb(purpose["chunkSettings"]),
                    index * 10,
                ),
            )
        connection.execute("ALTER TABLE knowledge_documents ADD COLUMN IF NOT EXISTS purpose_id text")
        connection.execute(
            """UPDATE knowledge_documents SET purpose_id = CASE
                   WHEN is_generation_template AND is_reference_knowledge THEN 'template-reference'
                   WHEN is_generation_template THEN 'generation-template'
                   ELSE 'reference-knowledge'
               END WHERE purpose_id IS NULL"""
        )
        connection.execute(
            """UPDATE knowledge_documents
               SET applicable_process_id = '', applicable_step_id = ''
               WHERE applicable_process_id <> '' OR applicable_step_id <> ''"""
        )
        connection.execute(
            """DO $$ BEGIN
                   IF NOT EXISTS (
                       SELECT 1 FROM pg_constraint WHERE conname = 'knowledge_documents_purpose_id_fkey'
                   ) THEN
                       ALTER TABLE knowledge_documents
                       ADD CONSTRAINT knowledge_documents_purpose_id_fkey
                       FOREIGN KEY (purpose_id) REFERENCES knowledge_purposes(id) ON DELETE RESTRICT;
                   END IF;
               END $$"""
        )
        connection.execute("ALTER TABLE knowledge_documents ALTER COLUMN purpose_id SET NOT NULL")


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def map_document(row: dict[str, Any]) -> dict[str, Any]:
    is_template = bool(row["is_generation_template"])
    is_reference = bool(row["is_reference_knowledge"])
    purpose = "both" if is_template and is_reference else "template" if is_template else "reference"
    return {
        "id": str(row["id"]),
        "title": str(row["title"]),
        "categoryId": None if row["category_id"] is None else str(row["category_id"]),
        "originalName": str(row["original_name"]),
        "originalPath": str(row["original_path"]),
        "mimeType": str(row["mime_type"]),
        "status": str(row["status"]),
        "isGenerationTemplate": is_template,
        "isReferenceKnowledge": is_reference,
        "documentPurpose": purpose,
        "purposeId": str(row.get("purpose_id") or purpose),
        "purposeName": str(row.get("purpose_name") or {
            "template": "生成模板",
            "reference": "参考知识",
            "both": "模板＋参考知识",
        }[purpose]),
        "documentType": str(row["document_type"]),
        "keywords": _string_list(row["keywords"]),
        "outline": _string_list(row["outline"]),
        "templateFamily": str(row["template_family"]),
        "templateVariant": str(row["template_variant"]),
        "version": str(row["version"]),
        "applicableProcessId": str(row["applicable_process_id"]),
        "applicableStepId": str(row["applicable_step_id"]),
        "applicableScenario": str(row["applicable_scenario"]),
        "summary": str(row["summary"]),
        "chunkSettings": row["chunk_settings"],
        "chunkCount": int(row["chunk_count"]),
        "indexed": bool(row["indexed"]),
        "documentIndexed": bool(
            row.get("document_indexed", row.get("document_embedding") is not None)
        ),
        "chunkIndexed": bool(row.get("chunk_indexed", False)),
        "createdAt": _iso(row["created_at"]),
        "updatedAt": _iso(row["updated_at"]),
    }


def _purpose(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "name": str(row["name"]),
        "description": str(row["description"]),
        "canGenerateTemplate": bool(row["can_generate_template"]),
        "chunkBody": bool(row["chunk_body"]),
        "inheritChunking": bool(row["inherit_chunking"]),
        "chunkSettings": row["chunk_settings"],
        "sortOrder": int(row["sort_order"]),
        "documentCount": int(row.get("document_count", 0)),
        "updatedAt": _iso(row["updated_at"]),
    }


def list_purposes(pool: ConnectionPool) -> list[dict[str, Any]]:
    with pool.connection() as connection:
        rows = connection.execute(
            """SELECT p.*, count(d.id)::integer AS document_count
               FROM knowledge_purposes p
               LEFT JOIN knowledge_documents d ON d.purpose_id = p.id
               GROUP BY p.id ORDER BY p.sort_order, p.name"""
        ).fetchall()
    return [_purpose(row) for row in rows]


def get_purpose(pool: ConnectionPool, purpose_id: str) -> dict[str, Any]:
    with pool.connection() as connection:
        row = connection.execute(
            """SELECT p.*, count(d.id)::integer AS document_count
               FROM knowledge_purposes p
               LEFT JOIN knowledge_documents d ON d.purpose_id = p.id
               WHERE p.id = %s GROUP BY p.id""",
            (purpose_id,),
        ).fetchone()
    if not row:
        raise NotFoundError("文档用途不存在")
    return _purpose(row)


def create_purpose(pool: ConnectionPool, data: dict[str, Any]) -> dict[str, Any]:
    purpose_id = f"purpose-{uuid4()}"
    try:
        with pool.connection() as connection:
            connection.execute(
                """INSERT INTO knowledge_purposes
                   (id, name, description, can_generate_template, chunk_body,
                    inherit_chunking, chunk_settings, sort_order, updated_at)
                   SELECT %s,%s,%s,%s,%s,%s,%s,COALESCE(MAX(sort_order), -10) + 10,now()
                   FROM knowledge_purposes""",
                (
                    purpose_id,
                    data["name"],
                    data["description"],
                    data["canGenerateTemplate"],
                    data["chunkBody"],
                    data["inheritChunking"],
                    Jsonb(data["chunkSettings"]),
                ),
            )
    except UniqueViolation as error:
        raise ConflictError("已经存在同名文档用途") from error
    return get_purpose(pool, purpose_id)


def update_purpose(
    pool: ConnectionPool, purpose_id: str, data: dict[str, Any]
) -> dict[str, Any]:
    try:
        with pool.connection() as connection:
            updated = connection.execute(
                """UPDATE knowledge_purposes SET
                       name = %s, description = %s, can_generate_template = %s,
                       chunk_body = %s, inherit_chunking = %s, chunk_settings = %s,
                       updated_at = now() WHERE id = %s""",
                (
                    data["name"],
                    data["description"],
                    data["canGenerateTemplate"],
                    data["chunkBody"],
                    data["inheritChunking"],
                    Jsonb(data["chunkSettings"]),
                    purpose_id,
                ),
            ).rowcount
            if updated == 0:
                raise NotFoundError("文档用途不存在")
    except UniqueViolation as error:
        raise ConflictError("已经存在同名文档用途") from error
    return get_purpose(pool, purpose_id)


def delete_purpose(pool: ConnectionPool, purpose_id: str) -> None:
    with pool.connection() as connection:
        if connection.execute(
            "SELECT 1 FROM knowledge_documents WHERE purpose_id = %s LIMIT 1", (purpose_id,)
        ).fetchone():
            raise ConflictError("该用途仍有文档使用，不能删除")
        deleted = connection.execute(
            "DELETE FROM knowledge_purposes WHERE id = %s", (purpose_id,)
        ).rowcount
        if deleted == 0:
            raise NotFoundError("文档用途不存在")


def list_categories(pool: ConnectionPool) -> list[dict[str, Any]]:
    with pool.connection() as connection:
        rows = connection.execute(
            "SELECT id, parent_id, name, sort_order FROM knowledge_categories ORDER BY sort_order, name"
        ).fetchall()
    return [
        {
            "id": str(row["id"]),
            "parentId": None if row["parent_id"] is None else str(row["parent_id"]),
            "name": str(row["name"]),
            "sortOrder": int(row["sort_order"]),
        }
        for row in rows
    ]


def list_documents(pool: ConnectionPool) -> list[dict[str, Any]]:
    with pool.connection() as connection:
        rows = connection.execute(
            """SELECT d.*, p.name AS purpose_name,
                      count(c.id)::integer AS chunk_count,
                      d.document_embedding IS NOT NULL AS document_indexed,
                      COALESCE(bool_or(c.embedding IS NOT NULL), false) AS chunk_indexed,
                      (d.document_embedding IS NOT NULL OR
                       COALESCE(bool_or(c.embedding IS NOT NULL), false)) AS indexed
               FROM knowledge_documents d
               JOIN knowledge_purposes p ON p.id = d.purpose_id
               LEFT JOIN knowledge_chunks c ON c.document_id = d.id
               GROUP BY d.id, p.name ORDER BY d.updated_at DESC"""
        ).fetchall()
    return [map_document(row) for row in rows]


def get_document(pool: ConnectionPool, document_id: str) -> dict[str, Any]:
    with pool.connection() as connection:
        row = connection.execute(
            """SELECT d.*, p.name AS purpose_name,
                      (SELECT count(*)::integer FROM knowledge_chunks c WHERE c.document_id = d.id) AS chunk_count,
                      d.document_embedding IS NOT NULL AS document_indexed,
                      EXISTS (SELECT 1 FROM knowledge_chunks c
                              WHERE c.document_id = d.id AND c.embedding IS NOT NULL) AS chunk_indexed,
                      (d.document_embedding IS NOT NULL OR EXISTS (
                          SELECT 1 FROM knowledge_chunks c
                          WHERE c.document_id = d.id AND c.embedding IS NOT NULL
                      )) AS indexed
               FROM knowledge_documents d
               JOIN knowledge_purposes p ON p.id = d.purpose_id
               WHERE d.id = %s""",
            (document_id,),
        ).fetchone()
        if not row:
            raise NotFoundError("知识文档不存在")
        chunks = connection.execute(
            """SELECT id, document_id, parent_chunk_id, chunk_index, section_path,
                      content, token_count, enabled
               FROM knowledge_chunks WHERE document_id = %s ORDER BY chunk_index""",
            (document_id,),
        ).fetchall()
    return {
        **map_document(row),
        "parsedText": str(row["parsed_text"]),
        "chunks": [
            {
                "id": str(chunk["id"]),
                "documentId": str(chunk["document_id"]),
                "parentChunkId": (
                    None if chunk["parent_chunk_id"] is None else str(chunk["parent_chunk_id"])
                ),
                "chunkIndex": int(chunk["chunk_index"]),
                "sectionPath": str(chunk["section_path"]),
                "content": str(chunk["content"]),
                "tokenCount": int(chunk["token_count"]),
                "enabled": bool(chunk["enabled"]),
            }
            for chunk in chunks
        ],
    }


def _validate_document_links(connection: Any, document: dict[str, Any]) -> None:
    if document["categoryId"] and not connection.execute(
        "SELECT 1 FROM knowledge_categories WHERE id = %s", (document["categoryId"],)
    ).fetchone():
        raise NotFoundError("知识目录不存在")
    if not connection.execute(
        "SELECT 1 FROM knowledge_purposes WHERE id = %s",
        (document["purposeId"],),
    ).fetchone():
        raise NotFoundError("文档用途不存在")


def save_document(
    pool: ConnectionPool,
    document: dict[str, Any],
    chunks: list[dict[str, Any]],
    document_embedding: list[float],
    embedding_model: str,
) -> None:
    with pool.connection() as connection:
        if connection.execute(
            "SELECT 1 FROM knowledge_documents WHERE id = %s", (document["id"],)
        ).fetchone():
            raise ConflictError("文档 ID 已存在")
        _validate_document_links(connection, document)

        connection.execute(
            """INSERT INTO knowledge_documents
               (id, title, category_id, original_name, original_path, mime_type, status,
                purpose_id, is_generation_template, is_reference_knowledge, document_type, keywords, outline,
                template_family, template_variant, version, applicable_process_id,
                applicable_step_id, applicable_scenario, summary, parsed_text, chunk_settings,
                document_embedding, embedding_model, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s,now())""",
            (
                document["id"],
                document["title"],
                document["categoryId"],
                document["originalName"],
                document["originalPath"],
                document["mimeType"],
                document["status"],
                document["purposeId"],
                document["isGenerationTemplate"],
                document["isReferenceKnowledge"],
                document["documentType"],
                Jsonb(document["keywords"]),
                Jsonb(document["outline"]),
                document["templateFamily"],
                document["templateVariant"],
                document["version"],
                document["applicableProcessId"],
                document["applicableStepId"],
                document["applicableScenario"],
                document["summary"],
                document["parsedText"],
                Jsonb(document["chunkSettings"]),
                vector_literal(document_embedding),
                embedding_model,
            ),
        )
        for chunk in chunks:
            connection.execute(
                """INSERT INTO knowledge_chunks
                   (id, document_id, parent_chunk_id, chunk_index, section_path, content,
                    token_count, enabled, embedding, embedding_model)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::vector,%s)""",
                (
                    chunk["id"],
                    document["id"],
                    chunk["parentChunkId"],
                    chunk["chunkIndex"],
                    chunk["sectionPath"],
                    chunk["content"],
                    chunk["tokenCount"],
                    chunk["enabled"],
                    None if chunk["embedding"] is None else vector_literal(chunk["embedding"]),
                    embedding_model,
                ),
            )


def update_document(
    pool: ConnectionPool,
    document_id: str,
    document: dict[str, Any],
    document_embedding: list[float],
    embedding_model: str,
) -> None:
    with pool.connection() as connection:
        if not connection.execute(
            "SELECT 1 FROM knowledge_documents WHERE id = %s FOR UPDATE", (document_id,)
        ).fetchone():
            raise NotFoundError("知识文档不存在")
        _validate_document_links(connection, document)
        connection.execute(
            """UPDATE knowledge_documents SET
                   title = %s, category_id = %s, status = %s, document_type = %s,
                   keywords = %s, outline = %s, template_family = %s,
                   template_variant = %s, version = %s,
                   applicable_process_id = '', applicable_step_id = '',
                   applicable_scenario = %s, summary = %s,
                   document_embedding = %s::vector, embedding_model = %s, updated_at = now()
               WHERE id = %s""",
            (
                document["title"],
                document["categoryId"],
                document["status"],
                document["documentType"],
                Jsonb(document["keywords"]),
                Jsonb(document["outline"]),
                document["templateFamily"],
                document["templateVariant"],
                document["version"],
                document["applicableScenario"],
                document["summary"],
                vector_literal(document_embedding),
                embedding_model,
                document_id,
            ),
        )


def replace_document_embeddings(
    pool: ConnectionPool,
    document_id: str,
    document_embedding: list[float],
    chunk_embeddings: dict[str, list[float]],
    embedding_model: str,
) -> None:
    with pool.connection() as connection:
        updated = connection.execute(
            """UPDATE knowledge_documents
               SET document_embedding = %s::vector, embedding_model = %s, updated_at = now()
               WHERE id = %s""",
            (vector_literal(document_embedding), embedding_model, document_id),
        ).rowcount
        if updated == 0:
            raise NotFoundError("知识文档不存在")
        connection.execute(
            "UPDATE knowledge_chunks SET embedding = NULL, embedding_model = %s WHERE document_id = %s",
            (embedding_model, document_id),
        )
        for chunk_id, embedding in chunk_embeddings.items():
            connection.execute(
                """UPDATE knowledge_chunks SET embedding = %s::vector, embedding_model = %s
                   WHERE id = %s AND document_id = %s""",
                (vector_literal(embedding), embedding_model, chunk_id, document_id),
            )


def delete_document(pool: ConnectionPool, document_id: str) -> str:
    with pool.connection() as connection:
        row = connection.execute(
            "DELETE FROM knowledge_documents WHERE id = %s RETURNING original_path", (document_id,)
        ).fetchone()
        if not row:
            raise NotFoundError("知识文档不存在")
        return str(row["original_path"])


def vector_template_candidates(
    pool: ConnectionPool,
    vector: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    conditions = [
        "status = 'effective'",
        "is_generation_template = true",
        "document_embedding IS NOT NULL",
    ]
    parameters: list[Any] = [vector_literal(vector)]
    parameters.append(limit)
    with pool.connection() as connection:
        rows = connection.execute(
            f"""WITH query AS (SELECT %s::vector AS embedding)
                SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                       0 AS chunk_count, true AS indexed,
                       1 - (document_embedding <=> query.embedding) AS score
                FROM knowledge_documents d CROSS JOIN query
                WHERE {' AND '.join(conditions)}
                ORDER BY document_embedding <=> query.embedding LIMIT %s""",
            parameters,
        ).fetchall()
    return [_search_document(row) for row in rows]


def keyword_template_candidates(
    pool: ConnectionPool,
    keywords: list[str],
    limit: int,
) -> list[dict[str, Any]]:
    terms = list(dict.fromkeys(value.strip() for value in keywords if value.strip()))[:10]
    if not terms:
        return []
    searchable = "concat_ws(' ', title, document_type, template_family, template_variant, applicable_scenario, summary, keywords::text)"
    score_parts = [f"CASE WHEN lower({searchable}) LIKE '%%' || lower(%s) || '%%' THEN 1 ELSE 0 END" for _ in terms]
    matches = [f"lower({searchable}) LIKE '%%' || lower(%s) || '%%'" for _ in terms]
    parameters: list[Any] = [*terms, *terms]
    conditions = ["status = 'effective'", "is_generation_template = true", f"({' OR '.join(matches)})"]
    parameters.append(limit)
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                       0 AS chunk_count, document_embedding IS NOT NULL AS indexed,
                       ({' + '.join(score_parts)})::float AS score
                FROM knowledge_documents d WHERE {' AND '.join(conditions)}
                ORDER BY score DESC, updated_at DESC LIMIT %s""",
            parameters,
        ).fetchall()
    return [_search_document(row) for row in rows]


def vector_reference_documents(
    pool: ConnectionPool, vector: list[float], limit: int
) -> list[dict[str, Any]]:
    with pool.connection() as connection:
        rows = connection.execute(
            """WITH query AS (SELECT %s::vector AS embedding)
               SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                      0 AS chunk_count, true AS indexed,
                      1 - (document_embedding <=> query.embedding) AS score
               FROM knowledge_documents d CROSS JOIN query
               WHERE status = 'effective' AND is_reference_knowledge = true
                 AND document_embedding IS NOT NULL
               ORDER BY document_embedding <=> query.embedding LIMIT %s""",
            (vector_literal(vector), limit),
        ).fetchall()
    return [_search_document(row) for row in rows]


def keyword_reference_documents(
    pool: ConnectionPool, keywords: list[str], limit: int
) -> list[dict[str, Any]]:
    terms = list(dict.fromkeys(value.strip() for value in keywords if value.strip()))[:10]
    if not terms:
        return []
    searchable = "concat_ws(' ', title, document_type, applicable_scenario, summary, keywords::text, outline::text)"
    score_parts = [f"CASE WHEN lower({searchable}) LIKE '%%' || lower(%s) || '%%' THEN 1 ELSE 0 END" for _ in terms]
    matches = [f"lower({searchable}) LIKE '%%' || lower(%s) || '%%'" for _ in terms]
    parameters: list[Any] = [*terms, *terms, limit]
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                       0 AS chunk_count, document_embedding IS NOT NULL AS indexed,
                       ({' + '.join(score_parts)})::float AS score
                FROM knowledge_documents d
                WHERE status = 'effective' AND is_reference_knowledge = true
                  AND ({' OR '.join(matches)})
                ORDER BY score DESC, updated_at DESC LIMIT %s""",
            parameters,
        ).fetchall()
    return [_search_document(row) for row in rows]


def vector_chunk_candidates(
    pool: ConnectionPool, vector: list[float], limit: int, document_id: str | None
) -> list[dict[str, Any]]:
    filter_sql = ""
    parameters: list[Any] = [vector_literal(vector)]
    if document_id is not None:
        filter_sql = " AND d.id = %s"
        parameters.append(document_id)
    parameters.append(limit)
    with pool.connection() as connection:
        rows = connection.execute(
            f"""WITH query AS (SELECT %s::vector AS embedding)
                SELECT c.id, c.document_id, c.parent_chunk_id, c.chunk_index,
                       c.section_path, c.content, c.token_count, c.enabled,
                       d.title, d.original_name,
                       1 - (c.embedding <=> query.embedding) AS score
                FROM knowledge_chunks c
                JOIN knowledge_documents d ON d.id = c.document_id CROSS JOIN query
                WHERE d.status = 'effective' AND d.is_reference_knowledge = true
                  AND c.enabled = true AND c.embedding IS NOT NULL{filter_sql}
                ORDER BY c.embedding <=> query.embedding LIMIT %s""",
            parameters,
        ).fetchall()
    return [_search_chunk(row) for row in rows]


def keyword_chunk_candidates(
    pool: ConnectionPool,
    keywords: list[str],
    limit: int,
    document_id: str | None,
) -> list[dict[str, Any]]:
    terms = list(dict.fromkeys(value.strip() for value in keywords if value.strip()))[:10]
    if not terms:
        return []
    score_parts = ["CASE WHEN lower(c.content) LIKE '%%' || lower(%s) || '%%' THEN 1 ELSE 0 END" for _ in terms]
    matches = ["lower(c.content) LIKE '%%' || lower(%s) || '%%'" for _ in terms]
    parameters: list[Any] = [*terms, *terms]
    document_filter = ""
    if document_id is not None:
        document_filter = " AND d.id = %s"
        parameters.append(document_id)
    parameters.append(limit)
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT c.id, c.document_id, c.parent_chunk_id, c.chunk_index,
                       c.section_path, c.content, c.token_count, c.enabled,
                       d.title, d.original_name, ({' + '.join(score_parts)})::float AS score
                FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
                WHERE d.status = 'effective' AND d.is_reference_knowledge = true
                  AND c.enabled = true AND ({' OR '.join(matches)}){document_filter}
                ORDER BY score DESC, c.chunk_index LIMIT %s""",
            parameters,
        ).fetchall()
    return [_search_chunk(row) for row in rows]


def parent_chunk_contents(pool: ConnectionPool, ids: list[str]) -> dict[str, str]:
    if not ids:
        return {}
    with pool.connection() as connection:
        rows = connection.execute(
            "SELECT id, content FROM knowledge_chunks WHERE id = ANY(%s)", (ids,)
        ).fetchall()
    return {str(row["id"]): str(row["content"]) for row in rows}


def _search_document(row: dict[str, Any]) -> dict[str, Any]:
    return {
        **map_document(row),
        "parsedText": str(row["parsed_text"]),
        "score": float(row["score"]),
    }


def _search_chunk(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "documentId": str(row["document_id"]),
        "parentChunkId": None if row["parent_chunk_id"] is None else str(row["parent_chunk_id"]),
        "chunkIndex": int(row["chunk_index"]),
        "sectionPath": str(row["section_path"]),
        "content": str(row["content"]),
        "tokenCount": int(row["token_count"]),
        "enabled": bool(row["enabled"]),
        "title": str(row["title"]),
        "source": str(row["original_name"]),
        "score": float(row["score"]),
    }


def get_department_settings(pool: ConnectionPool) -> dict[str, Any]:
    with pool.connection() as connection:
        rows = connection.execute("SELECT key, value FROM department_settings").fetchall()
    saved = {str(row["key"]): row["value"] for row in rows}
    return {key: saved.get(key, value) for key, value in DEFAULT_SETTINGS.items()}


def _ensure_category_parent(connection: Any, category_id: str | None, parent_id: str | None) -> None:
    if parent_id is None:
        return
    if parent_id == category_id:
        raise ConflictError("目录不能把自己设为上级目录")
    if not connection.execute(
        "SELECT 1 FROM knowledge_categories WHERE id = %s", (parent_id,)
    ).fetchone():
        raise NotFoundError("上级目录不存在")
    if category_id and connection.execute(
        """WITH RECURSIVE descendants AS (
               SELECT id FROM knowledge_categories WHERE id = %s
               UNION ALL
               SELECT child.id FROM knowledge_categories child
               JOIN descendants parent ON child.parent_id = parent.id
           ) SELECT 1 FROM descendants WHERE id = %s LIMIT 1""",
        (category_id, parent_id),
    ).fetchone():
        raise ConflictError("目录不能移动到自己的子目录中")


def create_category(pool: ConnectionPool, data: dict[str, Any]) -> dict[str, Any]:
    category_id = f"category-{uuid4()}"
    try:
        with pool.connection() as connection:
            _ensure_category_parent(connection, None, data["parentId"])
            row = connection.execute(
                """INSERT INTO knowledge_categories (id, parent_id, name, sort_order, updated_at)
                   SELECT %s, %s, %s, COALESCE(MAX(sort_order), -10) + 10, now()
                   FROM knowledge_categories WHERE parent_id IS NOT DISTINCT FROM %s
                   RETURNING id, parent_id, name, sort_order""",
                (category_id, data["parentId"], data["name"], data["parentId"]),
            ).fetchone()
    except UniqueViolation as error:
        raise ConflictError("同一上级目录下已经存在同名目录") from error
    return _category(row)


def update_category(pool: ConnectionPool, category_id: str, data: dict[str, Any]) -> dict[str, Any]:
    try:
        with pool.connection() as connection:
            current = connection.execute(
                "SELECT parent_id FROM knowledge_categories WHERE id = %s FOR UPDATE",
                (category_id,),
            ).fetchone()
            if not current:
                raise NotFoundError("知识目录不存在")
            _ensure_category_parent(connection, category_id, data["parentId"])
            moved = current["parent_id"] != data["parentId"]
            if moved:
                next_order = connection.execute(
                    """SELECT COALESCE(MAX(sort_order), -10) + 10 AS value
                       FROM knowledge_categories
                       WHERE parent_id IS NOT DISTINCT FROM %s AND id <> %s""",
                    (data["parentId"], category_id),
                ).fetchone()["value"]
            else:
                next_order = connection.execute(
                    "SELECT sort_order AS value FROM knowledge_categories WHERE id = %s",
                    (category_id,),
                ).fetchone()["value"]
            row = connection.execute(
                """UPDATE knowledge_categories
                   SET parent_id = %s, name = %s, sort_order = %s, updated_at = now()
                   WHERE id = %s RETURNING id, parent_id, name, sort_order""",
                (data["parentId"], data["name"], next_order, category_id),
            ).fetchone()
    except UniqueViolation as error:
        raise ConflictError("同一上级目录下已经存在同名目录") from error
    return _category(row)


def reorder_categories(pool: ConnectionPool, parent_id: str | None, ids: list[str]) -> None:
    with pool.connection() as connection:
        rows = connection.execute(
            """SELECT id FROM knowledge_categories
               WHERE parent_id IS NOT DISTINCT FROM %s FOR UPDATE""",
            (parent_id,),
        ).fetchall()
        current_ids = {str(row["id"]) for row in rows}
        if current_ids != set(ids) or len(current_ids) != len(ids):
            raise ConflictError("排序列表必须包含该上级目录下的全部直属目录")
        for index, category_id in enumerate(ids):
            connection.execute(
                "UPDATE knowledge_categories SET sort_order = %s, updated_at = now() WHERE id = %s",
                (index * 10, category_id),
            )


def delete_category(pool: ConnectionPool, category_id: str) -> None:
    with pool.connection() as connection:
        state = connection.execute(
            """SELECT
                   EXISTS (SELECT 1 FROM knowledge_categories WHERE parent_id = %s) AS has_children,
                   EXISTS (SELECT 1 FROM knowledge_documents WHERE category_id = %s) AS has_documents""",
            (category_id, category_id),
        ).fetchone()
        if state["has_children"]:
            raise ConflictError("该目录还有子目录，不能删除")
        if state["has_documents"]:
            raise ConflictError("该目录还有文档，不能删除")
        deleted = connection.execute(
            "DELETE FROM knowledge_categories WHERE id = %s", (category_id,)
        ).rowcount
        if deleted == 0:
            raise NotFoundError("知识目录不存在")


def save_department_settings(pool: ConnectionPool, settings: dict[str, Any]) -> None:
    with pool.connection() as connection:
        for key, value in settings.items():
            connection.execute(
                """INSERT INTO department_settings (key, value, updated_at)
                   VALUES (%s, %s, now())
                   ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = now()""",
                (key, Jsonb(value)),
            )


def _category(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "parentId": None if row["parent_id"] is None else str(row["parent_id"]),
        "name": str(row["name"]),
        "sortOrder": int(row["sort_order"]),
    }
