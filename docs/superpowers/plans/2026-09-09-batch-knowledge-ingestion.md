# Batch Knowledge Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fast multi-file knowledge ingestion path that inherits an explicitly selected directory, asks AI for a directory only on homepage uploads, and lets users review and publish valid items in one batch.

**Architecture:** Keep the existing single-file preview/analyze/rechunk/index endpoints and four-step editor. A new browser-managed batch coordinator calls those endpoints per file with preparation concurrency 2 and serial final indexing; temporary previews remain the recovery boundary. Existing nullable `category_id` and document status provide unclassified and publication semantics, so no new database tables, worker service, or dependencies are introduced.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic, PostgreSQL/pgvector, browser ES modules, native HTML dialog/file input, CSS, Node assertion/JSDOM checks.

**Spec:** `docs/superpowers/specs/2026-09-09-batch-knowledge-ingestion-design.md`

## Global Constraints

- Read and edit ordinary files through `/Volumes/DepartmentKnowledgeBase/department-ai`; run Python, Node, Git, build, test, database, and service commands only through `ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && ...'`.
- Use `/root/anaconda3/envs/department-ai/bin/python` for backend checks.
- Preserve the existing single-file four-step flow and all existing REST/MCP contracts; the only REST response extension is optional `suggestedCategoryId` on metadata analysis.
- `suggestCategory` defaults to `false`; only homepage uploads send `suggestCategory=true`.
- Directory-inside uploads keep their entry directory and never ask AI to replace it.
- An empty directory is valid and does not prevent indexing or publication.
- Preparation concurrency is exactly 2; final indexing is serial.
- Do not add database tables, migrations, dependencies, a persistent job runner, multi-knowledge-base entities, permissions, tags, or index versions.
- Keep `backend/app/main.py` and `frontend/js/main.js` within their composition-only architecture boundaries.
- Keep new frontend business logic inside `frontend/js/features/knowledge/`; do not move it into `core` or `ui`.
- Do not modify or commit the existing user-owned changes in `deploy-server.sh`.
- Do not push, deploy, restart services, or alter production data as part of this plan.

---

### Task 1: Optional AI directory recommendation

**Files:**
- Modify: `backend/app/features/documents/service.py:258-340`
- Modify: `backend/app/features/documents/router.py:1-175`
- Modify: `backend/tests/knowledge_ingestion_check.py`
- Modify: `backend/README.md:70-105`

**Interfaces:**
- Consumes: flat category dictionaries returned by `list_categories(pool)` with `id`, `parentId`, and `name`.
- Produces: `analyze_metadata(..., categories: list[dict[str, Any]] | None = None) -> dict[str, Any]`; `POST /api/knowledge/previews/{preview_id}/analyze?suggestCategory=true`; metadata field `suggestedCategoryId: str` where an empty string means no recommendation.

- [ ] **Step 1: Extend the backend ingestion check and verify it fails**

Add two captured-request cases to `backend/tests/knowledge_ingestion_check.py`:

```python
categories = [
    {"id": "product", "parentId": None, "name": "产品知识"},
    {"id": "crm", "parentId": "product", "name": "CRM"},
]

with patch("app.features.documents.service._send", fake_send):
    without_category = analyze_metadata(
        "合同.docx", "甲方：____ 乙方：____", purposes,
        "https://metadata.example", "key", "model",
    )
    with_category = analyze_metadata(
        "合同.docx", "甲方：____ 乙方：____", purposes,
        "https://metadata.example", "key", "model", categories=categories,
    )

assert without_category["suggestedCategoryId"] == ""
assert "可选知识目录" not in captured_bodies[0]
assert with_category["suggestedCategoryId"] == "crm"
assert "产品知识 / CRM" in captured_bodies[1]
```

Make `fake_send` return `suggestedCategoryId: "crm"` in the second response and retain the existing purpose assertions.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && /root/anaconda3/envs/department-ai/bin/python -m tests.knowledge_ingestion_check'
```

Expected: FAIL because `analyze_metadata` does not accept `categories` and does not return `suggestedCategoryId`.

- [ ] **Step 2: Implement validated category choices in the metadata service**

Add a small path builder next to `analyze_metadata`:

```python
def _category_choices(categories: list[dict[str, Any]]) -> list[dict[str, str]]:
    by_id = {str(item["id"]): item for item in categories}

    def path(item: dict[str, Any]) -> str:
        names = [str(item["name"])]
        parent_id = item.get("parentId")
        visited = {str(item["id"])}
        while parent_id and str(parent_id) in by_id and str(parent_id) not in visited:
            parent = by_id[str(parent_id)]
            visited.add(str(parent_id))
            names.append(str(parent["name"]))
            parent_id = parent.get("parentId")
        return " / ".join(reversed(names))

    return [{"id": str(item["id"]), "path": path(item)} for item in categories]
```

Extend the signature without breaking current positional callers:

```python
def analyze_metadata(
    file_name: str,
    text: str,
    purposes: list[dict[str, Any]],
    base_url: str,
    api_key: str,
    model: str,
    categories: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
```

Only when `categories` is non-empty, append `suggestedCategoryId` to the requested JSON fields and include `可选知识目录：...` in the user message. Validate the model result against the supplied IDs:

```python
category_ids = {str(category["id"]) for category in categories or []}
suggested_category = string("suggestedCategoryId", 100)

return {
    "suggestedCategoryId": suggested_category if suggested_category in category_ids else "",
    "suggestedPurposeId": suggested_purpose if suggested_purpose in purpose_ids else "",
    # existing metadata fields unchanged
}
```

- [ ] **Step 3: Add the optional query parameter at the route boundary**

Import `Annotated`, `Query`, and `list_categories`, then change the route signature and call:

```python
@router.post("/api/knowledge/previews/{preview_id}/analyze")
def knowledge_analyze(
    preview_id: str,
    request: Request,
    suggest_category: Annotated[bool, Query(alias="suggestCategory")] = False,
) -> dict[str, Any]:
    runtime = _settings(request)
    preview = read_preview(runtime.data_dir, preview_id)
    metadata = analyze_metadata(
        preview["fileName"],
        preview["parsedText"],
        list_purposes(_pool(request)),
        runtime.metadata_base_url,
        runtime.metadata_api_key,
        runtime.metadata_model,
        categories=list_categories(_pool(request)) if suggest_category else None,
    )
    return {"id": preview_id, "metadata": metadata}
```

- [ ] **Step 4: Run focused backend checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && /root/anaconda3/envs/department-ai/bin/python -m tests.knowledge_ingestion_check && /root/anaconda3/envs/department-ai/bin/python -m tests.route_contract_check && /root/anaconda3/envs/department-ai/bin/python -m tests.self_check'
```

Expected: all three commands print their `ok` completion line and exit 0.

- [ ] **Step 5: Document and commit the compatible endpoint extension**

Update the analysis endpoint entry in `backend/README.md` to state that `suggestCategory=true` is used only for homepage uploads and that the response may contain `suggestedCategoryId`.

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app/features/documents/service.py backend/app/features/documents/router.py backend/tests/knowledge_ingestion_check.py backend/README.md && git commit -m "feat: suggest directories for homepage ingestion"'
```

Expected: one commit containing only the four listed files.

---

### Task 2: Avoid Embedding calls for directory-only and status-only edits

**Files:**
- Create: `backend/tests/document_update_check.py`
- Modify: `backend/app/features/documents/router.py:75-105`
- Modify: `backend/app/features/documents/store.py:215-260`

**Interfaces:**
- Consumes: `document_profile(current)` and `document_profile(updated)` from the existing document service.
- Produces: `update_document(..., document_embedding: list[float] | None, embedding_model: str | None) -> None`; `None` preserves the stored document vector and model.

- [ ] **Step 1: Write a route-level regression check**

Create `backend/tests/document_update_check.py` with a complete editable document fixture and patched dependencies. The two essential assertions are:

```python
from types import SimpleNamespace
from unittest.mock import patch

from app.features.documents.router import document_update
from app.features.documents.schemas import KnowledgeDocumentUpdate


def editable(category_id: str | None, title: str = "网络手册") -> KnowledgeDocumentUpdate:
    return KnowledgeDocumentUpdate.model_validate({
        "title": title,
        "categoryId": category_id,
        "status": "effective",
        "documentType": "手册",
        "keywords": ["网络"],
        "outline": ["第一章"],
        "templateFamily": "",
        "templateVariant": "",
        "version": "V1.0",
        "applicableScenario": "运维",
        "summary": "网络运维手册",
    })
```

Build `current` with the same fields plus `id`, `purposeName`, `parsedText`, `isGenerationTemplate`, and `categoryId="old"`. Use `SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=object(), settings=object())))` as the request. Patch `get_document`, `get_department_settings`, `embed_texts`, and `update_document`.

Assert that changing only `categoryId` does not call `embed_texts` and passes `None, None` to `update_document`. In a second case, change `title`, return `[[0.1] * 1024]` from `embed_texts`, and assert that one embedding is passed to the store.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && /root/anaconda3/envs/department-ai/bin/python -m tests.document_update_check'
```

Expected: FAIL because the route always calls Embedding and the store does not accept nullable vector inputs.

- [ ] **Step 2: Compare document profiles before requesting Embedding**

In `document_update`, merge the current document and update first, compare profiles, and only load model settings when the profile changed:

```python
document = {**current, **data}
embedding = None
embedding_model = None
if document_profile(current) != document_profile(document):
    settings = get_department_settings(_pool(request))
    embedding_model = settings["embeddingModel"]
    embedding = embed_texts(
        [document_profile(document)],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        embedding_model,
    )[0]
update_document(_pool(request), document_id, data, embedding, embedding_model)
```

Do not include `categoryId` or `status` in `document_profile`.

- [ ] **Step 3: Preserve the current vector when no replacement is supplied**

Change `update_document` arguments to nullable types and use `COALESCE` only for the two vector columns:

```sql
document_embedding = COALESCE(%s::vector, document_embedding),
embedding_model = COALESCE(%s, embedding_model),
updated_at = now()
```

Keep validation and all other updated columns unchanged.

- [ ] **Step 4: Run backend regression checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && /root/anaconda3/envs/department-ai/bin/python -m tests.document_update_check && /root/anaconda3/envs/department-ai/bin/python -m tests.self_check && /root/anaconda3/envs/department-ai/bin/python -m tests.route_contract_check'
```

Expected: all checks exit 0; the new check proves one no-Embedding path and one Embedding path.

- [ ] **Step 5: Commit the focused optimization**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app/features/documents/router.py backend/app/features/documents/store.py backend/tests/document_update_check.py && git commit -m "perf: skip embeddings for classification edits"'
```

Expected: one backend-only commit.

---

### Task 3: Extract a shared knowledge-ingestion HTTP client

**Files:**
- Create: `frontend/js/features/knowledge/upload-api.js`
- Create: `frontend/tests/upload_api_check.mjs`
- Modify: `frontend/js/features/knowledge/upload.js:1-55,315-470`
- Modify: `frontend/tests/knowledge_upload_check.mjs`

**Interfaces:**
- Produces: `previewKnowledge(file: File)`, `analyzeKnowledge(previewId: string, options?: {suggestCategory?: boolean})`, `rechunkKnowledge(previewId: string, settings: object)`, `indexKnowledge(previewId: string, data: object)`, and `deleteKnowledgePreview(previewId: string)`.
- Consumed by: the existing single-file `upload.js` and Task 5's batch uploader.

- [ ] **Step 1: Write the client contract check**

Create `frontend/tests/upload_api_check.mjs`. Call `createDom` with a minimal valid application state so JSDOM installs `File` and `FileReader`, replace `fetch` with a request-capturing stub, import the new module, and assert exact URLs and bodies:

```javascript
await analyzeKnowledge('preview/一')
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/analyze')

await analyzeKnowledge('preview/一', { suggestCategory: true })
assert.equal(requests.at(-1).url, '/api/knowledge/previews/preview%2F%E4%B8%80/analyze?suggestCategory=true')

const file = new dom.window.File(['ABC'], '合同.docx', { type: 'application/test' })
await previewKnowledge(file)
assert.deepEqual(JSON.parse(requests.at(-1).body), {
  fileName: '合同.docx', mimeType: 'application/test', fileBase64: 'QUJD',
})
```

Also assert that `indexKnowledge('preview/一', { title: '合同' })` sends the body without a `previewId` property and that delete uses an encoded preview ID.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/upload_api_check.mjs'
```

Expected: FAIL because `upload-api.js` does not exist.

- [ ] **Step 2: Implement the minimal shared client**

Move the existing `FileReader` Base64 conversion and request wrappers from `upload.js` into `upload-api.js`:

```javascript
export async function previewKnowledge(file) {
  return request('/api/knowledge/preview', {
    method: 'POST',
    body: {
      fileName: file.name,
      mimeType: file.type || 'application/octet-stream',
      fileBase64: await fileToBase64(file),
    },
  })
}

export function analyzeKnowledge(previewId, { suggestCategory = false } = {}) {
  const suffix = suggestCategory ? '?suggestCategory=true' : ''
  return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/analyze${suffix}`, { method: 'POST' })
}
```

Implement the other three wrappers with the same encoded paths and request bodies currently used by `upload.js`.

- [ ] **Step 3: Switch the single-file flow to the shared client without behavior changes**

Import the five functions into `upload.js`, delete the local wrappers and `fileToBase64`, and replace:

```javascript
const fileBase64 = await fileToBase64(file)
const preview = await previewKnowledge({ fileName: file.name, mimeType: file.type, fileBase64 })
```

with:

```javascript
const preview = await previewKnowledge(file)
```

Keep single-file analysis as `analyzeKnowledge(workflow.preview.id)` so it does not request a directory suggestion.

- [ ] **Step 4: Run client and existing single-file checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/upload_api_check.mjs && node frontend/tests/knowledge_upload_check.mjs && node frontend/tests/module_boundaries_check.mjs'
```

Expected: all three checks print `ok` and exit 0; existing single-file request bodies remain unchanged.

- [ ] **Step 5: Commit the behavior-preserving extraction**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/upload-api.js frontend/js/features/knowledge/upload.js frontend/tests/upload_api_check.mjs frontend/tests/knowledge_upload_check.mjs && git commit -m "refactor: share knowledge ingestion requests"'
```

Expected: one frontend-only extraction commit.

---

### Task 4: Implement deterministic batch task state and bounded concurrency

**Files:**
- Create: `frontend/js/features/knowledge/upload-batch-state.js`
- Create: `frontend/tests/batch_upload_state_check.mjs`

**Interfaces:**
- Produces: `BATCH_PREPARE_CONCURRENCY`, `createBatchItems(files, entryCategoryId, idFactory?)`, `mergeSuggestion(item, suggestion, purposes, categories)`, `evaluateBatchItem(item, purposes)`, and `runBatchPool(items, worker, concurrency?)`.
- Consumed by: Task 5's `upload-batch.js`.

- [ ] **Step 1: Write pure state and concurrency checks**

Create `frontend/tests/batch_upload_state_check.mjs` with three files and deterministic IDs:

```javascript
const items = createBatchItems(files, 'contracts', index => `knowledge-test-${index}`)
assert.deepEqual(items.map(item => item.metadata.categoryId), ['contracts', 'contracts', 'contracts'])
assert.deepEqual(items.map(item => item.status), ['waiting', 'waiting', 'waiting'])
```

Verify homepage suggestion versus directory inheritance:

```javascript
const homepage = createBatchItems([files[0]], '', () => 'knowledge-home')[0]
mergeSuggestion(homepage, {
  title: 'AI 合同', suggestedPurposeId: 'reference-knowledge', suggestedCategoryId: 'contracts',
}, purposes, categories)
assert.equal(homepage.metadata.categoryId, 'contracts')

const inside = createBatchItems([files[0]], 'manual', () => 'knowledge-inside')[0]
mergeSuggestion(inside, {
  title: 'AI 合同', suggestedPurposeId: 'reference-knowledge', suggestedCategoryId: 'contracts',
}, purposes, categories)
assert.equal(inside.metadata.categoryId, 'manual')
```

Verify that a valid reference item with one enabled chunk becomes `ready` and selected, a template without `templateFamily` becomes `needs-review` and unselected, and an empty category does not block readiness.

Measure active workers around an awaited gate and assert `maximumActive === 2`. Before throwing for the second item, set `item.retryAction='prepare'`; assert the third still runs while the failed item becomes `failed`, retains `retryAction='prepare'`, and contains the error message.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/batch_upload_state_check.mjs'
```

Expected: FAIL because the state module does not exist.

- [ ] **Step 2: Implement batch item construction and suggestion merging**

Use the exact item shape:

```javascript
{
  id,
  file,
  entryCategoryId,
  preview: null,
  metadata: {
    id,
    title: file.name.replace(/\.[^.]+$/, ''),
    purposeId: '',
    documentType: '',
    keywords: [],
    outline: [],
    categoryId: entryCategoryId,
    status: 'effective',
    summary: '',
    templateFamily: '',
    templateVariant: '',
    version: 'V1.0',
    applicableScenario: '',
  },
  chunks: [],
  status: 'waiting',
  error: '',
  retryAction: '',
  selected: false,
}
```

`mergeSuggestion` must only set non-empty suggestion fields, validate purpose and category IDs against current state, and refuse to replace `categoryId` when `entryCategoryId` is non-empty.

- [ ] **Step 3: Implement deterministic readiness rules**

`evaluateBatchItem` returns the mutated item. It sets `ready`, clears `retryAction`, and sets `selected=true` only when title, known purpose, required template family, and required enabled chunks are present. It sets `needs-review`, `selected=false`, and a specific Chinese error for the first missing requirement. It never treats `categoryId === ''` as an error.

```javascript
const enabledChunks = item.chunks.filter(chunk => chunk.enabled)
if (!item.metadata.title.trim()) return review(item, '请确认文档标题')
if (!purpose) return review(item, '请确认文档用途')
if (purpose.canGenerateTemplate && !item.metadata.templateFamily.trim()) {
  return review(item, '请填写模板家族')
}
if (purpose.chunkBody && enabledChunks.length === 0) {
  return review(item, '至少保留一个有效正文分块')
}
item.status = 'ready'
item.error = ''
item.retryAction = ''
item.selected = true
return item
```

- [ ] **Step 4: Implement the two-worker pool with per-item isolation**

```javascript
export const BATCH_PREPARE_CONCURRENCY = 2

export async function runBatchPool(items, worker, concurrency = BATCH_PREPARE_CONCURRENCY) {
  let cursor = 0
  async function next() {
    while (cursor < items.length) {
      const item = items[cursor]
      cursor += 1
      try {
        await worker(item)
      } catch (error) {
        item.status = 'failed'
        item.error = error instanceof Error ? error.message : String(error)
        item.retryAction ||= 'prepare'
        item.selected = false
      }
    }
  }
  await Promise.all(Array.from({ length: Math.min(concurrency, items.length) }, next))
}
```

- [ ] **Step 5: Run and commit the pure batch engine**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/batch_upload_state_check.mjs && git add frontend/js/features/knowledge/upload-batch-state.js frontend/tests/batch_upload_state_check.mjs && git commit -m "feat: add batch ingestion state engine"'
```

Expected: the check prints `batch-upload-state-check: ok`; the commit contains two files.

---

### Task 5: Add the batch uploader, centralized review, and inline directory creation

**Files:**
- Create: `frontend/js/features/knowledge/upload-batch.js`
- Create: `frontend/tests/batch_upload_check.mjs`
- Modify: `frontend/js/features/knowledge/upload.js`
- Modify: `frontend/js/features/knowledge/upload-metadata.js`
- Modify: `frontend/js/features/knowledge/categories.js`
- Modify: `frontend/css/features.css`
- Modify: `frontend/css/responsive.css`

**Interfaces:**
- Consumes: Task 3's shared HTTP client and Task 4's state functions.
- Produces: `openBatchKnowledgeUpload(files: File[], renderPage: Function, options: {categoryId: string})`; `createCategory(data: {name: string, parentId: string | null})`; an inline category creator shared by single and batch metadata review.

- [ ] **Step 1: Write the end-to-end browser-DOM check**

Create `frontend/tests/batch_upload_check.mjs` with the existing `createDom` helper, two purposes, two categories, and mocked responses keyed by uploaded file name. Cover these exact behaviors:

```javascript
setActiveCategory('contracts')
document.querySelector('#page-action').click()
attachFiles(['合同A.docx', '合同B.docx'])
document.querySelector('#parse-document').click()

await waitFor(() => document.querySelectorAll('.batch-upload-row').length === 2)
assert.ok(requests.filter(item => item.url.includes('/analyze')).every(item => !item.url.includes('suggestCategory=true')))
assert.ok([...document.querySelectorAll('[data-batch-category]')].every(select => select.value === 'contracts'))
```

Repeat from `setActiveCategory('')` and assert that analysis URLs contain `?suggestCategory=true` and valid `suggestedCategoryId` values populate the category selects.

Make one AI request fail and assert its row says `需要确认`, is not checked, retains its parsed preview, and exposes `重试分析`. Assert valid rows say `可入库` and are checked. Click the batch confirmation button and assert only checked ready rows issue serial `/index` requests. Make one index fail and assert successful rows become locked `已入库` while the failed row exposes `重试入库`.

Open one row's detail, change its purpose, verify rechunk is requested when the new purpose has `chunkBody=true`, save the detail, and confirm list state is preserved. Open inline directory creation, POST `{name, parentId}`, and assert the created directory becomes selected. Close the batch dialog and assert every non-completed preview is deleted exactly once.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/batch_upload_check.mjs'
```

Expected: FAIL because the batch dialog and multi-file branch do not exist.

- [ ] **Step 2: Add a reusable directory creation operation and inline form**

In `categories.js`, import `replaceState`, export the data operation, and reuse it from the existing editor's create branch:

```javascript
export async function createCategory(data) {
  const result = await request('/api/categories', { method: 'POST', body: data })
  replaceState({ ...state, categories: [...state.categories, result.category] })
  return result.category
}
```

In `upload-metadata.js`, render a `+ 新建目录` button beside `#document-category` plus a hidden inline form with `#upload-category-name`, `#upload-category-parent`, save, cancel, and an inline error node. Export `bindInlineCategoryCreator(onCreated)`; on success it rebuilds the category select options, selects the new ID, calls `onCreated(category)`, and returns focus to `#document-category`. The single-file upload binds it with a callback that only keeps the selected category.

- [ ] **Step 3: Route multiple selected files into the batch flow**

Set `multiple` on `#knowledge-file`. In the parse handler, branch before calling the single-file preview endpoint:

```javascript
const files = [...$('#knowledge-file').files]
if (files.length > 1) {
  workflow.disposed = true
  workflow.generation += 1
  await currentDialog.close()
  openBatchKnowledgeUpload(files, renderPage, { categoryId: activeCategory })
  return
}
const file = files[0]
```

Keep a one-file selection on the existing four-step path.

- [ ] **Step 4: Implement batch preparation and review rendering**

In `upload-batch.js`, build items with `createBatchItems` and run preparation through `runBatchPool`. Split retryable stages into these exact helpers:

```javascript
function chunkSettingsFor(purpose) {
  return purpose.inheritChunking
    ? state.settings.chunking
    : purpose.chunkSettings || state.settings.chunking
}

async function rechunkThenEvaluate(item) {
  const purpose = state.purposes.find(value => value.id === item.metadata.purposeId)
  if (!purpose) {
    evaluateBatchItem(item, state.purposes)
    render()
    return
  }
  if (!purpose.chunkBody) {
    item.chunks = []
    evaluateBatchItem(item, state.purposes)
    render()
    return
  }
  item.retryAction = 'rechunk'
  try {
    const result = await rechunkKnowledge(item.preview.id, chunkSettingsFor(purpose))
    item.chunks = result.chunks
    evaluateBatchItem(item, state.purposes)
  } catch (error) {
    item.status = 'needs-review'
    item.error = `分块失败：${error.message}`
    item.selected = false
  }
  render()
}

async function analyzeThenPrepareIndex(item) {
  item.retryAction = 'analyze'
  item.status = 'analyzing'
  render()
  try {
    const result = await analyzeKnowledge(item.preview.id, {
      suggestCategory: item.entryCategoryId === '',
    })
    mergeSuggestion(item, result.metadata, state.purposes, state.categories)
  } catch (error) {
    item.status = 'needs-review'
    item.error = `AI 分析失败：${error.message}`
    item.retryAction = 'analyze'
    item.selected = false
    render()
    return
  }
  await rechunkThenEvaluate(item)
}

async function prepare(item) {
  item.retryAction = 'prepare'
  item.status = 'parsing'
  render()
  try {
    item.preview = await previewKnowledge(item.file)
  } catch (error) {
    item.status = 'failed'
    item.error = `正文解析失败：${error.message}`
    item.selected = false
    render()
    return
  }
  await analyzeThenPrepareIndex(item)
}
```

Render a summary, filters for all/needs-review/failed, a row per item, batch directory and purpose actions, and custom in-dialog buttons. Give the summary `aria-live="polite"`; associate row errors with their file controls; restore focus to the originating row after closing detail. Use text labels in addition to status colors. Keep the standard dialog save button hidden because partial success must leave the batch dialog open.

Apply bulk directory changes directly because they do not invalidate parsing or chunks. Apply bulk purpose changes through this rule:

```javascript
for (const item of selectedEditableItems()) {
  if (item.metadata.purposeId === purposeId) continue
  item.metadata.purposeId = purposeId
  item.chunks = []
  item.selected = false
  item.status = 'needs-review'
  item.error = '用途已修改，请重新生成索引预览'
  item.retryAction = purpose.chunkBody ? 'rechunk' : ''
  if (!purpose.chunkBody) evaluateBatchItem(item, state.purposes)
}
```

Removing a non-processing item first deletes its temporary preview when present, then removes the item from the in-memory list. A delete failure keeps the row and displays the cleanup error; it must not silently orphan a preview.

- [ ] **Step 5: Implement single-item detail review and retries**

Render one detail panel at a time inside the same dialog, using `metadataFormHtml`, `chunkPanelHtml`, `renderChunkPreview`, and existing collect/validation helpers. Saving the detail copies the form values into `item.metadata`; if the purpose's chunk behavior or resolved chunk settings changed, call `rechunkKnowledge` or clear chunks before `evaluateBatchItem`.

Retry rules use `retryAction` so each failure resumes from the correct stage:

```javascript
if (item.retryAction === 'prepare') await prepare(item)
else if (item.retryAction === 'analyze') await analyzeThenPrepareIndex(item)
else if (item.retryAction === 'rechunk') await rechunkThenEvaluate(item)
else if (item.retryAction === 'index') await indexOne(item)
```

Do not retry completed items. Disable file removal while that item is in `parsing`, `analyzing`, or `indexing`.

- [ ] **Step 6: Implement serial partial-success indexing and cleanup**

Implement `indexOne` once and use it for both the serial first attempt and retry. Define the page refresh locally because `upload.js` must not import its batch consumer:

```javascript
async function indexOne(item) {
  item.status = 'indexing'
  item.retryAction = 'index'
  render()
  try {
    await indexKnowledge(item.preview.id, { ...item.metadata, chunks: item.chunks })
    item.preview = null
    item.status = 'completed'
    item.selected = false
    item.error = ''
    item.retryAction = ''
  } catch (error) {
    item.status = 'failed'
    item.selected = false
    item.error = `入库失败：${error.message}`
  }
  render()
}

async function refreshKnowledgePage() {
  replaceState(await request('/api/state'))
  renderPage()
}
```

When the user clicks `确认并入库 N 份`, snapshot items where `selected && status === 'ready'`, execute `for (const item of selected) await indexOne(item)`, then call `refreshKnowledgePage()`. This is the required serial final-indexing behavior.

On dialog close, mark the coordinator disposed, prevent late responses from mutating DOM, and call `deleteKnowledgePreview` once for every remaining `item.preview?.id`. If processing is active, intercept close and ask for confirmation before cleanup.

- [ ] **Step 7: Add focused responsive styles**

Add `.batch-upload-summary`, `.batch-upload-toolbar`, `.batch-upload-list`, `.batch-upload-row`, `.batch-upload-status`, `.batch-upload-detail`, and `.inline-category-creator` rules to `features.css`. Use existing colors, spacing, controls, card radii, and high-opacity content surfaces. Add a `max-width: 900px` card layout and a `max-width: 620px` single-column action layout to `responsive.css`; do not introduce horizontal page scrolling.

- [ ] **Step 8: Run frontend checks and commit the complete batch path**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/batch_upload_check.mjs && node frontend/tests/knowledge_upload_check.mjs && node frontend/tests/upload_api_check.mjs && node frontend/tests/batch_upload_state_check.mjs && node frontend/tests/module_boundaries_check.mjs'
```

Expected: all five checks print `ok`; one-file behavior remains covered by `knowledge_upload_check.mjs`.

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/upload-batch.js frontend/js/features/knowledge/upload.js frontend/js/features/knowledge/upload-metadata.js frontend/js/features/knowledge/categories.js frontend/tests/batch_upload_check.mjs frontend/css/features.css frontend/css/responsive.css && git commit -m "feat: add reviewed batch knowledge ingestion"'
```

Expected: one batch UI commit; `deploy-server.sh` remains unstaged.

---

### Task 6: Add system views and complete regression verification

**Files:**
- Create: `frontend/tests/knowledge_views_check.mjs`
- Modify: `frontend/js/features/knowledge/categories.js`
- Modify: `frontend/js/features/knowledge/index.js`
- Modify: `frontend/css/features.css`
- Modify: `frontend/css/responsive.css`
- Modify: `frontend/tests/css_contract_check.mjs`
- Modify: `frontend/tests/premium_ui_check.mjs`
- Modify: `frontend/DESIGN.md`

**Interfaces:**
- Produces: `activeKnowledgeView`, `setActiveKnowledgeView(view)`, `systemViewRows()`, and `filterKnowledgeDocuments(documents)` in the knowledge feature domain.
- Consumes: the existing state document fields `categoryId` and `status`.

- [ ] **Step 1: Write the system-view behavior check**

Create `frontend/tests/knowledge_views_check.mjs` with unclassified effective, categorized draft, categorized effective, and obsolete fixtures. Assert:

```javascript
setActiveKnowledgeView('unclassified')
assert.deepEqual(filterKnowledgeDocuments(documents).map(item => item.id), ['unclassified'])

setActiveKnowledgeView('draft')
assert.deepEqual(filterKnowledgeDocuments(documents).map(item => item.id), ['draft'])

setActiveKnowledgeView('published')
assert.deepEqual(filterKnowledgeDocuments(documents).map(item => item.id), ['unclassified', 'published'])
```

Render the knowledge page and assert that system buttons show exact counts, selecting a real directory resets the system view to `all`, selecting a system view clears `activeCategory`, and launching upload from a system view sends an empty entry category.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/knowledge_views_check.mjs'
```

Expected: FAIL because system views are not implemented.

- [ ] **Step 2: Implement mutually exclusive directory and system navigation state**

In `categories.js`, keep `activeCategory` and add `activeKnowledgeView = 'all'`. Use these exact filters:

```javascript
const systemFilters = {
  all: () => true,
  unclassified: item => !item.categoryId,
  draft: item => item.status === 'draft',
  published: item => item.status === 'effective',
  obsolete: item => item.status === 'obsolete',
}

export function systemViewRows(documents = state.documents) {
  return [
    { id: 'all', label: '全部文档', count: documents.length },
    { id: 'unclassified', label: '待整理', count: documents.filter(systemFilters.unclassified).length },
    { id: 'draft', label: '草稿', count: documents.filter(systemFilters.draft).length },
    { id: 'published', label: '已发布', count: documents.filter(systemFilters.published).length },
    { id: 'obsolete', label: '已废止', count: documents.filter(systemFilters.obsolete).length },
  ]
}
```

`setActiveCategory(id)` must set `activeKnowledgeView='all'`. `setActiveKnowledgeView(view)` must validate the key and set `activeCategory=''`. `filterKnowledgeDocuments` first applies the active system filter, then applies the selected directory and descendants only when `activeCategory` is non-empty.

- [ ] **Step 3: Render system views separately from real directories**

In `index.js`, render this order in the category panel:

```text
系统视图
全部文档
待整理
草稿
已发布
已废止

知识目录
<real category tree>
```

Use buttons with `data-knowledge-view`. Keep the `+ 目录` action attached only to the real-directory heading. Derive the section heading and count from `filterKnowledgeDocuments(state.documents)`. The upload handler continues to call `openKnowledgeUpload(renderPage)`; system view selection has already cleared `activeCategory`, so homepage behavior is automatic.

- [ ] **Step 4: Add system-view styling and durable design checks**

Style `.knowledge-system-views`, `.knowledge-system-view`, and `.knowledge-directory-heading` as restrained navigation controls distinct from category tree indentation. Extend `css_contract_check.mjs` to require responsive batch layout and the system-view classes. Extend `premium_ui_check.mjs` to click `待整理`, assert only null-category documents render, and assert the upload action starts without a selected directory.

Update the knowledge rule in `frontend/DESIGN.md` to include:

```markdown
- 知识库：真实目录只负责人工浏览；“待整理、草稿、已发布、已废止”属于独立系统筛选。目录内上传继承当前目录，首页上传才请求 AI 推荐目录。单文件保留四步精细审核，多文件使用集中审核和部分成功模型。
```

- [ ] **Step 5: Run every backend and frontend automated check**

Run on Aliyun:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && /root/anaconda3/envs/department-ai/bin/python -m tests.knowledge_ingestion_check && /root/anaconda3/envs/department-ai/bin/python -m tests.document_update_check && /root/anaconda3/envs/department-ai/bin/python -m tests.self_check && /root/anaconda3/envs/department-ai/bin/python -m tests.route_contract_check && /root/anaconda3/envs/department-ai/bin/python -m tests.module_boundaries_check'
```

Expected: every backend check prints `ok` and exits 0.

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && node frontend/tests/core_modules_check.mjs && node frontend/tests/upload_api_check.mjs && node frontend/tests/batch_upload_state_check.mjs && node frontend/tests/knowledge_upload_check.mjs && node frontend/tests/batch_upload_check.mjs && node frontend/tests/knowledge_views_check.mjs && node frontend/tests/css_contract_check.mjs && node frontend/tests/module_boundaries_check.mjs && node frontend/tests/premium_ui_check.mjs && node frontend/tests/settings_ui_check.mjs'
```

Expected: every frontend check prints `ok` and exits 0.

- [ ] **Step 6: Perform browser acceptance against the running Aliyun service**

Use a temporary mixed batch containing one plain reference text, one blank template, one signed contract, and one deliberately unsupported or empty file. Verify:

1. One selected file still opens the four-step editor.
2. Multiple files open centralized batch review.
3. Directory-inside upload preserves the directory and does not request AI recategorization.
4. Homepage upload applies valid AI directory suggestions and permits unclassified items.
5. Valid items default to checked; failed and incomplete items do not.
6. Inline directory creation returns to the same review state and selects the new directory.
7. Partial indexing success does not repeat completed items.
8. Closing cancels pending work and cleans non-completed previews.
9. Keyboard focus, 200% zoom, and narrow layout remain usable.

Delete only the temporary knowledge records and directories created by this acceptance check through the product's normal delete actions. Do not touch existing business documents.

- [ ] **Step 7: Commit system views and final design alignment**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/categories.js frontend/js/features/knowledge/index.js frontend/css/features.css frontend/css/responsive.css frontend/tests/knowledge_views_check.mjs frontend/tests/css_contract_check.mjs frontend/tests/premium_ui_check.mjs frontend/DESIGN.md && git commit -m "feat: add knowledge system views" && git status --short'
```

Expected: the commit contains only the listed knowledge-view and design files; final status still shows only the pre-existing `M deploy-server.sh`.
