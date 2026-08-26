from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.core.health import docling_health, url_health
from app.features.catalog.store import list_categories, list_purposes
from app.features.documents.store import list_documents
from app.features.processes.store import list_processes
from app.features.settings.store import get_department_settings
from app.features.skills.service import list_skills


router = APIRouter(tags=["dashboard"])


@router.get("/api/state")
def state(request: Request) -> dict[str, Any]:
    pool = request.app.state.pool
    settings = request.app.state.settings
    return {
        "processes": list_processes(pool),
        "categories": list_categories(pool),
        "purposes": list_purposes(pool),
        "documents": list_documents(pool),
        "skills": list_skills(settings.skill_dir),
        "settings": get_department_settings(pool),
        "services": {
            "database": True,
            "docling": docling_health(settings.docling_base_url),
            "siliconflow": settings.siliconflow_configured,
            "metadata": bool(settings.metadata_api_key and settings.metadata_model),
            "harness": url_health(settings.harness_url),
            "harnessUrl": settings.harness_url,
        },
    }
