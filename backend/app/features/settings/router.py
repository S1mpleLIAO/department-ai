from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.features.settings.schemas import DepartmentSettingsInput
from app.features.settings.store import get_department_settings, save_department_settings


router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def settings(request: Request) -> dict[str, Any]:
    return get_department_settings(request.app.state.pool)


@router.put("")
def settings_update(request: Request, settings: DepartmentSettingsInput) -> dict[str, Any]:
    data = settings.model_dump()
    save_department_settings(request.app.state.pool, data)
    return {"saved": True, "settings": data}
