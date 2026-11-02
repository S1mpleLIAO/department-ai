"""HTTP identity boundary. Unclassified APIs fail closed; no production bypass flag."""
import re
import secrets
from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from app.core.security import ScopedPool, scoped_settings
from .service import authenticate, COOKIE

# Existing publication endpoints write live content. Until revision/review is
# implemented they require explicit direct-publication authority as well.
ROUTES = [
 ("POST",r"/api/assistant/entry",("assistant.use",)),
 ("GET",r"/api/reviews(?:/[^/]+(?:/source|/resources/.+)?)?",()),
 ("POST",r"/api/reviews(?:/edits|/[^/]+/(?:submit|approve|reject|publish))?",()),
 ("PUT",r"/api/reviews/[^/]+",()),
 ("GET",r"/api/state",()),
 ("GET",r"/api/processes",("processes.read",)),
 ("POST",r"/api/processes",("processes.create","processes.publish_direct")),
 ("PUT",r"/api/processes/[^/]+",("processes.edit_any","processes.publish_direct")),
 ("DELETE",r"/api/processes/[^/]+",("processes.archive",)),
 ("GET",r"/api/(categories|purposes)",("catalog.read",)),
 ("POST",r"/api/(categories|purposes)",("catalog.manage",)),
 ("PUT",r"/api/(categories|purposes)/[^/]+",("catalog.manage",)),
 ("DELETE",r"/api/(categories|purposes)/[^/]+",("catalog.manage",)),
 ("GET",r"/api/documents(?:/[^/]+)?",("knowledge.read",)),
 ("GET",r"/api/documents/[^/]+/source",("knowledge.read","knowledge.source_download")),
 ("PUT",r"/api/documents/[^/]+",("knowledge.edit_any","knowledge.publish_direct")),
 ("DELETE",r"/api/documents/[^/]+",("knowledge.archive",)),
 ("POST",r"/api/documents/[^/]+/reindex",("knowledge.reindex",)),
 ("POST",r"/api/search/(templates|knowledge)",("knowledge.read",)),
 ("POST",r"/api/knowledge/preview",("knowledge.create",)),
 ("POST",r"/api/knowledge/previews/[^/]+/(analyze|rechunk)",("knowledge.create",)),
 ("DELETE",r"/api/knowledge/previews/[^/]+",("knowledge.create",)),
 ("POST",r"/api/knowledge/previews/[^/]+/index",("knowledge.create","knowledge.publish_direct")),
 ("GET",r"/api/skills(?:/[^/]+/resources/.+)?",("skills.source_read",)),
 ("POST",r"/api/skills",("skills.create","skills.publish_direct")),
 ("PUT",r"/api/skills/[^/]+(?:/resources/.+)?",("skills.edit_any","skills.publish_direct")),
 # Skill archive is a disable operation. Resource deletion remains publication.
 ("DELETE",r"/api/skills/[^/]+",("skills.archive",)),
 ("DELETE",r"/api/skills/[^/]+/resources/.+",("skills.edit_any","skills.publish_direct")),
]


def authorize(request):
    app = request.app
    settings = app.state.settings
    path, method = request.url.path, request.method
    if method not in ("GET","HEAD","OPTIONS"):
        if request.headers.get("origin") != settings.auth_origin:
            raise HTTPException(403,"请求来源不受信任，请从系统页面操作")
    if path == "/api/auth/login" and method == "POST":
        return
    p, row = authenticate(app.state.pool, request.cookies.get(COOKIE))
    request.state.principal, request.state.identity_row = p, row
    if method not in ("GET","HEAD","OPTIONS"):
        if not secrets.compare_digest(request.headers.get("x-csrf-token",""), row["csrf"]):
            raise HTTPException(403,"页面校验已失效，请刷新后重试")
    if p.must_change and path not in ("/api/me","/api/me/password","/api/auth/logout"):
        raise HTTPException(403,"请先修改初始密码")
    if path.startswith("/api/admin/") or path == "/api/settings":
        if not p.superadmin:
            raise HTTPException(403,"仅超级管理员可以管理系统")
        request.state.pool = app.state.pool
        request.state.settings = settings
        return
    if path.startswith("/api/auth/") or path == "/api/me" or path.startswith("/api/me/"):
        return
    match = next((actions for verb, pattern, actions in ROUTES
                  if method==verb and re.fullmatch(pattern,path)), None)
    if match is None:
        raise HTTPException(403,"此接口尚未接入权限管理")
    selected = request.headers.get("x-department-space")
    query_space = request.query_params.get("space")
    if selected and query_space and selected != query_space:
        raise HTTPException(400,"空间上下文不一致")
    space = selected or query_space or p.company_id
    with app.state.pool.connection() as conn:
        exists = conn.execute("SELECT 1 FROM spaces WHERE id=%s",(space,)).fetchone()
    if not exists or (not p.superadmin and space not in p.grants):
        raise HTTPException(403,"没有访问此空间的权限")
    if space == "legacy" and method not in ("GET","HEAD"):
        raise HTTPException(403,"历史资料尚未确认归属，只能查看")
    p.require(space,*match)
    request.state.space = space
    request.state.pool = ScopedPool(app.state.pool,p,space)
    request.state.settings = scoped_settings(settings,p,space)


class IdentityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            try:
                await run_in_threadpool(authorize,request)
            except HTTPException as error:
                return JSONResponse({"detail":error.detail},status_code=error.status_code,
                                    headers={"Cache-Control":"no-store"})
        elif path not in ("/health","/","/department") and not path.startswith("/department/"):
            # No shared unauthenticated MCP/Harness fallback in the identity build.
            return JSONResponse({"detail":"此入口尚未完成身份接入"},status_code=403)
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        # Cross-origin form POST must retain its Origin for the one-time AI bridge.
        # Cross-origin referrers contain only the origin, never path/query data.
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        if path.startswith("/api/") and request.method not in ("GET","HEAD","OPTIONS") and response.status_code < 400:
            p = getattr(request.state,"principal",None)
            if p and not path.startswith(("/api/auth/","/api/admin/","/api/me")):
                from .service import audit
                def log():
                    with request.app.state.pool.connection() as conn:
                        audit(conn,p.user_id,request.method+" "+path,space=getattr(request.state,"space",None))
                await run_in_threadpool(log)
        return response

