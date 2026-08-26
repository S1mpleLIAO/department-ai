# Backend Domain Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the FastAPI backend into focused business-domain modules without changing any REST, MCP, database, or external-service behavior.

**Architecture:** `app.main` composes domain `APIRouter` instances. Each domain owns its Pydantic inputs and store/service functions; shared configuration, database primitives, errors, and validation primitives live in `app.core`.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, Psycopg 3, PostgreSQL/pgvector, MCP Python SDK.

**Spec:** `docs/superpowers/specs/2026-08-26-domain-modularization-design.md`

## Global Constraints

- Complete `docs/superpowers/plans/2026-08-26-domain-modularization-foundation.md` first.
- Preserve every route in `backend/tests/route_contract_check.py` exactly.
- Preserve the six MCP tool names and payloads exactly.
- Move SQL and business logic mechanically; do not optimize queries or change validation messages.
- Do not change the database schema or add dependencies.
- Run every Python test and Git command on Aliyun in the `department-ai` Conda environment.
- Each task must leave `self_check` and `route_contract_check` green before commit.

---

### Task 1: Extract Shared Backend Primitives

**Files:**
- Create: `backend/app/core/__init__.py`
- Create: `backend/app/core/config.py`
- Create: `backend/app/core/database.py`
- Create: `backend/app/core/health.py`
- Create: `backend/app/core/schemas.py`
- Delete: `backend/app/config.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/schemas.py`
- Modify imports in: `backend/app/main.py`, `backend/app/mcp_server.py`, `backend/app/knowledge.py`, `backend/app/search.py`, `backend/tests/self_check.py`

**Interfaces:**
- Produces: `Settings`, `get_settings()`, `StoreError`, `NotFoundError`, `ConflictError`, `create_pool()`, `vector_literal()`, `url_health()`, `docling_health()`, `StrictModel`, `NonEmpty`, `Identifier`, `ShortText`, and `ChunkingSettings` under `app.core`.
- Consumes: Existing environment variables and Psycopg connection configuration unchanged.

- [ ] **Step 1: Add a failing import-boundary assertion**

Add to `backend/tests/self_check.py` before importing feature models:

```python
from app.core.config import PROJECT_DIR, Settings, get_settings
from app.core.database import ConflictError, NotFoundError, StoreError, vector_literal
from app.core.schemas import ChunkingSettings, Identifier, NonEmpty, ShortText, StrictModel
```

Replace the old `from app.config import PROJECT_DIR` and `from app.db import StoreError` imports. Add:

```python
assert vector_literal([0.1, 0.25]) == "[0.1,0.25]"
```

- [ ] **Step 2: Run the self-check and verify the new imports fail**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check'
```

Expected: FAIL with `ModuleNotFoundError: No module named 'app.core'`.

- [ ] **Step 3: Move configuration and shared database primitives**

Move `PROJECT_DIR`, `_load_environment`, `Settings`, and `get_settings` unchanged into `app/core/config.py`.

Move the three error classes and `create_pool` into `app/core/database.py`. Rename the old private `_vector` helper to this public shared function:

```python
def vector_literal(values: list[float]) -> str:
    return "[" + ",".join(str(value) for value in values) + "]"
```

Update every old `_vector(...)` call in `app/db.py` to `vector_literal(...)` imported from `app.core.database`.

Move `_url_health` and `_docling_health` from `main.py` into `app/core/health.py` as public `url_health` and `docling_health`. Preserve the three-second timeout and exception handling exactly; import both functions back into `main.py`.

- [ ] **Step 4: Move shared validation primitives**

Move these definitions unchanged into `app/core/schemas.py`:

```python
NonEmpty
Identifier
ShortText
StrictModel
ChunkingSettings
```

Do not move `OptionalIdentifier`; it has no callers and should be deleted. Keep domain models temporarily in `app/schemas.py`, importing the shared names from `app.core.schemas`.

- [ ] **Step 5: Update all imports and remove `app/config.py`**

Use these canonical imports everywhere:

```python
from app.core.config import Settings, get_settings
from app.core.database import ConflictError, NotFoundError, StoreError, create_pool
from app.core.schemas import ChunkingSettings, Identifier, NonEmpty, ShortText, StrictModel
```

Delete `backend/app/config.py` only after `rg 'app\.config|from app\.db import .*StoreError' backend` returns no old imports.

- [ ] **Step 6: Run backend checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check'
```

Expected: `self-check: ok` and `route-contract-check: ok`.

- [ ] **Step 7: Commit shared primitives**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app backend/tests/self_check.py && git commit -m "refactor: extract backend core primitives"'
```

### Task 2: Extract the Processes Domain

**Files:**
- Create: `backend/app/features/__init__.py`
- Create: `backend/app/features/processes/__init__.py`
- Create: `backend/app/features/processes/schemas.py`
- Create: `backend/app/features/processes/store.py`
- Create: `backend/app/features/processes/router.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/mcp_server.py`
- Modify: `backend/app/db.py`
- Modify: `backend/app/schemas.py`
- Modify: `backend/tests/self_check.py`

**Interfaces:**
- Produces: `router`, `ProcessStepInput`, `ProcessInput`, `list_processes(pool)`, `save_process(pool, process, creating)`, `delete_process(pool, process_id)`.
- Preserves: four `/api/processes` routes and MCP `process_list`.

- [ ] **Step 1: Point the self-check at the future domain model**

Replace the `ProcessInput` import with:

```python
from app.features.processes.schemas import ProcessInput
```

Run `python -m tests.self_check` on Aliyun and expect `ModuleNotFoundError`.

- [ ] **Step 2: Move process models and store functions unchanged**

Move `ProcessStepInput` and `ProcessInput` from `app/schemas.py` into `features/processes/schemas.py`.

Move these functions from `app/db.py` into `features/processes/store.py`:

```text
list_processes
save_process
delete_process
```

Import `ConflictError` and `NotFoundError` from `app.core.database` as required by the moved SQL.

- [ ] **Step 3: Create the process router**

Define `router = APIRouter(prefix="/api/processes", tags=["processes"])` and move the existing GET, POST, PUT, and DELETE handlers from `main.py` unchanged. Access the pool through `request.app.state.pool` inside this module.

- [ ] **Step 4: Register the router and update MCP**

In `main.py`:

```python
from app.features.processes.router import router as processes_router

app.include_router(processes_router)
```

In `mcp_server.py`, import `list_processes` from `app.features.processes.store`.

- [ ] **Step 5: Verify offline and live process behavior**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.live_process_check'
```

Expected: all three checks report `ok`. `live_process_check` requires the backend service to be running.

- [ ] **Step 6: Commit the processes domain**

Commit only the process feature, changed imports, and removed legacy definitions with message:

```text
refactor: extract processes domain
```

### Task 3: Extract the Catalog Domain

**Files:**
- Create: `backend/app/features/catalog/__init__.py`
- Create: `backend/app/features/catalog/schemas.py`
- Create: `backend/app/features/catalog/store.py`
- Create: `backend/app/features/catalog/router.py`
- Modify: `backend/app/main.py`, `backend/app/db.py`, `backend/app/schemas.py`

**Interfaces:**
- Produces: category/purpose schemas, `router`, `ensure_knowledge_purpose_schema`, category CRUD/order functions, purpose CRUD functions.
- Preserves: all `/api/categories` and `/api/purposes` contracts.

- [ ] **Step 1: Add catalog model imports to the self-check**

Import and instantiate `CategoryInput`, `CategoryOrderInput`, and `KnowledgePurposeInput` from `app.features.catalog.schemas`; expect the import to fail before extraction.

- [ ] **Step 2: Move catalog schemas**

Move exactly:

```text
CategoryInput
CategoryOrderInput
KnowledgePurposeInput
```

Import `ChunkingSettings`, `Identifier`, `NonEmpty`, `ShortText`, and `StrictModel` from `app.core.schemas`.

- [ ] **Step 3: Move catalog persistence**

Move `DEFAULT_PURPOSES`, `ensure_knowledge_purpose_schema`, `_purpose`, `list_purposes`, `get_purpose`, `create_purpose`, `update_purpose`, `delete_purpose`, `list_categories`, `_ensure_category_parent`, `create_category`, `update_category`, `reorder_categories`, `delete_category`, and `_category` into `features/catalog/store.py`.

Until Task 5 moves settings defaults, import `DEFAULT_SETTINGS` from `app.db` in this one temporary location and mark the import with `# removed by settings-domain task`.

- [ ] **Step 4: Create and register the catalog router**

Use one `APIRouter(tags=["catalog"])` containing the existing category and purpose paths verbatim. Register it in `main.py` and remove those handlers/imports from `main.py`.

- [ ] **Step 5: Verify and commit**

Run `self_check` and `route_contract_check` on Aliyun. Commit with:

```text
refactor: extract catalog domain
```

### Task 4: Extract the Skills Domain

**Files:**
- Create: `backend/app/features/skills/__init__.py`
- Create: `backend/app/features/skills/schemas.py`
- Create: `backend/app/features/skills/service.py`
- Create: `backend/app/features/skills/router.py`
- Delete: `backend/app/skills.py`
- Modify: `backend/app/main.py`, `backend/app/schemas.py`, `backend/tests/self_check.py`

**Interfaces:**
- Produces: `SkillInput`, `SkillResourceInput`, existing Skill service functions, and all `/api/skills` routes.
- Preserves: path traversal protection, symlink exclusion, frontmatter preservation, file-size validation, and response shapes.

- [ ] **Step 1: Redirect self-check imports and verify failure**

Change Skill service imports to `app.features.skills.service` and model imports to `app.features.skills.schemas`, then run `self_check` and expect missing-module failure.

- [ ] **Step 2: Move Skill models and service code unchanged**

Move `SkillInput` and `SkillResourceInput` into `features/skills/schemas.py`. Move the complete contents of `app/skills.py` into `features/skills/service.py`; preserve every private validation helper.

- [ ] **Step 3: Create and register the Skill router**

Move all seven Skill and resource handlers from `main.py` into `features/skills/router.py`. Keep Base64 decoding and `StoreError("技能资源内容不是有效的 Base64")` unchanged.

- [ ] **Step 4: Run checks**

Run on Aliyun:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.live_admin_check'
```

Expected: all report `ok`; the live check creates and deletes its own temporary Skill and restores settings.

- [ ] **Step 5: Delete the old module and commit**

Verify `rg 'app\.skills' backend` has no matches, delete `app/skills.py`, and commit with:

```text
refactor: extract skills domain
```

### Task 5: Extract Settings and Dashboard Aggregation

**Files:**
- Create: `backend/app/features/settings/__init__.py`
- Create: `backend/app/features/settings/schemas.py`
- Create: `backend/app/features/settings/store.py`
- Create: `backend/app/features/settings/router.py`
- Create: `backend/app/features/dashboard/__init__.py`
- Create: `backend/app/features/dashboard/router.py`
- Modify: `backend/app/main.py`, `backend/app/mcp_server.py`, `backend/app/db.py`, `backend/app/schemas.py`, `backend/app/features/catalog/store.py`

**Interfaces:**
- Produces: settings models/defaults/store/router plus cross-domain `/api/state` router.
- Preserves: settings validation messages, `/api/settings`, `/api/state`, and MCP `department_context_get`.

- [ ] **Step 1: Move settings schemas**

Move `RetrievalSettings`, `AssistantSettingsInput`, and `DepartmentSettingsInput` into `features/settings/schemas.py`; import shared `ChunkingSettings`, `NonEmpty`, and `StrictModel` from `app.core.schemas`.

- [ ] **Step 2: Move settings defaults and persistence**

Move `DEFAULT_SETTINGS`, `get_department_settings`, and `save_department_settings` into `features/settings/store.py`. Update `features/catalog/store.py` to import `DEFAULT_SETTINGS` from the new module and remove the temporary legacy import.

- [ ] **Step 3: Create settings and dashboard routers**

Move `/api/settings` GET/PUT handlers into `features/settings/router.py`.

Move `/api/state` into `features/dashboard/router.py`. Its handler must import and call the public list/get functions from the six feature domains and preserve the current JSON keys exactly:

```python
{
    "processes", "categories", "purposes", "documents",
    "skills", "settings", "services",
}
```

Import `url_health(url: str) -> bool` and `docling_health(base_url: str) -> bool` from `app.core.health` in both `main.py` and the dashboard router; do not duplicate either function.

- [ ] **Step 4: Update MCP and run checks**

Import `get_department_settings` from `features.settings.store`. Run `self_check`, `route_contract_check`, `mcp_check`, and `live_admin_check` on Aliyun.

- [ ] **Step 5: Commit**

Commit with:

```text
refactor: extract settings and dashboard domains
```

### Task 6: Extract Search

**Files:**
- Create: `backend/app/features/search/__init__.py`
- Create: `backend/app/features/search/schemas.py`
- Create: `backend/app/features/search/store.py`
- Create: `backend/app/features/search/service.py`
- Create: `backend/app/features/search/router.py`
- Delete: `backend/app/search.py`
- Modify: `backend/app/db.py`, `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/mcp_server.py`

**Interfaces:**
- Produces: `TemplateSearchInput`, `KnowledgeSearchInput`, candidate-query functions, `search_templates`, `search_knowledge`, and two REST routes.
- Temporarily consumes: document helpers from legacy `app.knowledge` and `get_document` from legacy `app.db`; Task 7 removes both temporary imports.

- [ ] **Step 1: Move search models and SQL candidates**

Move the two search input models into `features/search/schemas.py`.

Move these functions into `features/search/store.py`:

```text
vector_template_candidates
keyword_template_candidates
vector_reference_documents
keyword_reference_documents
vector_chunk_candidates
keyword_chunk_candidates
parent_chunk_contents
_search_document
_search_chunk
```

Use `vector_literal` from `app.core.database`.

- [ ] **Step 2: Move search orchestration**

Move all of `app/search.py` into `features/search/service.py`, updating store imports to the new domain. Move `rerank`, `search_keywords`, and `newer_document` from `app.knowledge` into this service because they are search-only. Keep `embed_texts` and `document_profile` temporarily imported from `app.knowledge`.

- [ ] **Step 3: Create router and update MCP**

Move `/api/search/templates` and `/api/search/knowledge` into the new router. Update MCP imports and model validation imports to the new search domain.

- [ ] **Step 4: Verify and commit**

Run `self_check`, `route_contract_check`, and `mcp_check`; commit with:

```text
refactor: extract search domain
```

### Task 7: Extract Documents and Knowledge Processing

**Files:**
- Create: `backend/app/features/documents/__init__.py`
- Create: `backend/app/features/documents/schemas.py`
- Create: `backend/app/features/documents/store.py`
- Create: `backend/app/features/documents/service.py`
- Create: `backend/app/features/documents/router.py`
- Delete: `backend/app/knowledge.py`
- Modify: `backend/app/db.py`, `backend/app/schemas.py`, `backend/app/main.py`, `backend/app/mcp_server.py`, `backend/app/features/search/service.py`, `backend/tests/self_check.py`

**Interfaces:**
- Produces: all document models, document CRUD/store functions, parsing/chunking/preview/embedding helpers, and document/knowledge-preview routes.
- Preserves: managed-file boundaries, preview cleanup, Docling calls, metadata analysis, 1024-dimensional embedding validation, and file rollback on failed database save.

- [ ] **Step 1: Move document models**

Move `KnowledgePreviewInput`, `KnowledgeChunkInput`, `KnowledgeIndexInput`, and `KnowledgeDocumentUpdate` into `features/documents/schemas.py`. Import shared primitives from `app.core.schemas`.

- [ ] **Step 2: Move document persistence**

Move into `features/documents/store.py`:

```text
_string_list
_iso
map_document
list_documents
get_document
_validate_document_links
save_document
update_document
replace_document_embeddings
delete_document
```

Use `vector_literal` from `app.core.database`.

- [ ] **Step 3: Move document processing service**

Move the remaining document-focused functions from `app.knowledge` into `features/documents/service.py`, including decode, Docling parsing, upload-path validation, chunking, metadata analysis, document profile, embeddings, and preview lifecycle.

Keep these public signatures unchanged because MCP/search consume them:

```python
def parse_document(content: bytes, file_name: str, mime_type: str, docling_base_url: str) -> str: ...
def uploaded_document_path(file_path: str, maximum_bytes: int) -> Path: ...
def document_profile(document: dict[str, Any]) -> str: ...
def embed_texts(texts: list[str], base_url: str, api_key: str, model: str) -> list[list[float]]: ...
```

Update `features/search/service.py` to import `document_profile` and `embed_texts` from this service and `get_document` from this store. Verify `app.knowledge` and legacy `app.db` are no longer imported by search.

- [ ] **Step 4: Move all document routes**

Move document CRUD, source download, preview, rechunk, preview delete, index, and reindex handlers into `features/documents/router.py`. Preserve `_managed_source` as a private router helper and preserve the file move/rollback `try/except` exactly.

- [ ] **Step 5: Update MCP and lifecycle imports**

Update `document_read` to import `parse_document` and `uploaded_document_path` from the document service. Update `main.lifespan` to import `cleanup_previews` from the new service.

- [ ] **Step 6: Run offline and online knowledge checks**

Run `self_check`, `route_contract_check`, and `mcp_check`. With an explicitly selected small managed `.docx`, run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.live_preview_check /absolute/path/to/test.docx'
```

Expected: preview, parent-child rechunk, index, document retrieval, knowledge search, and cleanup all succeed. Do not search for or move a large document automatically.

- [ ] **Step 7: Remove legacy modules and commit**

Delete `app/knowledge.py`. Delete `app/schemas.py` and `app/db.py` only after:

```bash
rg 'app\.(db|schemas|knowledge)' backend
```

returns no production/test imports. Commit with:

```text
refactor: extract documents domain
```

### Task 8: Enforce Backend Boundaries and Finish Composition

**Files:**
- Create: `backend/tests/module_boundaries_check.py`
- Modify: `backend/app/main.py`
- Modify: `backend/tests/self_check.py`

**Interfaces:**
- Consumes: final `app.core` and `app.features` layout.
- Produces: an automated check that `core` never imports `features` and `main.py` contains no `/api/` business decorators.

- [ ] **Step 1: Create the boundary check**

Use Python `ast` and `pathlib` only. The check must:

```python
assert not any("app.features" in source for source in core_sources)
assert '@app.get("/api/' not in main_source
assert '@app.post("/api/' not in main_source
assert '@app.put("/api/' not in main_source
assert '@app.delete("/api/' not in main_source
```

Also assert that each domain directory contains the files listed in the approved design. Print `backend-module-boundaries-check: ok` on success.

- [ ] **Step 2: Run it and fix only real boundary violations**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check'
```

Expected: PASS. If it fails, move the violating dependency to the owning feature or a genuinely shared core module; do not weaken the assertion.

- [ ] **Step 3: Run the complete backend suite**

Run on Aliyun:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check && conda run --no-capture-output -n department-ai python -m tests.mcp_check && conda run --no-capture-output -n department-ai python -m tests.live_admin_check && conda run --no-capture-output -n department-ai python -m tests.live_process_check'
```

Expected: every check reports `ok`.

- [ ] **Step 4: Inspect final module sizes and imports**

Run read-only checks on Aliyun:

```bash
rg -n '^@app\.(get|post|put|delete)\("/api/' backend/app/main.py
rg -n 'app\.(db|schemas|knowledge|skills|search|config)' backend
```

Expected: no matches.

- [ ] **Step 5: Commit the final backend guard**

Commit with:

```text
test: enforce backend module boundaries
```
