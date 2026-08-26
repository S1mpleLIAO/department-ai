from fastapi.routing import APIRoute

from app.main import app


EXPECTED = {
    ("GET", "/health", 200),
    ("GET", "/api/processes", 200),
    ("POST", "/api/processes", 201),
    ("PUT", "/api/processes/{process_id}", 200),
    ("DELETE", "/api/processes/{process_id}", 200),
    ("GET", "/api/categories", 200),
    ("POST", "/api/categories", 201),
    ("PUT", "/api/categories/order", 200),
    ("PUT", "/api/categories/{category_id}", 200),
    ("DELETE", "/api/categories/{category_id}", 200),
    ("GET", "/api/purposes", 200),
    ("POST", "/api/purposes", 201),
    ("PUT", "/api/purposes/{purpose_id}", 200),
    ("DELETE", "/api/purposes/{purpose_id}", 200),
    ("GET", "/api/documents", 200),
    ("GET", "/api/documents/{document_id}", 200),
    ("GET", "/api/documents/{document_id}/source", 200),
    ("PUT", "/api/documents/{document_id}", 200),
    ("POST", "/api/documents/{document_id}/reindex", 200),
    ("DELETE", "/api/documents/{document_id}", 200),
    ("GET", "/api/settings", 200),
    ("PUT", "/api/settings", 200),
    ("GET", "/api/skills", 200),
    ("POST", "/api/skills", 201),
    ("PUT", "/api/skills/{skill_id}", 200),
    ("DELETE", "/api/skills/{skill_id}", 200),
    ("PUT", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("GET", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("DELETE", "/api/skills/{skill_id}/resources/{resource_path:path}", 200),
    ("POST", "/api/knowledge/preview", 200),
    ("POST", "/api/knowledge/previews/{preview_id}/rechunk", 200),
    ("DELETE", "/api/knowledge/previews/{preview_id}", 200),
    ("POST", "/api/knowledge/previews/{preview_id}/index", 201),
    ("POST", "/api/search/templates", 200),
    ("POST", "/api/search/knowledge", 200),
    ("GET", "/api/state", 200),
}


def main() -> None:
    actual = {
        (method, route.path, route.status_code or 200)
        for route in app.routes
        if isinstance(route, APIRoute)
        and (route.path == "/health" or route.path.startswith("/api/"))
        for method in route.methods
        if method not in {"HEAD", "OPTIONS"}
    }
    assert actual == EXPECTED, {"missing": EXPECTED - actual, "unexpected": actual - EXPECTED}
    print("route-contract-check: ok")


if __name__ == "__main__":
    main()
