from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.errors import UniqueViolation
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core.database import ConflictError, NotFoundError
from app.db import DEFAULT_SETTINGS  # removed by settings-domain task


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


def _iso(value: Any) -> str:
    if not isinstance(value, datetime):
        return str(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


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


def _category(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(row["id"]),
        "parentId": None if row["parent_id"] is None else str(row["parent_id"]),
        "name": str(row["name"]),
        "sortOrder": int(row["sort_order"]),
    }
