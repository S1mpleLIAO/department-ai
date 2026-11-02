from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from psycopg_pool import ConnectionPool
from psycopg import IntegrityError

from app.core.config import Settings, get_settings
from app.core.database import StoreError, create_pool
from app.features.catalog.router import router as catalog_router
from app.features.dashboard.router import router as dashboard_router
from app.features.documents.router import router as documents_router
from app.features.processes.router import router as processes_router
from app.features.search.router import router as search_router
from app.features.settings.router import router as settings_router
from app.features.skills.router import router as skills_router
from app.features.identity.router import router as identity_router
from app.features.identity.access import IdentityMiddleware
from app.features.reviews.router import router as reviews_router
from app.features.assistant.router import router as assistant_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    (settings.data_dir / "previews").mkdir(parents=True, exist_ok=True)
    settings.skill_dir.mkdir(parents=True, exist_ok=True)
    pool = create_pool(settings.database_url)
    try:
        pool.open(wait=True)
        with pool.connection() as conn:
            role = conn.execute("SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user").fetchone()
            if role["rolsuper"] or role["rolbypassrls"]:
                raise RuntimeError("身份版本必须使用非超级用户、非 BYPASSRLS 的应用数据库账号")
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='001_identity'").fetchone():
                raise RuntimeError("请先显式执行身份迁移，服务启动不会自动修改数据库")
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='003_review_edits'").fetchone():
                raise RuntimeError("请先显式执行审核发布迁移")
            if not conn.execute("SELECT 1 FROM schema_migrations WHERE version='004_assistant'").fetchone():
                raise RuntimeError("请先显式执行个人 AI 入口迁移")
        app.state.settings = settings
        app.state.pool = pool
        yield
    finally:
        pool.close()


app = FastAPI(title="部门 AI Python API", version="0.1.0", lifespan=lifespan)
app.add_middleware(IdentityMiddleware)
web_dir = Path(__file__).resolve().parents[2] / "frontend"


@app.exception_handler(StoreError)
def store_error_handler(_request: Request, error: StoreError) -> JSONResponse:
    return JSONResponse(status_code=error.status_code, content={"detail": str(error)})


@app.exception_handler(IntegrityError)
def integrity_error_handler(_request: Request, _error: IntegrityError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": "资料冲突或关联无效，请刷新后重试"})


def _pool(request: Request) -> ConnectionPool:
    return request.app.state.pool


def _settings(request: Request) -> Settings:
    return request.app.state.settings


@app.get("/health")
def health(request: Request) -> dict[str, Any]:
    pool = _pool(request)
    with pool.connection() as connection:
        connection.execute("SELECT 1").fetchone()
    return {"status": "ok"}


@app.get("/", include_in_schema=False)
def portal_redirect() -> RedirectResponse:
    return RedirectResponse("/department")


@app.get("/department", include_in_schema=False)
def portal() -> FileResponse:
    return FileResponse(web_dir / "index.html")


app.include_router(processes_router)
app.include_router(identity_router)
app.include_router(reviews_router)
app.include_router(assistant_router)
app.include_router(catalog_router)
app.include_router(skills_router)
app.include_router(settings_router)
app.include_router(dashboard_router)
app.include_router(search_router)
app.include_router(documents_router)


app.mount("/department", StaticFiles(directory=web_dir), name="department-web")

# MCP and Harness remain unavailable in this isolated identity build until their
# request identity bridge is implemented. Never fall back to a shared runtime.
