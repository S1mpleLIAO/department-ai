from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool

from app.core.config import Settings, get_settings
from app.core.database import StoreError, create_pool
from app.core.health import docling_health, url_health
from app.features.catalog.router import router as catalog_router
from app.features.catalog.store import ensure_knowledge_purpose_schema
from app.features.dashboard.router import router as dashboard_router
from app.features.documents.router import router as documents_router
from app.features.documents.service import cleanup_previews
from app.features.processes.router import router as processes_router
from app.features.search.router import router as search_router
from app.features.settings.router import router as settings_router
from app.features.skills.router import router as skills_router
from app.mcp_server import clear_runtime, mcp, mcp_app, set_runtime


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    (settings.data_dir / "previews").mkdir(parents=True, exist_ok=True)
    settings.skill_dir.mkdir(parents=True, exist_ok=True)
    cleanup_previews(settings.data_dir)
    pool = create_pool(settings.database_url)
    pool.open(wait=True)
    ensure_knowledge_purpose_schema(pool)
    app.state.settings = settings
    app.state.pool = pool
    set_runtime(pool, settings)
    try:
        async with mcp.session_manager.run():
            yield
    finally:
        clear_runtime()
        pool.close()


app = FastAPI(title="部门 AI Python API", version="0.1.0", lifespan=lifespan)
web_dir = Path(__file__).resolve().parents[2] / "frontend"


@app.exception_handler(StoreError)
def store_error_handler(_request: Request, error: StoreError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


def _pool(request: Request) -> ConnectionPool:
    return request.app.state.pool


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    pool = _pool(request)
    with pool.connection() as connection:
        connection.execute("SELECT 1").fetchone()
    settings = _settings(request)
    return {
        "status": "ok",
        "database": "ok",
        "docling": "ok" if docling_health(settings.docling_base_url) else "unavailable",
        "siliconflowConfigured": settings.siliconflow_configured,
        "metadataConfigured": bool(settings.metadata_api_key and settings.metadata_model),
        "harness": "ok" if url_health(settings.harness_url) else "unavailable",
    }


@app.get("/", include_in_schema=False)
def portal_redirect() -> RedirectResponse:
    return RedirectResponse("/department")


@app.get("/department", include_in_schema=False)
def portal() -> FileResponse:
    return FileResponse(web_dir / "index.html")


app.include_router(processes_router)
app.include_router(catalog_router)
app.include_router(skills_router)
app.include_router(settings_router)
app.include_router(dashboard_router)
app.include_router(search_router)
app.include_router(documents_router)


app.mount("/department", StaticFiles(directory=web_dir), name="department-web")

# 放在普通 API 路由之后；MCP 子应用的默认端点因此正好是 /mcp。
app.mount("/", mcp_app)
