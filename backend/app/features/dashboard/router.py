from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.health import docling_health, harness_health
from app.features.catalog.store import list_categories, list_purposes
from app.features.documents.store import list_documents
from app.features.processes.store import list_processes
from app.features.settings.store import get_department_settings
from app.features.skills.publications import list_available_skills


router = APIRouter(tags=["dashboard"])


@router.get("/api/state")
def state(request: Request) -> dict[str, Any]:
    from app.features.assistant.auth import origins
    pool = request.state.pool
    settings = request.state.settings
    p, space = request.state.principal, request.state.space
    can = lambda action: p.allowed(space, action)
    config = get_department_settings(pool)
    return {
        "processes": list_processes(pool) if can("processes.read") else [],
        "categories": list_categories(pool) if can("catalog.read") else [],
        "purposes": list_purposes(pool) if can("catalog.read") else [],
        "documents": list_documents(pool) if can("knowledge.read") else [],
        "skills": list_available_skills(pool,settings.skill_dir) if can("skills.source_read") else [],
        "settings": config if p.superadmin else {k:config[k] for k in ("chunking","retrieval","embeddingModel","rerankModel")},
        "services": {
            "database": True,
            "docling": docling_health(settings.docling_base_url),
            "siliconflow": settings.siliconflow_configured,
            "metadata": bool(settings.metadata_api_key and settings.metadata_model),
            "harness": bool(origins().get(space)) and can("assistant.use"),
            "harnessUrl": "",
        },
    }
