from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from psycopg_pool import ConnectionPool

from app.core.database import vector_literal


def _scope_filter(
    process_id: str | None, step_id: str | None, task_scenario: str
) -> tuple[str, tuple[str, ...]] | None:
    if process_id is not None and step_id is not None:
        return "d.applicable_process_id = %s", (process_id,)
    task = task_scenario.strip()
    if task:
        return (
            "d.applicable_process_id = '' AND d.applicable_step_id = '' "
            "AND lower(trim(d.applicable_scenario)) = lower(trim(%s))",
            (task,),
        )
    return None


def _scope_order(
    process_id: str | None, step_id: str | None, stable_order: str
) -> tuple[str, tuple[str, ...]]:
    if process_id is not None and step_id is not None:
        return (
            f"CASE WHEN d.applicable_step_id = %s THEN 0 ELSE 1 END, {stable_order}",
            (step_id,),
        )
    return stable_order, ()


def scoped_template_candidates(
    pool: ConnectionPool,
    process_id: str | None,
    step_id: str | None,
    task_scenario: str,
    limit: int,
) -> list[dict[str, Any]]:
    scope = _scope_filter(process_id, step_id, task_scenario)
    if scope is None:
        return []
    condition, parameters = scope
    order, order_parameters = _scope_order(process_id, step_id, "d.updated_at DESC")
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                       0 AS chunk_count, document_embedding IS NOT NULL AS indexed,
                       0.0 AS score
                FROM knowledge_documents d
                WHERE d.status = 'effective' AND d.is_generation_template = true
                  AND {condition}
                ORDER BY {order} LIMIT %s""",
            (*parameters, *order_parameters, limit),
        ).fetchall()
    return [_search_document(row) for row in rows]


def scoped_reference_documents(
    pool: ConnectionPool,
    process_id: str | None,
    step_id: str | None,
    task_scenario: str,
    limit: int,
) -> list[dict[str, Any]]:
    scope = _scope_filter(process_id, step_id, task_scenario)
    if scope is None:
        return []
    condition, parameters = scope
    order, order_parameters = _scope_order(process_id, step_id, "d.updated_at DESC")
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT d.*, (SELECT name FROM knowledge_purposes p WHERE p.id = d.purpose_id) AS purpose_name,
                       0 AS chunk_count, document_embedding IS NOT NULL AS indexed,
                       0.0 AS score
                FROM knowledge_documents d
                WHERE d.status = 'effective' AND d.is_reference_knowledge = true
                  AND {condition}
                ORDER BY {order} LIMIT %s""",
            (*parameters, *order_parameters, limit),
        ).fetchall()
    return [_search_document(row) for row in rows]


def scoped_chunk_candidates(
    pool: ConnectionPool,
    process_id: str | None,
    step_id: str | None,
    task_scenario: str,
    limit: int,
) -> list[dict[str, Any]]:
    scope = _scope_filter(process_id, step_id, task_scenario)
    if scope is None:
        return []
    condition, parameters = scope
    order, order_parameters = _scope_order(
        process_id, step_id, "d.updated_at DESC, c.chunk_index"
    )
    with pool.connection() as connection:
        rows = connection.execute(
            f"""SELECT c.id, c.document_id, c.parent_chunk_id, c.chunk_index,
                       c.section_path, c.content, c.token_count, c.enabled,
                       d.title, d.original_name, d.applicable_process_id,
                       d.applicable_step_id, d.applicable_scenario, 0.0 AS score
                FROM knowledge_chunks c JOIN knowledge_documents d ON d.id = c.document_id
                WHERE d.status = 'effective' AND d.is_reference_knowledge = true
                  AND c.enabled = true AND {condition}
                ORDER BY {order} LIMIT %s""",
            (*parameters, *order_parameters, limit),
        ).fetchall()
    return [_search_chunk(row) for row in rows]


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
                       d.title, d.original_name, d.applicable_process_id,
                       d.applicable_step_id, d.applicable_scenario,
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
                       d.title, d.original_name, d.applicable_process_id,
                       d.applicable_step_id, d.applicable_scenario,
                       ({' + '.join(score_parts)})::float AS score
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
    is_template = bool(row["is_generation_template"])
    is_reference = bool(row["is_reference_knowledge"])
    purpose = "both" if is_template and is_reference else "template" if is_template else "reference"

    def iso(value: Any) -> str:
        if not isinstance(value, datetime):
            return str(value)
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    def string_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item for item in value if isinstance(item, str)]

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
        "keywords": string_list(row["keywords"]),
        "outline": string_list(row["outline"]),
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
        "createdAt": iso(row["created_at"]),
        "updatedAt": iso(row["updated_at"]),
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
        "applicableProcessId": str(row["applicable_process_id"]),
        "applicableStepId": str(row["applicable_step_id"]),
        "applicableScenario": str(row["applicable_scenario"]),
        "score": float(row["score"]),
    }
