# Knowledge Usage Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让知识资产可以选择“全局通用、独立任务场景、业务流程步骤”三种适用范围，并让 REST/MCP 检索在保持全库语义兜底的同时优先返回当前工作上下文关联的真实模板和知识。

**Architecture:** 复用 `knowledge_documents` 已有的流程、步骤和场景字段，不新增数据库结构。文档域负责适用范围校验、保存和 AI 建议，搜索域接收可选上下文并合并关联候选，Harness 继续负责判断当前工作属于流程、独立任务还是普通问答。

**Tech Stack:** Python 3.11、FastAPI、Pydantic、Psycopg 3、PostgreSQL/pgvector、MCP Python SDK、原生 JavaScript ES Modules、JSDOM、CSS。

**Spec:** `docs/superpowers/specs/2026-09-03-knowledge-usage-context-design.md`

## Global Constraints

- 所有项目运行、依赖、测试、数据库和 Git 命令必须通过 SSH 在阿里云 `/root/liao/DepartmentKnowledgeBase/department-ai` 执行。
- 使用 Conda 环境 `/root/anaconda3/envs/department-ai`，命令形式为 `conda run --no-capture-output -n department-ai ...`。
- 不实现人员、角色、部门或文档访问权限。
- 不新增数据库表或列；复用 `applicable_process_id`、`applicable_step_id` 和 `applicable_scenario`。
- 一份文档本阶段只保存一个主要适用范围，不实现多流程、多步骤或多任务场景关联。
- 流程和任务场景只提供检索软优先级，不能排除未关联但语义相关的候选。
- `score` 始终是 Rerank 原始分数，上下文优先级不得混入或覆盖该值。
- 保持现有三种文档用途及其索引能力不变；保留元数据模型 `max_tokens: 4096` 和 `User-Agent: department-ai/1.0`。
- 不修改 `backend/app/main.py`、`frontend/js/main.js`、向量模型、Rerank 模型或向量维度。
- 不新增第三方依赖；只在现有业务域内增加最少代码。
- 不暂存或提交当前 `deploy-server.sh` 的用户改动。
- 每个任务只暂存其列出的文件；提交前运行 `git diff --cached --name-only`。

---

## File Structure

- `backend/app/features/documents/schemas.py`：三种适用范围的严格请求契约和归一化。
- `backend/app/features/documents/router.py`：在入库、编辑和 AI 分析入口连接流程校验。
- `backend/app/features/documents/service.py`：向元数据模型提供真实流程并清洗适用范围建议。
- `backend/app/features/documents/store.py`：持久化并派生 `scopeType`。
- `backend/app/features/processes/store.py`：验证流程步骤存在且归属正确。
- `backend/app/features/catalog/store.py`：停止在每次启动时清空流程关联。
- `backend/app/features/search/schemas.py`：REST 检索的可选流程/任务上下文契约。
- `backend/app/features/search/store.py`：查询范围直接关联候选。
- `backend/app/features/search/service.py`：合并候选、软排序并生成推荐原因。
- `backend/app/mcp_server.py`：向 Harness 暴露检索上下文参数和调用规则。
- `backend/tests/knowledge_context_check.py`：适用范围、上下文排序和错误分支的离线聚焦检查。
- `backend/tests/knowledge_ingestion_check.py`：AI 适用范围建议清洗检查。
- `backend/tests/self_check.py`：文档映射和请求模型回归。
- `backend/tests/live_context_check.py`：真实数据库、入库和检索的端到端检查。
- `backend/tests/mcp_check.py`：MCP 工具 schema 和真实调用回归。
- `frontend/js/features/knowledge/scope.js`：上传与编辑共用的适用范围控件、联动、收集和文案。
- `frontend/js/features/knowledge/upload-metadata.js`：把范围控件纳入 AI 建议、收集和人工校验。
- `frontend/js/features/knowledge/upload.js`：向表单提供真实流程并在最终确认展示适用范围。
- `frontend/js/features/knowledge/documents.js`：详情展示和编辑适用范围。
- `frontend/tests/knowledge_context_check.mjs`：范围控件与文档编辑的浏览器检查。
- `frontend/tests/knowledge_upload_check.mjs`：知识入库四步流程请求体回归。
- `frontend/css/features.css`、`frontend/css/responsive.css`：范围选择器和窄屏布局。
- `frontend/tests/css_contract_check.mjs`：范围选择器样式契约。
- `backend/README.md`、`frontend/DESIGN.md`：更新管理和检索行为说明。

---

### Task 1: Persist and validate document usage scope

**Files:**
- Modify: `backend/app/features/documents/schemas.py`
- Modify: `backend/app/features/documents/router.py`
- Modify: `backend/app/features/documents/service.py`
- Modify: `backend/app/features/documents/store.py`
- Modify: `backend/app/features/processes/store.py`
- Modify: `backend/app/features/catalog/store.py`
- Create: `backend/tests/knowledge_context_check.py`
- Modify: `backend/tests/knowledge_ingestion_check.py`
- Modify: `backend/tests/self_check.py`

**Interfaces:**
- Produces: `KnowledgeScopeInput` with `scopeType`, `applicableProcessId`, `applicableStepId`, `applicableScenario` and normalization rules.
- Produces: `validate_process_step(pool, process_id, step_id) -> None`.
- Changes: `analyze_metadata(file_name, text, purposes, processes, base_url, api_key, model)`.
- Preserves: existing index/edit routes, document-purpose behavior and database columns.

- [ ] **Step 1: Write failing scope model and mapping checks**

Create `backend/tests/knowledge_context_check.py` with literal expectations that catch accepting incomplete scopes or losing stored scope data:

```python
from pydantic import ValidationError

from app.features.documents.schemas import KnowledgeIndexInput
from app.features.documents.store import map_document


def expect_invalid(payload: dict) -> None:
    try:
        KnowledgeIndexInput.model_validate({
            "title": "测试文档",
            "purposeId": "reference-knowledge",
            **payload,
        })
        raise AssertionError("无效适用范围必须被拒绝")
    except ValidationError:
        pass


def main() -> None:
    expect_invalid({"scopeType": "task", "applicableScenario": ""})
    expect_invalid({"scopeType": "process", "applicableProcessId": "procurement"})
    expect_invalid({"scopeType": "process", "applicableStepId": "contract"})
    global_scope = KnowledgeIndexInput.model_validate({
        "title": "公司介绍", "purposeId": "reference-knowledge", "scopeType": "global",
        "applicableProcessId": "procurement", "applicableStepId": "contract",
        "applicableScenario": "旧客户端遗留值",
    })
    assert global_scope.scopeType == "global"
    assert global_scope.applicableProcessId == ""
    assert global_scope.applicableStepId == ""
    assert global_scope.applicableScenario == ""

    task_scope = KnowledgeIndexInput.model_validate({
        "title": "设计方案模板", "purposeId": "generation-template",
        "scopeType": "task", "applicableScenario": " 编写设计方案 ",
        "applicableProcessId": "procurement", "applicableStepId": "contract",
    })
    assert task_scope.applicableScenario == "编写设计方案"
    assert task_scope.applicableProcessId == ""
    assert task_scope.applicableStepId == ""

    process_scope = KnowledgeIndexInput.model_validate({
        "title": "采购合同模板", "purposeId": "generation-template",
        "scopeType": "process", "applicableProcessId": "procurement",
        "applicableStepId": "contract", "applicableScenario": "设备采购",
    })
    assert process_scope.applicableProcessId == "procurement"
    assert process_scope.applicableStepId == "contract"

    row = {
        "id": "doc-1", "title": "采购合同模板", "category_id": None,
        "original_name": "采购合同.docx", "original_path": "/tmp/采购合同.docx",
        "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "status": "effective", "is_generation_template": True,
        "is_reference_knowledge": False, "purpose_id": "generation-template",
        "purpose_name": "生成模板", "document_type": "合同", "keywords": [], "outline": [],
        "template_family": "采购合同", "template_variant": "", "version": "V1.0",
        "applicable_process_id": "procurement", "applicable_step_id": "contract",
        "applicable_scenario": "设备采购", "summary": "", "chunk_settings": {},
        "chunk_count": 0, "indexed": True, "document_embedding": [0.1],
        "created_at": "2026-09-03T00:00:00Z", "updated_at": "2026-09-03T00:00:00Z",
    }
    mapped = map_document(row)
    assert mapped["scopeType"] == "process"
    assert mapped["applicableProcessId"] == "procurement"
    assert mapped["applicableStepId"] == "contract"
    print("knowledge-context-check: ok")


if __name__ == "__main__":
    main()
```

Extend `backend/tests/self_check.py` with these three literal mapping expectations:

```python
assert document["scopeType"] == "process"
assert document["applicableProcessId"] == "procurement"
assert document["applicableStepId"] == "contract"
```

- [ ] **Step 2: Run the focused checks and verify RED**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_context_check && conda run --no-capture-output -n department-ai python -m tests.self_check'
```

Expected: FAIL because `scopeType` and scope validation do not exist.

- [ ] **Step 3: Implement the minimal scope request model**

In `documents/schemas.py`, define a local optional identifier and reuse one base class in both write contracts:

```python
from pydantic import Field, StringConstraints, model_validator

OptionalIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^$|^[a-z0-9][a-z0-9-]{0,63}$"),
]


class KnowledgeScopeInput(StrictModel):
    scopeType: Literal["global", "task", "process"] = "global"
    applicableProcessId: OptionalIdentifier = ""
    applicableStepId: OptionalIdentifier = ""
    applicableScenario: ShortText = ""

    @model_validator(mode="after")
    def validate_scope(self) -> "KnowledgeScopeInput":
        if self.scopeType == "global":
            self.applicableProcessId = ""
            self.applicableStepId = ""
            self.applicableScenario = ""
        elif self.scopeType == "task":
            if not self.applicableScenario:
                raise ValueError("独立任务场景不能为空")
            self.applicableProcessId = ""
            self.applicableStepId = ""
        elif not self.applicableProcessId or not self.applicableStepId:
            raise ValueError("业务流程范围必须同时选择流程和步骤")
        return self
```

Make `KnowledgeIndexInput` and `KnowledgeDocumentUpdate` inherit `KnowledgeScopeInput`. Remove their duplicate `applicableScenario` fields.

- [ ] **Step 4: Implement process membership validation and persistence**

Add to `processes/store.py`:

```python
def validate_process_step(pool: ConnectionPool, process_id: str, step_id: str) -> None:
    with pool.connection() as connection:
        exists = connection.execute(
            "SELECT 1 FROM process_steps WHERE process_id = %s AND id = %s",
            (process_id, step_id),
        ).fetchone()
    if not exists:
        raise NotFoundError("业务流程步骤不存在或不属于所选流程")
```

In both `document_update` and `knowledge_index`, call it only when `scopeType == "process"` before embedding or moving files. In `documents/store.py`, persist all three existing columns on insert and update. Add this derivation to `map_document`:

```python
scope_type = (
    "process" if row["applicable_process_id"] and row["applicable_step_id"]
    else "task" if row["applicable_scenario"]
    else "global"
)
```

Return `"scopeType": scope_type`. Remove this startup data-loss statement from `catalog/store.py`:

```sql
UPDATE knowledge_documents
SET applicable_process_id = '', applicable_step_id = ''
WHERE applicable_process_id <> '' OR applicable_step_id <> ''
```

- [ ] **Step 5: Add real-process AI suggestions and invalid-ID cleaning**

Update the `analyze_metadata` signature to receive `processes: list[dict[str, Any]]`. Include a compact list containing only process IDs/names and step IDs/names in the user message. Require JSON fields `suggestedScopeType`, `applicableProcessId`, `applicableStepId`, and existing `applicableScenario` in the system message.

After parsing the model response, validate the suggested relation against a literal lookup:

```python
process_steps = {
    (str(process["id"]), str(step["id"]))
    for process in processes
    for step in process.get("steps", [])
}
scope_type = string("suggestedScopeType", 20)
process_id = string("applicableProcessId", 64)
step_id = string("applicableStepId", 64)
scenario = string("applicableScenario", 500)
if scope_type == "process" and (process_id, step_id) not in process_steps:
    scope_type, process_id, step_id = "", "", ""
elif scope_type == "task" and not scenario:
    scope_type = ""
elif scope_type == "global":
    process_id, step_id, scenario = "", "", ""
elif scope_type not in {"task", "process"}:
    scope_type = ""
```

Return the four cleaned fields. Pass `list_processes(_pool(request))` from `knowledge_analyze`.

Extend `knowledge_ingestion_check.py` so its fake response includes one valid process suggestion and one invalid suggestion. Assert the valid pair survives and the invalid pair returns empty `suggestedScopeType`, `applicableProcessId`, and `applicableStepId`. The fake process fixture must contain the complete API shape: `id`, `name`, `description`, and steps with `id`, `name`, `objective`, `requiredInputs`, `requiredOutputs`, `completionCriteria`, `instructions`.

- [ ] **Step 6: Run backend scope regression checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_context_check && conda run --no-capture-output -n department-ai python -m tests.knowledge_ingestion_check && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check'
```

Expected: all five checks print their `ok` lines.

- [ ] **Step 7: Commit only backend document-scope changes**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app/features/documents/schemas.py backend/app/features/documents/router.py backend/app/features/documents/service.py backend/app/features/documents/store.py backend/app/features/processes/store.py backend/app/features/catalog/store.py backend/tests/knowledge_context_check.py backend/tests/knowledge_ingestion_check.py backend/tests/self_check.py && git diff --cached --name-only && git commit -m "feat: add knowledge usage scopes"'
```

Expected: only the nine listed files are staged; `deploy-server.sh` remains unstaged.

---

### Task 2: Add scope controls to knowledge upload and editing

**Files:**
- Create: `frontend/js/features/knowledge/scope.js`
- Modify: `frontend/js/features/knowledge/upload-metadata.js`
- Modify: `frontend/js/features/knowledge/upload.js`
- Modify: `frontend/js/features/knowledge/documents.js`
- Create: `frontend/tests/knowledge_context_check.mjs`
- Modify: `frontend/tests/knowledge_upload_check.mjs`
- Modify: `frontend/css/features.css`
- Modify: `frontend/css/responsive.css`
- Modify: `frontend/tests/css_contract_check.mjs`

**Interfaces:**
- Produces from `scope.js`: `scopeFieldsHtml(prefix, processes, values)`, `bindScopeFields(prefix, processes)`, `collectScope(prefix)`, `validateScope(prefix)`, `applyScope(prefix, metadata, processes)`, `scopeLabel(document, processes)`.
- Changes: `metadataFormHtml({documentId, categoryOptionsHtml, purposes, processes})`.
- Preserves: four-step manual review; AI never automatically advances the workflow.

- [ ] **Step 1: Write failing browser checks for all three scopes**

Create `frontend/tests/knowledge_context_check.mjs` using `createDom` and this complete process fixture:

```javascript
const processes = [{
  id: 'procurement', name: '项目采购', description: '采购流程',
  steps: [{
    id: 'contract', name: '采购合同', objective: '签订合同',
    requiredInputs: [], requiredOutputs: [], completionCriteria: [], instructions: '',
  }],
}]
```

Import the real scope module and assert observable form behavior with literal values:

```javascript
const scope = await import('../js/features/knowledge/scope.js')
for (const name of ['scopeFieldsHtml', 'bindScopeFields', 'collectScope', 'validateScope', 'applyScope', 'scopeLabel']) {
  assert.equal(typeof scope[name], 'function', `scope module 应导出 ${name}`)
}

document.body.innerHTML = scope.scopeFieldsHtml('test', processes, { scopeType: '' })
scope.bindScopeFields('test', processes)
assert.equal(scope.validateScope('test').id, 'test-scope-global', '未确认范围应聚焦第一个选项')

document.querySelector('#test-scope-task').click()
assert.equal(document.querySelector('#test-task-fields').hidden, false)
assert.equal(document.querySelector('#test-process-fields').hidden, true)
assert.equal(scope.validateScope('test').id, 'test-task-scenario')
document.querySelector('#test-task-scenario').value = '编写设计方案'
assert.deepEqual(scope.collectScope('test'), {
  scopeType: 'task', applicableProcessId: '', applicableStepId: '',
  applicableScenario: '编写设计方案',
})

document.querySelector('#test-scope-process').click()
document.querySelector('#test-process').value = 'procurement'
document.querySelector('#test-process').dispatchEvent(new Event('change', { bubbles: true }))
assert.equal(document.querySelector('#test-step').value, '', '切换流程必须清空旧步骤')
document.querySelector('#test-step').value = 'contract'
assert.deepEqual(scope.collectScope('test'), {
  scopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract',
  applicableScenario: '',
})

assert.equal(scope.scopeLabel({ scopeType: 'global' }, processes), '全局通用')
assert.equal(scope.scopeLabel({ scopeType: 'task', applicableScenario: '编写设计方案' }, processes), '独立任务 / 编写设计方案')
assert.equal(scope.scopeLabel({ scopeType: 'process', applicableProcessId: 'procurement', applicableStepId: 'contract' }, processes), '项目采购 / 采购合同')
console.log('knowledge-context-check: ok')
```

- [ ] **Step 2: Run the scope browser check and verify RED**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_context_check.mjs'
```

Expected: FAIL with `ERR_MODULE_NOT_FOUND` for `scope.js`.

- [ ] **Step 3: Implement one feature-local scope component**

Create `scope.js` with radio IDs `${prefix}-scope-global`, `${prefix}-scope-task`, `${prefix}-scope-process`; a task panel `${prefix}-task-fields`; and a process panel `${prefix}-process-fields` containing `${prefix}-process` and `${prefix}-step` selects.

`bindScopeFields` must:

```javascript
const selectedType = () => document.querySelector(`input[name="${prefix}-scope-type"]:checked`)?.value || ''
const refreshVisibility = () => {
  document.querySelector(`#${prefix}-task-fields`).hidden = selectedType() !== 'task'
  document.querySelector(`#${prefix}-process-fields`).hidden = selectedType() !== 'process'
}
```

On process change, replace the step options with only the selected process steps and begin with `<option value="">请选择步骤</option>`. Do not create a task-scene registry or fetch another endpoint.

`applyScope` must accept AI fields only when the process/step pair exists in `processes`; invalid pairs leave all scope radios unselected. `validateScope` returns the first missing real form control for no selection, empty task scene, empty process, or empty step.

- [ ] **Step 4: Integrate scope into upload and AI review**

Pass `state.processes` into `metadataFormHtml`. Replace the old free-text-only `#template-scenario` block with `scopeFieldsHtml('upload', processes, {scopeType: ''})`.

Update `collectMetadata` to spread `collectScope('upload')`. Update `validateMetadata` so the first missing title/purpose/template field still wins, then returns `validateScope('upload')`. Update `applyMetadataSuggestion` to call `applyScope('upload', metadata, processes)` and continue marking applied fields with `data-ai-suggested="true"`.

In `upload.js`, bind the scope fields after opening the dialog. Reset all three radios and dependent fields when the file changes. Add this line to the final summary using the real helper:

```javascript
<span>适用范围：${escapeHtml(scopeLabel(metadata, state.processes))}</span>
```

Extend `knowledge_upload_check.mjs` to choose `#upload-scope-task`, fill `#upload-task-scenario` with `编写设计方案`, and assert the final `/index` body contains exactly:

```javascript
scopeType: 'task',
applicableProcessId: '',
applicableStepId: '',
applicableScenario: '编写设计方案',
```

Also change its AI fixture to return `suggestedScopeType: 'process'`, `applicableProcessId: 'procurement'`, `applicableStepId: 'contract'`, provide the complete process fixture in state, and assert the suggestion fills but does not advance the step.

- [ ] **Step 5: Integrate the same scope component into document editing**

In `documents.js`, render `scopeFieldsHtml('edit', state.processes, detail)`, call `bindScopeFields('edit', state.processes)` after the dialog opens, reject save when `validateScope('edit')` returns a control, and spread `collectScope('edit')` into the PUT body.

Replace the details row label “适用场景” with:

```javascript
<span><b>适用范围</b>${escapeHtml(scopeLabel(detail, state.processes))}</span>
```

Extend `knowledge_context_check.mjs` through the actual knowledge page: open a process-scoped document, click edit, switch to task scope, save, and assert the PUT request contains the four normalized scope fields and preserves the existing title, category, status, purpose-owned template fields and summary.

- [ ] **Step 6: Add minimal responsive scope styles**

Add `.scope-options` as a three-column grid using existing `.check-field` surfaces, and collapse it to one column in the existing narrow-screen media query. Add runtime CSS contract checks that load the stylesheets and assert the computed rule declarations for `.scope-options` and the narrow-screen override; do not assert raw source substrings.

- [ ] **Step 7: Run frontend regression checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_context_check.mjs && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs && conda run --no-capture-output -n department-ai node tests/module_boundaries_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

Expected: all five checks print their `ok` lines.

- [ ] **Step 8: Commit only frontend scope changes**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add frontend/js/features/knowledge/scope.js frontend/js/features/knowledge/upload-metadata.js frontend/js/features/knowledge/upload.js frontend/js/features/knowledge/documents.js frontend/tests/knowledge_context_check.mjs frontend/tests/knowledge_upload_check.mjs frontend/css/features.css frontend/css/responsive.css frontend/tests/css_contract_check.mjs && git diff --cached --name-only && git commit -m "feat: add knowledge scope controls"'
```

---

### Task 3: Prioritize retrieval by workflow or task context

**Files:**
- Modify: `backend/app/features/search/schemas.py`
- Modify: `backend/app/features/search/store.py`
- Modify: `backend/app/features/search/service.py`
- Modify: `backend/app/mcp_server.py`
- Modify: `backend/tests/knowledge_context_check.py`
- Modify: `backend/tests/mcp_check.py`
- Create: `backend/tests/live_context_check.py`
- Modify: `backend/README.md`
- Modify: `frontend/DESIGN.md`

**Interfaces:**
- Adds to both REST search bodies: optional `processId`, `stepId`, `taskScenario`.
- Adds to both MCP tools: optional `process_id`, `step_id`, `task_scenario`.
- Produces: `context_match(document, options) -> str`, `selection_reason(match, options) -> str`, and context fields on every returned template, document card and knowledge chunk.
- Preserves: existing search routes, tool names, template version deduplication and raw Rerank scores.

- [ ] **Step 1: Write failing context validation and ordering checks**

Append to `knowledge_context_check.py`:

```python
from app.features.search.schemas import TemplateSearchInput
from app.features.search.service import context_match, prioritize_ranked

expect_search_invalid = [
    {"query": "合同", "processId": "procurement"},
    {"query": "合同", "stepId": "contract"},
    {"query": "合同", "processId": "procurement", "stepId": "contract", "taskScenario": "编写合同"},
]
for payload in expect_search_invalid:
    try:
        TemplateSearchInput.model_validate(payload)
        raise AssertionError("冲突或不完整检索上下文必须被拒绝")
    except ValidationError:
        pass

process_options = {
    "processId": "procurement", "stepId": "contract", "taskScenario": "",
}
candidates = [
    {"id": "semantic", "applicableProcessId": "", "applicableStepId": "", "applicableScenario": "其他"},
    {"id": "global", "applicableProcessId": "", "applicableStepId": "", "applicableScenario": ""},
    {"id": "same", "applicableProcessId": "procurement", "applicableStepId": "compare", "applicableScenario": ""},
    {"id": "exact", "applicableProcessId": "procurement", "applicableStepId": "contract", "applicableScenario": ""},
]
ranked = [
    {"index": 0, "score": 0.95}, {"index": 1, "score": 0.90},
    {"index": 2, "score": 0.80}, {"index": 3, "score": 0.70},
]
ordered = prioritize_ranked(candidates, ranked, process_options)
assert [item["document"]["id"] for item in ordered] == ["exact", "same", "global", "semantic"]
assert [item["score"] for item in ordered] == [0.70, 0.80, 0.90, 0.95]
assert [item["contextMatch"] for item in ordered] == ["exact", "same-process", "global", "semantic"]

task_options = {"processId": None, "stepId": None, "taskScenario": " 编写设计方案 "}
assert context_match({
    "applicableProcessId": "", "applicableStepId": "", "applicableScenario": "编写设计方案",
}, task_options) == "exact"
assert context_match({
    "applicableProcessId": "", "applicableStepId": "", "applicableScenario": "",
}, task_options) == "global"
```

These assertions catch wrong context precedence and accidental score mutation.

- [ ] **Step 2: Run the focused backend check and verify RED**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_context_check'
```

Expected: FAIL because contextual search fields and ordering helpers do not exist.

- [ ] **Step 3: Implement strict optional search context**

Create a shared base in `search/schemas.py`:

```python
class SearchContextInput(StrictModel):
    processId: Identifier | None = None
    stepId: Identifier | None = None
    taskScenario: ShortText = ""

    @model_validator(mode="after")
    def validate_context(self) -> "SearchContextInput":
        has_process = self.processId is not None or self.stepId is not None
        if has_process and (self.processId is None or self.stepId is None):
            raise ValueError("流程检索上下文必须同时提供流程和步骤")
        if has_process and self.taskScenario:
            raise ValueError("流程步骤和独立任务场景不能同时作为检索上下文")
        return self
```

Make `TemplateSearchInput` and `KnowledgeSearchInput` inherit it. In both REST services, call `validate_process_step` when a process context exists.

- [ ] **Step 4: Query direct-scope candidates without hard filtering**

Add three store functions:

```python
scoped_template_candidates(pool, process_id, step_id, task_scenario, limit)
scoped_reference_documents(pool, process_id, step_id, task_scenario, limit)
scoped_chunk_candidates(pool, process_id, step_id, task_scenario, limit)
```

For process context, select effective rows where `applicable_process_id = %s`; this supplies both exact-step and same-process candidates. For task context, select effective rows where `lower(trim(applicable_scenario)) = lower(trim(%s))`. Apply the same template/reference/chunk capability predicates as the existing semantic queries. Return an empty list without opening a connection when no context is supplied.

Set the store-only candidate `score` to `0.0`; final `score` always comes from Rerank. Extend chunk SELECT/mapping with `applicable_process_id`, `applicable_step_id`, and `applicable_scenario` so chunk results can be contextualized from real document metadata.

Merge scoped candidates after existing vector and keyword candidates by stable ID:

```python
recalled = {
    item["id"]: item
    for item in [*semantic, *lexical, *scoped]
}
```

Do this independently for templates, reference document cards and reference chunks. Do not add global documents wholesale; semantic/keyword recall remains their bounded entry path.

- [ ] **Step 5: Implement context precedence and recommendation reasons**

In `search/service.py`, add:

```python
CONTEXT_PRIORITY = {"exact": 3, "same-process": 2, "global": 1, "semantic": 0}


def context_match(document: dict[str, Any], options: dict[str, Any]) -> str:
    process_id, step_id = options.get("processId"), options.get("stepId")
    task = str(options.get("taskScenario") or "").strip().casefold()
    document_process = str(document.get("applicableProcessId") or "")
    document_step = str(document.get("applicableStepId") or "")
    scenario = str(document.get("applicableScenario") or "").strip().casefold()
    if process_id and document_process == process_id and document_step == step_id:
        return "exact"
    if process_id and document_process == process_id:
        return "same-process"
    if task and not document_process and not document_step and scenario == task:
        return "exact"
    if not document_process and not document_step and not scenario:
        return "global"
    return "semantic"


def prioritize_ranked(candidates, ranked, options):
    values = [
        {
            "document": candidates[int(item["index"])],
            "score": item["score"],
            "contextMatch": context_match(candidates[int(item["index"])], options),
        }
        for item in ranked
    ]
    return sorted(values, key=lambda item: (-CONTEXT_PRIORITY[item["contextMatch"]], -item["score"]))
```

Add `selection_reason` with these exact meanings, allowing the process/task display value to be interpolated:

- `exact` with process context: `直接关联当前流程步骤`
- `exact` with task context: `f"直接关联独立任务场景“{options['taskScenario'].strip()}”"`
- `same-process`: `关联当前业务流程`
- `global`: `全局通用知识`
- `semantic`: `与当前需求语义相关`

Apply the configured relevance threshold to raw Rerank results before calling `prioritize_ranked`. Return `contextMatch` and `selectionReason` on templates, reference document cards and chunk results. Keep template family/variant version deduplication before Rerank.

- [ ] **Step 6: Expose the same context through MCP**

Update both MCP signatures:

```python
def template_search(
    query: str, keywords: list[str] | None = None, limit: int | None = None,
    process_id: str | None = None, step_id: str | None = None,
    task_scenario: str | None = None,
) -> dict[str, Any]:
```

```python
def knowledge_search(
    query: str, keywords: list[str] | None = None, document_id: str | None = None,
    limit: int | None = None, process_id: str | None = None,
    step_id: str | None = None, task_scenario: str | None = None,
) -> dict[str, Any]:
```

Map snake-case MCP arguments to camel-case Pydantic fields. Update descriptions so Harness calls `process_list` before sending process IDs, sends a stable task scene for a one-off deliverable, omits context for ordinary Q&A, and explains `selectionReason` before asking the user to confirm a template.

Extend `mcp_check.py` to inspect the listed tool input schemas and assert both search tools expose `process_id`, `step_id`, and `task_scenario` while the six tool names remain unchanged.

- [ ] **Step 7: Add a live context smoke check**

Create `backend/tests/live_context_check.py` using `urllib.request` in the style of `live_preview_check.py`. It must:

1. Create a temporary process with one step through `/api/processes`.
2. Upload and index three unique plain-text generation templates through the existing preview/index endpoints: one global, one task-scoped to `编写设计方案`, and one process-scoped to the temporary step.
3. Call `/api/search/templates` once with `taskScenario` and once with `processId`/`stepId`.
4. Assert the first result has `contextMatch == "exact"`, keeps a numeric raw `score`, and has the matching Chinese `selectionReason`.
5. In `finally`, delete all three documents and the temporary process so the check is repeatable.

Use unique IDs derived from `uuid4()` and a shared query phrase present in all three test documents. This test exercises the real database, embedding and Rerank services; it must not replace any of them with mocks.

- [ ] **Step 8: Update operator and UX documentation**

In `backend/README.md`, document the three optional search context fields, soft-priority semantics, MCP snake-case names and the absence of permission filtering. In `frontend/DESIGN.md`, record that knowledge upload requires an explicit scope choice and that process/step controls are conditionally displayed.

- [ ] **Step 9: Run full fresh verification on Aliyun**

Run backend offline checks:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.knowledge_context_check && conda run --no-capture-output -n department-ai python -m tests.knowledge_ingestion_check && conda run --no-capture-output -n department-ai python -m tests.self_check && conda run --no-capture-output -n department-ai python -m tests.route_contract_check && conda run --no-capture-output -n department-ai python -m tests.module_boundaries_check'
```

Run frontend checks:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/knowledge_context_check.mjs && conda run --no-capture-output -n department-ai node tests/knowledge_upload_check.mjs && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs && conda run --no-capture-output -n department-ai node tests/module_boundaries_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

With the backend running on `127.0.0.1:3081`, run live checks:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/backend && conda run --no-capture-output -n department-ai python -m tests.live_context_check && conda run --no-capture-output -n department-ai python -m tests.mcp_check'
```

Expected: every command exits `0`; each check prints its `ok` line; the live check removes its temporary records.

- [ ] **Step 10: Commit search, MCP, live check and documentation**

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && git add backend/app/features/search/schemas.py backend/app/features/search/store.py backend/app/features/search/service.py backend/app/mcp_server.py backend/tests/knowledge_context_check.py backend/tests/mcp_check.py backend/tests/live_context_check.py backend/README.md frontend/DESIGN.md && git diff --cached --name-only && git commit -m "feat: prioritize knowledge by task context"'
```

Expected: only the nine listed files are staged; `deploy-server.sh` remains unstaged.

---

## Final acceptance checklist

- [ ] Upload requires a deliberate choice among global, task and process scope.
- [ ] AI scope suggestions use only real process/step IDs and never bypass manual confirmation.
- [ ] Document detail and editing preserve the selected scope.
- [ ] Restarting the backend no longer erases process associations.
- [ ] REST and MCP accept equivalent optional task context.
- [ ] Direct scope, same-process, global and semantic candidates remain available in the designed order.
- [ ] No personnel-permission UI, API, SQL or filtering has been added.
- [ ] `deploy-server.sh` remains outside every feature commit.
- [ ] Backend, frontend, live REST and MCP checks pass freshly on Aliyun.
