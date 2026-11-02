from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core.database import ConflictError, NotFoundError, StoreError, vector_literal

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
    document_embedding: list[float] | None,
    embedding_model: str | None,
) -> None:
    with pool.connection() as connection:
        if not connection.execute(
            "SELECT 1 FROM knowledge_documents WHERE id = %s FOR UPDATE", (document_id,)
        ).fetchone():
            raise NotFoundError("知识文档不存在")
        _validate_document_links(connection, document)
        if document_embedding is None:
            # The route detected a classification-only edit against its snapshot.
            # Never write that snapshot's profile over a newer locked profile/vector.
            connection.execute(
                """UPDATE knowledge_documents
                   SET category_id = %s, status = %s, updated_at = now()
                   WHERE id = %s""",
                (document["categoryId"], document["status"], document_id),
            )
            return
        connection.execute(
            """UPDATE knowledge_documents SET
                   title = %s, category_id = %s, status = %s, document_type = %s,
                   keywords = %s, outline = %s, template_family = %s,
                   template_variant = %s, version = %s,
                   applicable_process_id = '', applicable_step_id = '',
                   applicable_scenario = %s, summary = %s,
                   document_embedding = COALESCE(%s::vector, document_embedding),
                   embedding_model = COALESCE(%s, embedding_model), updated_at = now()
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
                None if document_embedding is None else vector_literal(document_embedding),
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
            "UPDATE knowledge_documents SET status='obsolete',updated_at=now() WHERE id = %s RETURNING original_path", (document_id,)
        ).fetchone()
        if not row:
            raise NotFoundError("知识文档不存在")
        return str(row["original_path"])
