# Department AI Architecture

## Dependency direction

`main -> features -> core`

Frontend shared modules follow `main -> features -> core/ui`; `core` and `ui` never import `features`.

## 新增功能入口

| Change | Start here |
|---|---|
| REST endpoint | `backend/app/features/<domain>/router.py` |
| Request validation | `backend/app/features/<domain>/schemas.py` |
| SQL/data access | `backend/app/features/<domain>/store.py` |
| Business/external-service logic | `backend/app/features/<domain>/service.py` |
| MCP tool | `backend/app/mcp_server.py`, reusing feature service/store functions |
| Frontend page behavior | `frontend/js/features/<domain>/` |
| Shared frontend interaction | `frontend/js/ui/` only after real cross-feature reuse |
| Environment setting | `backend/app/core/config.py` and `.env.example` |

## Backend domains

- `dashboard`: `/api/state` cross-domain aggregation only.
- `processes`: processes and ordered steps.
- `catalog`: knowledge categories and document purposes.
- `documents`: document lifecycle, preview, parsing, chunking, metadata, embeddings, and indexing.
- `search`: template and knowledge recall plus reranking.
- `skills`: department Skill bundles and resources.
- `settings`: assistant, chunking, retrieval, and model settings.

## Frontend domains

- `dashboard`: overview and service status.
- `processes`: process and step management.
- `knowledge`: categories, purposes, documents, upload, and recall workflows.
- `skills`: Skill management.
- `assistant`: Harness assistant entry.
- `settings`: assistant, chunking, retrieval, and model settings.

## Cross-layer mapping

- Frontend `dashboard` -> backend `dashboard`.
- Frontend `processes` -> backend `processes`.
- Frontend `knowledge` -> backend `catalog` + `documents` + `search`.
- Frontend `skills` -> backend `skills`.
- Frontend `assistant` -> no same-named backend domain; uses existing `dashboard`/`settings`/`search`/Harness/MCP composition as appropriate.
- Frontend `settings` -> backend `settings`.

## Change checklist

1. Extend the existing domain before creating a new one.
2. Preserve REST/MCP contracts unless a separately approved design changes them.
3. Add the smallest focused check for the changed domain.
4. Run checks on Aliyun; do not fall back to local project execution.
