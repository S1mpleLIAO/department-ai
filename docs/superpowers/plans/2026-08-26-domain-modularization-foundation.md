# Domain Modularization Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Establish a verified behavioral baseline and durable architecture rules before moving existing code.

**Architecture:** Preserve the current application unchanged while adding characterization checks for REST routes and project-owned guidance for module boundaries. The checks become the safety net used by the backend and frontend modularization plans.

**Tech Stack:** POSIX shell, Python 3.11, FastAPI route metadata, Node.js 24, JSDOM, Markdown.

**Spec:** `docs/superpowers/specs/2026-08-26-domain-modularization-design.md`

## Global Constraints

- Do not change REST paths, HTTP methods, status codes, response shapes, MCP tools, database schema, page behavior, or visual appearance.
- Do not add Python, Node, or browser dependencies.
- Edit ordinary files through the mounted workspace.
- Run project execution, tests, dependency commands, database commands, Docker commands, and all Git commands on Aliyun under `/root/liao/DepartmentKnowledgeBase/department-ai`.
- Do not move or batch-process archives, build outputs, or binary files.
- Keep each task independently verifiable and commit only the files listed for that task.

---

### Task 1: Record the Existing Green Baseline

**Files:**
- Read: `tests/server_scripts_check.sh`
- Read: `tests/deploy_state_check.sh`
- Read: `backend/tests/self_check.py`
- Read: `frontend/tests/settings_ui_check.mjs`
- Read: `frontend/tests/premium_ui_check.mjs`

**Interfaces:**
- Consumes: Existing Conda environment `department-ai` and sibling `../deepseek-harness/node_modules/jsdom`.
- Produces: A confirmed pre-refactor baseline; no repository files change.

- [ ] **Step 1: Confirm the Aliyun worktree before running checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git status --short --branch'
```

Expected: the current branch is shown; preserve every pre-existing change and do not stage it.

- [ ] **Step 2: Run the root shell checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && sh tests/server_scripts_check.sh && sh tests/deploy_state_check.sh'
```

Expected: `server script checks passed` and `deploy state checks passed`.

- [ ] **Step 3: Run the backend offline self-check**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check'
```

Expected: `self-check: ok`.

- [ ] **Step 4: Run the existing frontend UI checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/settings_ui_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

Expected: `settings-ui-check: ok` and `premium-ui-check: ok`.

- [ ] **Step 5: Stop if the baseline is not green**

Do not begin refactoring when a baseline command fails. Diagnose the existing failure separately and record which command failed; do not weaken or delete the check.

### Task 2: Add a REST Route Contract Check

**Files:**
- Create: `backend/tests/route_contract_check.py`

**Interfaces:**
- Consumes: `app.main.app: FastAPI` and FastAPI `APIRoute` metadata.
- Produces: `main() -> None`, which asserts the exact business route method/path/status triples.

- [ ] **Step 1: Create the route characterization check**

Create `backend/tests/route_contract_check.py` with this complete contract:

```python
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
```

- [ ] **Step 2: Run the characterization check against the monolith**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.route_contract_check'
```

Expected: `route-contract-check: ok`. This is intentionally a green characterization test; it records current behavior before extraction.

- [ ] **Step 3: Commit the route contract**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/tests/route_contract_check.py && git commit -m "test: lock REST route contract"'
```

Expected: one commit containing only `backend/tests/route_contract_check.py`.

### Task 3: Add Durable Architecture Guidance

**Files:**
- Modify: `AGENTS.md`
- Create: `docs/architecture.md`
- Modify: `tests/server_scripts_check.sh`

**Interfaces:**
- Consumes: The approved directory and dependency rules from the design spec.
- Produces: A developer-facing feature map and an executable check that the guidance remains present.

- [ ] **Step 1: Add failing documentation assertions to the shell check**

Add these exact assertions near the existing `require_file` and `require_text` checks:

```sh
require_file AGENTS.md
require_file docs/architecture.md
require_text AGENTS.md 'backend/app/main.py'
require_text AGENTS.md 'frontend/js/main.js'
require_text docs/architecture.md 'main -> features -> core'
require_text docs/architecture.md '新增功能入口'
```

- [ ] **Step 2: Run the check and verify it fails before the architecture guide exists**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && sh tests/server_scripts_check.sh'
```

Expected: FAIL with `missing: docs/architecture.md`.

- [ ] **Step 3: Extend `AGENTS.md` with the approved module rules**

Append this section without changing the existing Aliyun execution rules:

```markdown
## Architecture boundaries

- Organize new business functionality under the matching backend and frontend feature domain.
- Keep `backend/app/main.py` limited to application composition, lifespan, health/portal endpoints, router registration, and mounts.
- Keep `frontend/js/main.js` limited to startup, hash routing, page registration, and initial state loading.
- Create a shared module only after at least two business domains need the same behavior.
- Shared `core` and `ui` modules must not import concrete feature modules.
- Do not mix REST contract changes, database schema changes, or cross-domain architecture changes into an ordinary feature change; design those separately first.
```

- [ ] **Step 4: Create the architecture map**

Create `docs/architecture.md` with these required sections and mappings:

```markdown
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

## Business domains

- `dashboard`: `/api/state` cross-domain aggregation only.
- `processes`: processes and ordered steps.
- `catalog`: knowledge categories and document purposes.
- `documents`: document lifecycle, preview, parsing, chunking, metadata, embeddings, and indexing.
- `search`: template and knowledge recall plus reranking.
- `skills`: department Skill bundles and resources.
- `settings`: assistant, chunking, retrieval, and model settings.

## Change checklist

1. Extend the existing domain before creating a new one.
2. Preserve REST/MCP contracts unless a separately approved design changes them.
3. Add the smallest focused check for the changed domain.
4. Run checks on Aliyun; do not fall back to local project execution.
```

- [ ] **Step 5: Run the shell check and verify it passes**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && sh tests/server_scripts_check.sh'
```

Expected: `server script checks passed`.

- [ ] **Step 6: Run the full foundation verification**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && sh tests/server_scripts_check.sh && sh tests/deploy_state_check.sh && cd backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check'
```

Expected: all four root/backend checks report success.

- [ ] **Step 7: Commit the durable guidance**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add AGENTS.md docs/architecture.md tests/server_scripts_check.sh && git commit -m "docs: define modular architecture boundaries"'
```

Expected: one commit containing exactly the three listed files.
