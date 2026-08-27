# Knowledge Ingestion Review Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将知识入库改成“解析正文、人工确认属性、索引预览、最终入库”四步工作流，使 AI 分析成为可选建议，并按人工确认的文档用途生成索引。

**Architecture:** 后端把上传解析、AI 元数据建议、正文分块和最终入库拆成独立接口，临时预览是阶段之间唯一的服务器状态。前端在 `knowledge` 业务域内使用显式状态机，并把元数据表单和分块编辑分别放入专用模块；不增加数据库表、共享层或第三方依赖。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、原生 JavaScript ES Modules、JSDOM、CSS。

**Spec:** `docs/superpowers/specs/2026-08-27-knowledge-ingestion-review-workflow-design.md`

## Global Constraints

- 所有项目运行、测试和 Git 命令必须通过 SSH 在阿里云 `/root/liao/DepartmentKnowledgeBase/department-ai` 执行。
- 使用 Conda 环境 `/root/anaconda3/envs/department-ai`，命令形式为 `conda run --no-capture-output -n department-ai ...`。
- 保留 `backend/app/features/documents/service.py` 中现有的 `max_tokens: 4096` 和 `User-Agent: department-ai/1.0` 修改。
- 不暂存或提交当前 `deploy-server.sh` 的已有用户改动，除非部署检查证明本次架构调整确实要求修改它。
- 不修改数据库结构、MCP 搜索/模板读取契约、`backend/app/main.py` 或 `frontend/js/main.js`。
- 不新增第三方依赖；共享模块只有在两个业务域共同使用时才创建。
- 空白或去主体化合同建议“生成模板”；存在真实主体、金额、签章等履约信息的合同建议“模板＋参考知识”；制度、规范、历史经验建议“参考知识”。AI 建议必须由用户确认。
- 每个任务只暂存其列出的文件；提交前运行 `git diff --cached --name-only` 防止带入用户改动。

---

## File Structure

- `backend/app/features/documents/schemas.py`：每个入库阶段的严格输入契约。
- `backend/app/features/documents/router.py`：解析、AI 分析、重新分块、最终入库四个接口。
- `backend/app/features/documents/service.py`：文档解析、分块、AI 提示和返回值清洗。
- `backend/tests/knowledge_ingestion_check.py`：阶段接口和 AI 用途规则的聚焦检查。
- `backend/tests/route_contract_check.py`：锁定新增 AI 分析接口。
- `backend/tests/live_preview_check.py`：真实文档的完整四阶段服务器验收。
- `frontend/js/features/knowledge/upload.js`：弹窗生命周期、状态机、步骤导航、请求和最终提交。
- `frontend/js/features/knowledge/upload-metadata.js`：元数据表单渲染、建议应用、人工校验和数据收集。
- `frontend/js/features/knowledge/upload-chunks.js`：分块设置、预览渲染、编辑、启停和数据收集。
- `frontend/tests/knowledge_upload_check.mjs`：四步流程、AI 可选、错误恢复和用途失效行为。
- `frontend/tests/premium_ui_check.mjs`：删除旧的一体化上传断言，保留其余页面回归。
- `frontend/css/features.css`：四步状态、内容面板、AI 建议和最终摘要样式。
- `frontend/css/responsive.css`：窄屏单列、步骤条和预览滚动约束。
- `frontend/tests/css_contract_check.mjs`：锁定四步样式与响应式规则。
- `frontend/DESIGN.md`：把知识上传从三阶段更新为四阶段。

---

### Task 1: Split backend ingestion stages

**Files:**
- Modify: `backend/app/features/documents/schemas.py`
- Modify: `backend/app/features/documents/router.py`
- Modify: `backend/app/features/documents/service.py`
- Create: `backend/tests/knowledge_ingestion_check.py`
- Modify: `backend/tests/route_contract_check.py`
- Modify: `backend/tests/live_preview_check.py`

**Interfaces:**
- Consumes: `decode_upload(...)`, `parse_document(...)`, `analyze_metadata(...)`, `chunk_document(...)`, preview store helpers and catalog purposes.
- Produces: `POST /api/knowledge/preview` with body `{fileName, fileBase64, mimeType}` and response `{id, fileName, characters}`; `POST /api/knowledge/previews/{preview_id}/analyze` with no body and response `{id, metadata}`; existing `rechunk` response `{id, characters, chunks}`; existing `index` contract with stricter purpose validation.

- [ ] **Step 1: Write failing focused backend checks**

Create `backend/tests/knowledge_ingestion_check.py` with a `main()` check that:

```python
from unittest.mock import patch

from app.features.documents.schemas import KnowledgePreviewInput
from app.features.documents.service import analyze_metadata


def main() -> None:
    upload = KnowledgePreviewInput.model_validate({
        "fileName": "合同.docx",
        "fileBase64": "UEsDBA==",
        "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    })
    assert not hasattr(upload, "chunkSettings")

    captured = {}
    def fake_send(request, timeout, label):
        captured["body"] = request.data.decode()
        return {"choices": [{"message": {"content": '{"suggestedPurposeId":"generation-template"}'}}]}

    purposes = [
        {"id": "generation-template", "name": "生成模板", "description": "", "canGenerateTemplate": True, "chunkBody": False},
        {"id": "reference-knowledge", "name": "参考知识", "description": "", "canGenerateTemplate": False, "chunkBody": True},
        {"id": "template-reference", "name": "模板＋参考知识", "description": "", "canGenerateTemplate": True, "chunkBody": True},
    ]
    with patch("app.features.documents.service._send", fake_send):
        metadata = analyze_metadata("合同.docx", "甲方：____ 乙方：____", purposes, "https://metadata.example", "key", "model")
    assert metadata["suggestedPurposeId"] == "generation-template"
    assert "空白范本" in captured["body"]
    assert "真实甲乙方" in captured["body"]
    assert "签章" in captured["body"]
    print("knowledge-ingestion-check: ok")


if __name__ == "__main__":
    main()
```

Add `("POST", "/api/knowledge/previews/{preview_id}/analyze", 200)` between preview and rechunk in `route_contract_check.py`. Update `live_preview_check.py` to assert parse response has no `metadata` or `chunks`, then call `/analyze`, then `/rechunk`, then `/index`.

- [ ] **Step 2: Run checks and verify they fail for the old combined contract**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_ingestion_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check'
```

Expected: `KnowledgePreviewInput` rejects the missing `chunkSettings`, or the new `/analyze` route is missing.

- [ ] **Step 3: Implement the stage-specific schemas and routes**

Change the preview schema to:

```python
class KnowledgePreviewInput(StrictModel):
    fileName: NonEmpty
    fileBase64: NonEmpty
    mimeType: str = "application/octet-stream"
```

Make parse preview persist only the parsed source state:

```python
preview = {
    "id": preview_id,
    "fileName": file_name,
    "mimeType": upload.mimeType,
    "parsedText": parsed_text,
    "settings": None,
    "chunks": [],
    "createdAt": datetime.now(timezone.utc).isoformat(),
}
```

Add the AI route:

```python
@router.post("/api/knowledge/previews/{preview_id}/analyze")
def knowledge_analyze(preview_id: str, request: Request) -> dict[str, Any]:
    runtime = _settings(request)
    preview = read_preview(runtime.data_dir, preview_id)
    metadata = analyze_metadata(
        preview["fileName"], preview["parsedText"], list_purposes(_pool(request)),
        runtime.metadata_base_url, runtime.metadata_api_key, runtime.metadata_model,
    )
    return {"id": preview_id, "metadata": metadata}
```

Remove metadata from `rechunk` responses. In `knowledge_index`, reject a reference-capable purpose when no effective chunk exists, and use `preview.get("settings") or get_department_settings(_pool(request))["chunking"]` for the stored `chunkSettings` so a generation-only template can be indexed without calling `rechunk`.

Update the AI system message with the three exact classification rules in Global Constraints, while preserving the existing 4096 token limit and User-Agent header.

- [ ] **Step 4: Run focused and existing backend checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_ingestion_check && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check'
```

Expected: four checks print their `ok` lines.

- [ ] **Step 5: Commit only backend stage changes**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app/features/documents/schemas.py backend/app/features/documents/router.py backend/app/features/documents/service.py backend/tests/knowledge_ingestion_check.py backend/tests/route_contract_check.py backend/tests/live_preview_check.py && git diff --cached --name-only && git commit -m "feat: split knowledge ingestion backend stages"'
```

Expected staged names: only the six files listed above; `deploy-server.sh` remains unstaged.

---

### Task 2: Extract metadata and chunk UI modules

**Files:**
- Create: `frontend/js/features/knowledge/upload-metadata.js`
- Create: `frontend/js/features/knowledge/upload-chunks.js`
- Create: `frontend/tests/knowledge_upload_check.mjs`

**Interfaces:**
- Consumes: `state.purposes`, category option HTML, default chunking settings and existing DOM helpers.
- Produces from metadata module: `metadataFormHtml({documentId, categoryOptionsHtml, purposes})`, `applyMetadataSuggestion(metadata, purposes)`, `collectMetadata(outline)`, `validateMetadata(purposes)`, `selectedPurpose(purposes)`, `togglePurposeFields(purposes)`.
- Produces from chunks module: `chunkPanelHtml(settings)`, `renderChunkPreview(chunks)`, `collectPreviewChunks()`, `hasEnabledChunk()`, `renderIndexPlan(purpose)`.

- [ ] **Step 1: Write failing module and UI contract checks**

Create `frontend/tests/knowledge_upload_check.mjs`. Its first assertions must import the future modules and verify exact exports:

```javascript
import assert from 'node:assert/strict'

const metadata = await import('../js/features/knowledge/upload-metadata.js')
const chunks = await import('../js/features/knowledge/upload-chunks.js')

for (const name of ['metadataFormHtml', 'applyMetadataSuggestion', 'collectMetadata', 'validateMetadata', 'selectedPurpose', 'togglePurposeFields']) {
  assert.equal(typeof metadata[name], 'function', `metadata module 应导出 ${name}`)
}
for (const name of ['chunkPanelHtml', 'renderChunkPreview', 'collectPreviewChunks', 'hasEnabledChunk', 'renderIndexPlan']) {
  assert.equal(typeof chunks[name], 'function', `chunks module 应导出 ${name}`)
}
```

Add static assertions that `metadataFormHtml(...)` starts the purpose select with `<option value="" selected>待确认</option>` and does not preselect `reference-knowledge`.

- [ ] **Step 2: Run the module check and verify missing-module failure**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs'
```

Expected: `ERR_MODULE_NOT_FOUND` for `upload-metadata.js`.

- [ ] **Step 3: Implement focused metadata and chunk modules**

Move metadata form HTML, purpose toggling and metadata collection out of `upload.js`. `applyMetadataSuggestion` must set `#document-purpose` when the suggested ID exists, add `data-ai-suggested="true"` to populated controls, and never trigger navigation. `validateMetadata` must return the first invalid element after requiring title, purpose and template family when `canGenerateTemplate` is true.

Move chunk settings and cards out of `upload.js`, while continuing to reuse these existing functions from `purposes.js`:

```javascript
import { chunkSettingsForm, collectChunkSettings, setChunkSettings, toggleChunkFields } from './purposes.js'
```

`renderIndexPlan(purpose)` must explicitly return template-only, reference-only or combined index descriptions from `canGenerateTemplate` and `chunkBody`.

- [ ] **Step 4: Run module and boundary checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/module_boundaries_check.mjs'
```

Expected: both checks print `ok`.

- [ ] **Step 5: Commit only the new modules and test scaffold**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/upload-metadata.js frontend/js/features/knowledge/upload-chunks.js frontend/tests/knowledge_upload_check.mjs && git diff --cached --name-only && git commit -m "refactor: extract knowledge upload stage modules"'
```

---

### Task 3: Implement the four-step frontend state machine

**Files:**
- Modify: `frontend/js/features/knowledge/upload.js`
- Modify: `frontend/tests/knowledge_upload_check.mjs`
- Modify: `frontend/tests/premium_ui_check.mjs`

**Interfaces:**
- Consumes: Task 1 endpoints and Task 2 UI helpers.
- Produces: explicit `selecting`, `reviewing-metadata`, `reviewing-index`, `confirming`, `saving` UI states and the final unchanged index request body.

- [ ] **Step 1: Extend the failing browser workflow test**

Use `createDom` with three purposes and a request stub. Assert this exact sequence:

```javascript
assert.equal(document.querySelector('#document-purpose').value, '')
assert.equal(document.querySelector('[data-upload-step="selecting"]').hidden, false)

document.querySelector('#parse-document').click()
await waitFor(() => requests.at(-1)?.url === '/api/knowledge/preview')
assert.deepEqual(JSON.parse(requests.at(-1).body), {
  fileName: '合同.docx', mimeType: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document', fileBase64: 'QUJD',
})
assert.equal(document.querySelector('[data-upload-step="reviewing-metadata"]').hidden, false)

document.querySelector('#analyze-metadata').click()
await waitFor(() => requests.at(-1)?.url.endsWith('/analyze'))
assert.equal(document.querySelector('#document-purpose').value, 'generation-template')
assert.equal(document.querySelector('[data-upload-step="reviewing-index"]').hidden, true, 'AI 不得自动跳过人工确认')
```

Add a second path that never clicks `#analyze-metadata`, fills title and purpose manually, continues successfully, and confirms that template-only purpose never calls `/rechunk`. Add a reference path that calls `/rechunk`, makes a purpose change, and asserts the old chunk preview is invalidated. Add AI failure response coverage where the current metadata form values remain intact and `#metadata-error` becomes visible.

- [ ] **Step 2: Run the browser check and verify old UI fails**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs'
```

Expected: missing `#parse-document`, four step panels, or `/analyze` request.

- [ ] **Step 3: Replace the combined handler with a state-driven workflow**

In `upload.js`, keep requests private:

```javascript
function previewKnowledge(body) { return request('/api/knowledge/preview', { method: 'POST', body }) }
function analyzeKnowledge(previewId) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/analyze`, { method: 'POST' }) }
function rechunkKnowledge(previewId, settings) { return request(`/api/knowledge/previews/${encodeURIComponent(previewId)}/rechunk`, { method: 'POST', body: settings }) }
```

Use one workflow object:

```javascript
const workflow = {
  stage: 'selecting', preview: null, metadata: null, chunks: [],
  confirmedMetadata: null, indexPurposeId: '', saving: false,
}
```

Implement `setStage(stage)` to update all `[data-upload-step]` panels, stepper `current/completed` classes, footer button visibility/label, and focus the new panel heading. File changes call `discardPreview()` and reset to `selecting`. Purpose changes during or after `reviewing-index` clear `workflow.chunks` and `workflow.indexPurposeId`.

The metadata continue action must call `validateMetadata`; for a purpose with `chunkBody`, it calls `rechunk` before entering `reviewing-index`; for generation-only it directly renders a template index plan with no chunks. The index continue action builds a read-only final summary and enters `confirming`. Only the dialog save callback in `confirming` calls `indexKnowledge`.

- [ ] **Step 4: Remove obsolete combined-flow assertions and run frontend regression**

Delete only the knowledge upload block from `premium_ui_check.mjs` that expects `chunkSettings` on `/preview`, automatic metadata/chunks, and immediate dialog save. Keep document view/edit/delete and all unrelated premium checks unchanged.

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs && conda run --no-capture-output -n department-ai node tests/settings_ui_check.mjs && conda run --no-capture-output -n department-ai node tests/module_boundaries_check.mjs'
```

Expected: all four checks print `ok`.

- [ ] **Step 5: Commit the working four-step interaction**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/upload.js frontend/tests/knowledge_upload_check.mjs frontend/tests/premium_ui_check.mjs && git diff --cached --name-only && git commit -m "feat: add reviewed knowledge ingestion workflow"'
```

---

### Task 4: Polish stage presentation and update design rules

**Files:**
- Modify: `frontend/css/features.css`
- Modify: `frontend/css/responsive.css`
- Modify: `frontend/tests/css_contract_check.mjs`
- Modify: `frontend/DESIGN.md`

**Interfaces:**
- Consumes: Task 3 DOM classes `upload-stepper`, `current`, `completed`, `upload-stage`, `ai-suggested`, `upload-actions`, `upload-summary`.
- Produces: stable four-step desktop layout, single-column narrow layout and documented UI behavior.

- [ ] **Step 1: Add failing CSS contract assertions**

Extend `css_contract_check.mjs` with:

```javascript
assert.match(features, /\.upload-stepper \.completed/)
assert.match(features, /\.upload-stage\[hidden\]/)
assert.match(features, /\.ai-suggested/)
assert.match(features, /\.upload-summary/)
assert.match(responsive, /@media \(max-width: 620px\)[\s\S]*\.upload-stepper/)
```

Also assert `DESIGN.md` contains `解析正文 → 确认属性 → 索引预览 → 最终入库`.

- [ ] **Step 2: Run the CSS check and verify it fails**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs'
```

Expected: missing completed step, stage or four-step design contract.

- [ ] **Step 3: Implement the scoped UI styles and design documentation**

Change the stepper grid to seven columns for four labels and three connectors. Add completed check styling without using another accent color. Ensure:

```css
.upload-stage[hidden] { display: none; }
.upload-stepper .completed { color: var(--ink); }
.upload-stepper .completed b { color: var(--brand); background: rgba(0, 122, 255, .1); }
.ai-suggested { border-color: rgba(0, 122, 255, .35); }
.upload-actions { display: flex; justify-content: space-between; gap: 12px; }
```

Keep stage content on opaque readable surfaces. At `max-width: 1050px`, use one content column; at `max-width: 620px`, stack step labels, hide connectors and stack action buttons without horizontal scrolling. Update the knowledge-page rule in `DESIGN.md` to the exact four-stage wording.

- [ ] **Step 4: Run CSS, upload and premium UI checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

Expected: all three checks print `ok`.

- [ ] **Step 5: Commit presentation and design contract**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/css/features.css frontend/css/responsive.css frontend/tests/css_contract_check.mjs frontend/DESIGN.md && git diff --cached --name-only && git commit -m "style: present four-stage knowledge ingestion"'
```

---

### Task 5: Full verification, real contract acceptance, and deployment decision

**Files:**
- Verify: all files changed in Tasks 1–4
- Conditionally modify: `deploy-server.sh` only if its checks or restart targets depend on removed file names or old routes

**Interfaces:**
- Consumes: complete approved workflow.
- Produces: evidence that automated checks, the real `.docx` flow and deployment script remain valid.

- [ ] **Step 1: Run complete non-live verification on Aliyun**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && sh tests/server_scripts_check.sh && sh tests/deploy_state_check.sh && cd backend && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.knowledge_ingestion_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check && cd ../frontend && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs && conda run --no-capture-output -n department-ai node tests/core_modules_check.mjs && conda run --no-capture-output -n department-ai node tests/module_boundaries_check.mjs && conda run --no-capture-output -n department-ai node tests/settings_ui_check.mjs && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

Expected: every script exits 0 and prints its `ok` marker.

- [ ] **Step 2: Check whether deployment architecture changed**

Inspect `deploy-server.sh` only for backend/frontend paths, test lists, service names and port restarts. Because no entry point, dependency or service name changes in this plan, expected decision is “deployment script does not require a workflow-specific change.” Do not stage its existing user diff.

- [ ] **Step 3: Restart the existing application services and run the real document flow**

Use the project’s current deployment/restart mechanism, then run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.live_preview_check "/root/liao/DepartmentKnowledgeBase/算力并网框架协议.docx"'
```

Expected: parsing succeeds without chunks/metadata in the first response, AI analysis returns a valid allowed purpose suggestion, rechunk succeeds, final indexing succeeds, search returns at least one match, and the test removes its temporary indexed document.

- [ ] **Step 4: Inspect final Git scope and committed history**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git status --short && git log --oneline -6 && git diff --check'
```

Expected: only the pre-existing `deploy-server.sh` user change may remain; no untracked implementation files or whitespace errors.

- [ ] **Step 5: Commit a deployment-script adjustment only if Step 2 proved necessary**

If and only if a concrete removed path or missing new check was found, make the smallest correction, rerun `tests/server_scripts_check.sh`, then:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add deploy-server.sh tests/server_scripts_check.sh && git diff --cached --name-only && git commit -m "chore: align deployment checks with ingestion workflow"'
```

Otherwise make no Task 5 commit and report that deployment commands remain unchanged.
