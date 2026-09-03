from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool

from app.core.database import ConflictError, NotFoundError


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, str)]


def list_processes(pool: ConnectionPool) -> list[dict[str, Any]]:
    with pool.connection() as connection:
        processes = connection.execute(
            "SELECT id, name, description FROM business_processes ORDER BY sort_order, name"
        ).fetchall()
        steps = connection.execute(
            """SELECT process_id, id, name, objective, required_inputs, required_outputs,
                      completion_criteria, instructions
               FROM process_steps ORDER BY process_id, sort_order"""
        ).fetchall()

    steps_by_process: dict[str, list[dict[str, Any]]] = {}
    for step in steps:
        steps_by_process.setdefault(str(step["process_id"]), []).append(
            {
                "id": str(step["id"]),
                "name": str(step["name"]),
                "objective": str(step["objective"]),
                "requiredInputs": _string_list(step["required_inputs"]),
                "requiredOutputs": _string_list(step["required_outputs"]),
                "completionCriteria": _string_list(step["completion_criteria"]),
                "instructions": str(step["instructions"]),
            }
        )
    return [
        {
            "id": str(process["id"]),
            "name": str(process["name"]),
            "description": str(process["description"]),
            "steps": steps_by_process.get(str(process["id"]), []),
        }
        for process in processes
    ]


def save_process(pool: ConnectionPool, process: dict[str, Any], creating: bool) -> None:
    with pool.connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM business_processes WHERE id = %s FOR UPDATE", (process["id"],)
        ).fetchone()
        if creating and exists:
            raise ConflictError("流程 ID 已存在")
        if not creating and not exists:
            raise NotFoundError("业务流程不存在")

        if creating:
            connection.execute(
                """INSERT INTO business_processes (id, name, description, sort_order, updated_at)
                   SELECT %s, %s, %s, COALESCE(MAX(sort_order), -10) + 10, now()
                   FROM business_processes""",
                (process["id"], process["name"], process["description"]),
            )
        else:
            connection.execute(
                """UPDATE business_processes
                   SET name = %s, description = %s, updated_at = now() WHERE id = %s""",
                (process["name"], process["description"], process["id"]),
            )

        connection.execute("DELETE FROM process_steps WHERE process_id = %s", (process["id"],))
        for index, step in enumerate(process["steps"]):
            connection.execute(
                """INSERT INTO process_steps
                   (process_id, id, name, objective, required_inputs, required_outputs,
                    completion_criteria, knowledge_scopes, instructions, sort_order)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    process["id"],
                    step["id"],
                    step["name"],
                    step["objective"],
                    Jsonb(step["requiredInputs"]),
                    Jsonb(step["requiredOutputs"]),
                    Jsonb(step["completionCriteria"]),
                    Jsonb([]),
                    step["instructions"].strip(),
                    index,
                ),
            )


def delete_process(pool: ConnectionPool, process_id: str) -> None:
    with pool.connection() as connection:
        deleted = connection.execute(
            "DELETE FROM business_processes WHERE id = %s", (process_id,)
        ).rowcount
        if deleted == 0:
            raise NotFoundError("业务流程不存在")
