from __future__ import annotations

import base64
import binascii
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from app.core.database import StoreError
from app.features.skills.schemas import SkillInput, SkillResourceInput
from app.features.skills.service import (
    delete_skill,
    delete_skill_resource,
    list_skills,
    read_skill_resource,
    save_skill,
    save_skill_resource,
)


router = APIRouter(tags=["skills"])


@router.get("/api/skills")
def skills(request: Request) -> list[dict[str, Any]]:
    return list_skills(request.app.state.settings.skill_dir)


@router.post("/api/skills", status_code=201)
def skill_create(request: Request, skill: SkillInput) -> dict[str, Any]:
    saved = save_skill(request.app.state.settings.skill_dir, skill.model_dump())
    return {"saved": True, "skill": saved}


@router.put("/api/skills/{skill_id}")
def skill_update(skill_id: str, request: Request, skill: SkillInput) -> dict[str, Any]:
    saved = save_skill(request.app.state.settings.skill_dir, skill.model_dump(), skill_id)
    return {"saved": True, "skill": saved}


@router.delete("/api/skills/{skill_id}")
def skill_delete(skill_id: str, request: Request) -> dict[str, bool]:
    delete_skill(request.app.state.settings.skill_dir, skill_id)
    return {"deleted": True}


@router.put("/api/skills/{skill_id}/resources/{resource_path:path}")
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
    settings = request.app.state.settings
    resource = save_skill_resource(
        settings.skill_dir,
        skill_id,
        resource_path,
        content,
        settings.max_source_bytes,
    )
    return {"saved": True, "resource": resource}


@router.get("/api/skills/{skill_id}/resources/{resource_path:path}")
def skill_resource_download(
    skill_id: str, resource_path: str, request: Request
) -> FileResponse:
    resource = read_skill_resource(
        request.app.state.settings.skill_dir, skill_id, resource_path
    )
    return FileResponse(resource, filename=resource.name)


@router.delete("/api/skills/{skill_id}/resources/{resource_path:path}")
def skill_resource_delete(
    skill_id: str, resource_path: str, request: Request
) -> dict[str, bool]:
    delete_skill_resource(request.app.state.settings.skill_dir, skill_id, resource_path)
    return {"deleted": True}
