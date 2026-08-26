from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.features.processes.schemas import ProcessInput
from app.features.processes.store import delete_process, list_processes, save_process


router = APIRouter(prefix="/api/processes", tags=["processes"])


@router.get("")
def processes(request: Request) -> list[dict[str, Any]]:
    return list_processes(request.app.state.pool)


@router.post("", status_code=201)
def process_create(request: Request, process: ProcessInput) -> dict[str, Any]:
    data = process.model_dump()
    save_process(request.app.state.pool, data, creating=True)
    return {"saved": True, "process": data}


@router.put("/{process_id}")
def process_update(process_id: str, request: Request, process: ProcessInput) -> dict[str, Any]:
    data = process.model_dump()
    data["id"] = process_id
    save_process(request.app.state.pool, data, creating=False)
    return {"saved": True, "process": data}


@router.delete("/{process_id}")
def process_delete(process_id: str, request: Request) -> dict[str, bool]:
    delete_process(request.app.state.pool, process_id)
    return {"deleted": True}
