from __future__ import annotations

import base64
import binascii
from functools import wraps
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse, Response
from app.features.skills.publications import list_available_skills, publication, require_file_skill, lock_skills

from app.core.database import StoreError, TransactionPool
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


def serialized_write(handler):
    @wraps(handler)
    def wrapped(*args, **kwargs):
        request = kwargs.get("request") or next(arg for arg in args if isinstance(arg,Request))
        with request.state.pool.connection() as conn:
            lock_skills(conn)
            original = request.state.pool
            request.state.pool = TransactionPool(conn)
            try:
                return handler(*args, **kwargs)
            finally:
                request.state.pool = original
    return wrapped


@router.get("/api/skills")
def skills(request: Request) -> list[dict[str, Any]]:
    return list_available_skills(request.state.pool,request.state.settings.skill_dir)


@router.post("/api/skills", status_code=201)
@serialized_write
def skill_create(request: Request, skill: SkillInput) -> dict[str, Any]:
    require_file_skill(request.state.pool,skill.name)
    saved = save_skill(request.state.settings.skill_dir, skill.model_dump())
    return {"saved": True, "skill": saved}


@router.put("/api/skills/{skill_id}")
@serialized_write
def skill_update(skill_id: str, request: Request, skill: SkillInput) -> dict[str, Any]:
    require_file_skill(request.state.pool,skill_id)
    require_file_skill(request.state.pool,skill.name)
    saved = save_skill(request.state.settings.skill_dir, skill.model_dump(), skill_id)
    return {"saved": True, "skill": saved}


@router.delete("/api/skills/{skill_id}")
@serialized_write
def skill_delete(skill_id: str, request: Request) -> dict[str, bool]:
    if publication(request.state.pool,skill_id):
        with request.state.pool.connection() as conn:
            conn.execute("UPDATE skill_publications SET enabled=false,updated_at=now() WHERE id=%s",(skill_id,))
        return {"deleted":True}
    from app.core.database import NotFoundError
    directory = request.state.settings.skill_dir
    current = next((s for s in list_skills(directory) if s["id"] == skill_id), None)
    if current is None:
        raise NotFoundError("技能不存在")
    save_skill(directory, {**current, "enabled": False}, skill_id)
    return {"deleted": True}


@router.put("/api/skills/{skill_id}/resources/{resource_path:path}")
@serialized_write
def skill_resource_save(
    skill_id: str,
    resource_path: str,
    request: Request,
    upload: SkillResourceInput,
) -> dict[str, Any]:
    require_file_skill(request.state.pool,skill_id)
    try:
        content = base64.b64decode(upload.contentBase64, validate=True)
    except (ValueError, binascii.Error) as error:
        raise StoreError("技能资源内容不是有效的 Base64") from error
    settings = request.state.settings
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
) -> Response:
    reviewed=publication(request.state.pool,skill_id)
    if reviewed:
        from urllib.parse import quote
        from app.core.database import NotFoundError
        for item in reviewed["data"].get("resources",[]):
            if item["path"]==resource_path:
                return Response(base64.b64decode(item["contentBase64"]),media_type="application/octet-stream",
                                headers={"Content-Disposition":"attachment; filename*=UTF-8''"+quote(resource_path.split("/")[-1])})
        raise NotFoundError("技能附件不存在")
    resource = read_skill_resource(
        request.state.settings.skill_dir, skill_id, resource_path
    )
    return FileResponse(resource, filename=resource.name)


@router.delete("/api/skills/{skill_id}/resources/{resource_path:path}")
@serialized_write
def skill_resource_delete(
    skill_id: str, resource_path: str, request: Request
) -> dict[str, bool]:
    require_file_skill(request.state.pool,skill_id)
    delete_skill_resource(request.state.settings.skill_dir, skill_id, resource_path)
    return {"deleted": True}
