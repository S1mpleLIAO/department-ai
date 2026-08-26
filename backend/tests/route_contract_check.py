from pathlib import Path

from fastapi.responses import FileResponse, RedirectResponse
from fastapi.routing import APIRoute
from fastapi.staticfiles import StaticFiles
from starlette.routing import Mount

from app.main import app, mcp_app


EXPECTED = [
    ("GET", "/health", 200),
    ("GET", "/api/processes", 200),
    ("POST", "/api/processes", 201),
    ("PUT", "/api/processes/{process_id}", 200),
    ("DELETE", "/api/processes/{process_id}", 200),
    ("GET", "/api/categories", 200),
    ("GET", "/api/purposes", 200),
    ("POST", "/api/purposes", 201),
    ("PUT", "/api/purposes/{purpose_id}", 200),
    ("DELETE", "/api/purposes/{purpose_id}", 200),
    ("POST", "/api/categories", 201),
    ("PUT", "/api/categories/order", 200),
    ("PUT", "/api/categories/{category_id}", 200),
    ("DELETE", "/api/categories/{category_id}", 200),
    ("GET", "/api/skills", 200),
    ("POST", "/api/skills", 201),
    ("PUT", "/api/skills/{skill_id}", 200),
    ("DELETE", "/api/skills/{skill_id}", 200),
    ("PUT", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("GET", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("DELETE", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("GET", "/api/settings", 200),
    ("PUT", "/api/settings", 200),
    ("GET", "/api/state", 200),
    ("POST", "/api/search/templates", 200),
    ("POST", "/api/search/knowledge", 200),
    ("GET", "/api/documents", 200),
    ("GET", "/api/documents/{document_id}", 200),
    ("GET", "/api/documents/{document_id}/source", 200),
    ("PUT", "/api/documents/{document_id}", 200),
    ("POST", "/api/documents/{document_id}/reindex", 200),
    ("DELETE", "/api/documents/{document_id}", 200),
    ("POST", "/api/knowledge/preview", 200),
    ("POST", "/api/knowledge/previews/{preview_id}/rechunk", 200),
    ("DELETE", "/api/knowledge/previews/{preview_id}", 200),
    ("POST", "/api/knowledge/previews/{preview_id}/index", 201),
]


def api_routes(routes):
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        elif included := getattr(route, "original_router", None):
            yield from api_routes(included.routes)


def main() -> None:
    actual = [
        (method, route.path, route.status_code or 200)
        for route in api_routes(app.routes)
        if route.path == "/health" or route.path.startswith("/api/")
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    ]
    assert actual == EXPECTED, {
        "missing": set(EXPECTED) - set(actual),
        "unexpected": set(actual) - set(EXPECTED),
        "actualOrder": actual,
    }

    category_put_paths = [
        route.path
        for route in api_routes(app.routes)
        if isinstance(route, APIRoute)
        and "PUT" in route.methods
        and route.path in {"/api/categories/order", "/api/categories/{category_id}"}
    ]
    assert category_put_paths == [
        "/api/categories/order",
        "/api/categories/{category_id}",
    ], category_put_paths

    root_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute) and route.path == "/" and "GET" in route.methods
    ]
    assert len(root_routes) == 1, root_routes
    redirect = root_routes[0].endpoint()
    assert isinstance(redirect, RedirectResponse)
    assert redirect.status_code == 307
    assert redirect.headers["location"] == "/department"

    portal_routes = [
        route
        for route in app.routes
        if isinstance(route, APIRoute)
        and route.path == "/department"
        and "GET" in route.methods
    ]
    assert len(portal_routes) == 1, portal_routes
    portal = portal_routes[0].endpoint()
    assert isinstance(portal, FileResponse)
    assert portal.status_code == 200
    assert portal.path == Path(__file__).resolve().parents[2] / "frontend" / "index.html"

    static_mounts = [
        (index, route)
        for index, route in enumerate(app.routes)
        if isinstance(route, Mount) and route.path == "/department"
    ]
    mcp_mounts = [
        (index, route)
        for index, route in enumerate(app.routes)
        if isinstance(route, Mount) and route.path == ""
    ]
    assert len(static_mounts) == 1, static_mounts
    assert len(mcp_mounts) == 1, mcp_mounts
    static_index, static_mount = static_mounts[0]
    mcp_index, mcp_mount = mcp_mounts[0]
    assert isinstance(static_mount.app, StaticFiles)
    assert static_mount.name == "department-web"
    assert mcp_mount.name is None
    assert mcp_mount.app is mcp_app
    assert static_index < mcp_index == len(app.routes) - 1
    print("route-contract-check: ok")


if __name__ == "__main__":
    main()
