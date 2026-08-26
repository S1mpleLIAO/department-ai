from typing import Any

from fastapi import APIRouter, Request

from app.features.catalog.schemas import CategoryInput, CategoryOrderInput, KnowledgePurposeInput
from app.features.catalog.store import (
    create_category,
    create_purpose,
    delete_category,
    delete_purpose,
    list_categories,
    list_purposes,
    reorder_categories,
    update_category,
    update_purpose,
)


router = APIRouter(tags=["catalog"])


@router.get("/api/categories")
def categories(request: Request) -> list[dict[str, Any]]:
    return list_categories(request.app.state.pool)


@router.get("/api/purposes")
def purposes(request: Request) -> list[dict[str, Any]]:
    return list_purposes(request.app.state.pool)


@router.post("/api/purposes", status_code=201)
def purpose_create(request: Request, purpose: KnowledgePurposeInput) -> dict[str, Any]:
    saved = create_purpose(request.app.state.pool, purpose.model_dump())
    return {"saved": True, "purpose": saved}


@router.put("/api/purposes/{purpose_id}")
def purpose_update(
    purpose_id: str, request: Request, purpose: KnowledgePurposeInput
) -> dict[str, Any]:
    saved = update_purpose(request.app.state.pool, purpose_id, purpose.model_dump())
    return {"saved": True, "purpose": saved}


@router.delete("/api/purposes/{purpose_id}")
def purpose_delete(purpose_id: str, request: Request) -> dict[str, bool]:
    delete_purpose(request.app.state.pool, purpose_id)
    return {"deleted": True}


@router.post("/api/categories", status_code=201)
def category_create(request: Request, category: CategoryInput) -> dict[str, Any]:
    saved = create_category(request.app.state.pool, category.model_dump())
    return {"saved": True, "category": saved}


@router.put("/api/categories/order")
def category_reorder(request: Request, order: CategoryOrderInput) -> dict[str, bool]:
    reorder_categories(request.app.state.pool, order.parentId, order.ids)
    return {"saved": True}


@router.put("/api/categories/{category_id}")
def category_update(category_id: str, request: Request, category: CategoryInput) -> dict[str, Any]:
    saved = update_category(request.app.state.pool, category_id, category.model_dump())
    return {"saved": True, "category": saved}


@router.delete("/api/categories/{category_id}")
def category_delete(category_id: str, request: Request) -> dict[str, bool]:
    delete_category(request.app.state.pool, category_id)
    return {"deleted": True}
