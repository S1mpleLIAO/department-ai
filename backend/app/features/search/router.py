from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from app.features.search.schemas import KnowledgeSearchInput, TemplateSearchInput
from app.features.search.service import search_knowledge, search_templates


router = APIRouter(prefix="/api/search", tags=["search"])


@router.post("/templates")
def template_search(request: Request, search: TemplateSearchInput) -> dict[str, Any]:
    return search_templates(
        request.state.pool,
        request.state.settings,
        search.model_dump(),
    )


@router.post("/knowledge")
def knowledge_search(request: Request, search: KnowledgeSearchInput) -> dict[str, Any]:
    return search_knowledge(
        request.state.pool,
        request.state.settings,
        search.model_dump(),
    )
