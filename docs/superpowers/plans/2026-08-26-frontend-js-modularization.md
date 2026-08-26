# Frontend JavaScript Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the 1,083-line frontend monolith with browser-native ES modules organized by shared UI and business feature, without adding a build step or changing behavior.

**Architecture:** `js/main.js` owns startup and hash routing. Feature modules own page-specific rendering and actions; `core` and `ui` provide dependency-free shared helpers and must never import features.

**Tech Stack:** Browser ES Modules, vanilla JavaScript, HTML, FastAPI static files, Node.js 24, JSDOM.

**Spec:** `docs/superpowers/specs/2026-08-26-domain-modularization-design.md`

## Global Constraints

- Complete the foundation and backend plans first so REST contracts and `/api/state` remain stable.
- Do not add npm packages, bundlers, transpilers, frameworks, or a frontend build command.
- Preserve every visible label, hash route, REST request, dialog transition, validation behavior, and accessibility attribute.
- Do not duplicate a function in old and new modules; move it and update imports in the same task.
- Run Node/UI checks and Git commands on Aliyun.
- Keep `core` and `ui` free of imports from `features`.

---

### Task 1: Make the Existing Frontend Executable as an ES Module in JSDOM

**Files:**
- Create: `frontend/tests/helpers/dom.mjs`
- Modify: `frontend/index.html`
- Modify: `frontend/tests/settings_ui_check.mjs`
- Modify: `frontend/tests/premium_ui_check.mjs`

**Interfaces:**
- Produces: `createDom({ hash, state }) -> Promise<JSDOM>` and a module-capable test harness.
- Preserves: current `frontend/app.js` behavior before any function extraction.

- [ ] **Step 1: Change the HTML entry to a module and verify current tests fail**

Change only the script element:

```html
<script type="module" src="/department/app.js?v=20260825-3"></script>
```

Run both UI checks on Aliyun. Expected: FAIL because the tests currently evaluate `app.js` as a classic script and expect globals such as `closeAnimatedDialog`.

- [ ] **Step 2: Create a reusable module test harness**

`frontend/tests/helpers/dom.mjs` must:

```javascript
import { pathToFileURL } from 'node:url'
import { readFile } from 'node:fs/promises'
import { JSDOM } from '../../../../deepseek-harness/node_modules/jsdom/lib/api.js'

export async function createDom({ hash = 'dashboard', state, onRequest = () => {} }) {
  const root = new URL('../../', import.meta.url)
  const html = await readFile(new URL('index.html', root), 'utf8')
  const dom = new JSDOM(html, {
    url: `http://127.0.0.1:3081/department#${hash}`,
    pretendToBeVisual: true,
  })
  const { window } = dom
  window.HTMLDialogElement.prototype.showModal = function () { this.open = true }
  window.HTMLDialogElement.prototype.close = function (returnValue = '') {
    this.returnValue = returnValue
    this.open = false
    this.dispatchEvent(new window.Event('close'))
  }
  window.requestAnimationFrame = callback => callback()
  window.fetch = globalThis.fetch = async (url, options = {}) => {
    onRequest(String(url), options)
    return { ok: true, json: async () => structuredClone(state) }
  }
  for (const name of ['window', 'document', 'location', 'history', 'navigator', 'HTMLElement', 'HTMLDialogElement', 'Event', 'HashChangeEvent', 'File', 'FileReader']) {
    Object.defineProperty(globalThis, name, {
      configurable: true,
      value: window[name],
    })
  }
  const entry = pathToFileURL(new URL('app.js', root).pathname)
  await import(`${entry.href}?test=${Date.now()}`)
  await new Promise(resolve => setTimeout(resolve, 0))
  return dom
}
```

Keep the helper specific to one Node process per UI check; no cache-reset framework is needed.

- [ ] **Step 3: Update both UI checks to use `createDom`**

Remove direct `readFile(app.js)`, `dom.window.eval(app)`, and calls to module-private functions. Exercise dialogs through visible buttons instead. Keep every existing assertion and request capture.

- [ ] **Step 4: Run both checks**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/settings_ui_check.mjs && conda run --no-capture-output -n department-ai node tests/premium_ui_check.mjs'
```

Expected: both checks report `ok` while all production code still lives in `app.js`.

- [ ] **Step 5: Commit module-capable tests**

Commit with:

```text
test: support frontend ES modules
```

### Task 2: Extract Core State, DOM, Formatting, and HTTP

**Files:**
- Create: `frontend/js/core/dom.js`
- Create: `frontend/js/core/format.js`
- Create: `frontend/js/core/state.js`
- Create: `frontend/js/core/http.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: `$`, `$$`, `escapeHtml`, formatting helpers, live `state`, `replaceState`, and `request`.
- `request(path, { method = 'GET', body } = {}) -> Promise<any>` owns JSON/error handling only.

- [ ] **Step 1: Add direct core-module assertions**

Create `frontend/tests/core_modules_check.mjs` importing the future modules and asserting:

```javascript
assert.equal(escapeHtml('<b>'), '&lt;b&gt;')
assert.deepEqual(lineValues(' a\n\nb '), ['a', 'b'])
assert.equal(formatBytes(1024), '1.0 KiB')
replaceState({ processes: [{ id: 'p1' }] })
assert.equal(state.processes[0].id, 'p1')
```

Run it and expect module-not-found failure.

- [ ] **Step 2: Move pure helpers**

Move `$`, `$$`, and `escapeHtml` into `core/dom.js`. Move `lines`, `lineValues`, `formatDate`, `statusLabel`, `formatBytes`, and `bufferToBase64` into `core/format.js`. Export every moved symbol and import it from `app.js`.

- [ ] **Step 3: Create the state module**

Use a live export, not a copied object:

```javascript
export let state = {
  processes: [], categories: [], purposes: [], documents: [],
  skills: [], settings: null, services: {},
}

export function replaceState(value) { state = value }
```

Move only application-wide state. Keep `activeCategory` and `collapsedCategories` with the knowledge feature later.

- [ ] **Step 4: Replace the action switch with a generic HTTP primitive**

Create:

```javascript
export async function request(path, { method = 'GET', body } = {}) {
  const response = await fetch(path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  const payload = await response.json()
  if (!response.ok) {
    const detail = Array.isArray(payload.detail)
      ? payload.detail.map(item => item.msg).join('；')
      : payload.detail
    throw new Error(detail || payload.error || '请求失败')
  }
  return payload
}
```

For this task, keep small named endpoint wrappers in `app.js` so feature behavior remains unchanged. Delete `api(action, body)` only after every call site uses `request`.

- [ ] **Step 5: Run core and UI checks, then commit**

Expected: `core-modules-check: ok`, `settings-ui-check: ok`, and `premium-ui-check: ok`.

Commit with:

```text
refactor: extract frontend core modules
```

### Task 3: Extract Shared UI Primitives

**Files:**
- Create: `frontend/js/ui/dialog.js`
- Create: `frontend/js/ui/form.js`
- Create: `frontend/js/ui/feedback.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: dialog lifecycle, field validation, Toast/service badges, and page action setters.
- Consumes: `core/dom.js`; must not import any feature module.

- [ ] **Step 1: Add UI primitive assertions**

Extend one UI test to import the modules and assert that opening/closing a dialog preserves the 180 ms transition, invalid fields receive `aria-invalid`, and Toast uses the existing live region.

- [ ] **Step 2: Move dialog behavior**

Move `showAnimatedDialog`, `closeAnimatedDialog`, `confirmAction`, and `openDialog`, plus their private DOM references and cancel listeners, into `ui/dialog.js`. Export only `confirmAction`, `openDialog`, and the dialog content element needed by editors.

- [ ] **Step 3: Move forms and feedback**

Move `bindFormLabels`, `clearFieldError`, and `validateDialogForm` into `ui/form.js`.

Move `toast`, `serviceBadge`, `setAction`, and `setSecondaryAction` into `ui/feedback.js`. Keep existing DOM IDs and text unchanged.

- [ ] **Step 4: Run both UI checks and commit**

Commit with:

```text
refactor: extract shared frontend UI
```

### Task 4: Extract Dashboard and Assistant Pages

**Files:**
- Create: `frontend/js/features/dashboard.js`
- Create: `frontend/js/features/assistant.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: `renderDashboard()` and `renderAssistant()`.
- Consumes: application `state`, shared formatting, DOM, and feedback helpers.

- [ ] **Step 1: Move the two smallest renderers verbatim**

Move `renderDashboard` and `renderAssistant` with their required constants/imports. Do not move shared state or mutate labels.

- [ ] **Step 2: Import the renderers into the existing route map**

The existing `renderPage` continues to own routing at this stage:

```javascript
import { renderDashboard } from './js/features/dashboard.js'
import { renderAssistant } from './js/features/assistant.js'
```

- [ ] **Step 3: Test dashboard and assistant hash routes**

Add assertions that `#dashboard` renders its cards and `#assistant` creates the Harness iframe using `state.services.harnessUrl`.

- [ ] **Step 4: Run UI checks and commit**

Commit with:

```text
refactor: extract dashboard and assistant pages
```

### Task 5: Extract Processes

**Files:**
- Create: `frontend/js/features/processes/index.js`
- Create: `frontend/js/features/processes/editor.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: `renderProcesses()` and `openProcessEditor(process?)`.
- Consumes: `request`, `state/replaceState`, dialog/form/feedback helpers.

- [ ] **Step 1: Move the editor helpers**

Move `stepEditor`, `renumberSteps`, and `openProcessEditor` into `editor.js`. Replace action-switch calls with explicit requests:

```javascript
request('/api/processes', { method: 'POST', body })
request(`/api/processes/${encodeURIComponent(id)}`, { method: 'PUT', body })
request(`/api/processes/${encodeURIComponent(id)}`, { method: 'DELETE' })
```

- [ ] **Step 2: Move the page renderer**

Move `renderProcesses` into `index.js`, importing `openProcessEditor`. Preserve edit/delete selectors, confirmation copy, step ordering, and refresh behavior.

- [ ] **Step 3: Extend the UI check**

Assert create uses POST, edit uses PUT, delete sends no request before confirmation, and cancel still uses the 180 ms transition.

- [ ] **Step 4: Run UI checks and commit**

Commit with:

```text
refactor: extract processes frontend feature
```

### Task 6: Extract Skills and Settings

**Files:**
- Create: `frontend/js/features/skills/index.js`
- Create: `frontend/js/features/skills/editor.js`
- Create: `frontend/js/features/settings.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: `renderSkills()`, `openSkillEditor(skill?)`, and `renderSettings()` plus settings dialogs.
- Preserves: resource upload/download/delete behavior and single-section settings saves that retain untouched settings.

- [ ] **Step 1: Move Skill editor and renderer**

Move `openSkillEditor`, `skillResourceSummary`, and `renderSkills`. Keep resource URL encoding and Base64 conversion exact. Use explicit `/api/skills` requests.

- [ ] **Step 2: Move settings behavior**

Move `principleRow`, `renumberPrinciples`, `settingsPayload`, `bindPrincipleEditor`, all four settings dialogs, `settingRow`, and `renderSettings` into `features/settings.js`.

Keep `chunkSettingsForm`, `collectChunkSettings`, `setChunkSettings`, and chunk summary helpers temporarily exported from the knowledge module created in Task 7; until then, place them in `settings.js` and Task 7 moves the knowledge-owned editor pieces without duplication.

- [ ] **Step 3: Run existing settings and premium assertions**

Expected: unchanged settings section order, purpose manager entry, partial settings payload preservation, Skill resources, accessible labels, and confirmation behavior.

- [ ] **Step 4: Commit**

Commit with:

```text
refactor: extract skills and settings frontend features
```

### Task 7: Extract the Knowledge Feature

**Files:**
- Create: `frontend/js/features/knowledge/index.js`
- Create: `frontend/js/features/knowledge/categories.js`
- Create: `frontend/js/features/knowledge/purposes.js`
- Create: `frontend/js/features/knowledge/documents.js`
- Create: `frontend/js/features/knowledge/upload.js`
- Modify: `frontend/js/features/settings.js`
- Modify: `frontend/app.js`

**Interfaces:**
- Produces: `renderKnowledge()` and focused category, purpose, document, and upload helpers.
- Owns: `activeCategory` and `collapsedCategories` feature state.

- [ ] **Step 1: Move category and purpose management**

Move category option/tree/editor functions into `categories.js`. Move chunk-setting form helpers and purpose manager/editor functions into `purposes.js`; update `settings.js` to import the purpose manager entry rather than own it.

- [ ] **Step 2: Move upload and preview workflow**

Move file Base64 conversion, chunk preview/collection, metadata application, purpose/chunk toggles, and `openKnowledgeUpload` into `upload.js`. Preserve preview cleanup when the dialog closes.

- [ ] **Step 3: Move document details and page rendering**

Move `indexSummary`, `openDocumentEditor`, and `openDocument` into `documents.js`. Move `renderKnowledge` into `index.js` and compose the four submodules.

- [ ] **Step 4: Add knowledge request assertions**

In JSDOM, verify preview POST, rechunk POST, index POST, preview DELETE on cancel, document PUT/reindex POST, and document DELETE paths/methods.

- [ ] **Step 5: Run UI checks and commit**

Commit with:

```text
refactor: extract knowledge frontend feature
```

### Task 8: Replace the Legacy Entry and Enforce Boundaries

**Files:**
- Create: `frontend/js/main.js`
- Create: `frontend/tests/module_boundaries_check.mjs`
- Modify: `frontend/index.html`
- Modify: `frontend/tests/helpers/dom.mjs`
- Delete: `frontend/app.js`

**Interfaces:**
- Produces: final startup/hash router and automated import-direction checks.

- [ ] **Step 1: Move only composition into `js/main.js`**

The final entry must contain:

```javascript
const renderers = {
  dashboard: renderDashboard,
  processes: renderProcesses,
  knowledge: renderKnowledge,
  skills: renderSkills,
  assistant: renderAssistant,
  settings: renderSettings,
}

export function renderPage() { /* existing hash/title/navigation composition */ }
export async function start() { /* GET /api/state, replaceState, renderPage */ }

window.addEventListener('hashchange', renderPage)
start()
```

No editor, API endpoint, or feature-specific markup belongs in this file.

- [ ] **Step 2: Point HTML and tests at the final entry**

Use:

```html
<script type="module" src="/department/js/main.js?v=20260825-3"></script>
```

Update `tests/helpers/dom.mjs` to import `js/main.js`, then delete `app.js`.

- [ ] **Step 3: Add the module boundary check**

The Node check must recursively read `frontend/js/core` and `frontend/js/ui` and fail if either contains an import path with `/features/` or `../features`. It must also assert `js/main.js` does not declare functions matching `/open.*Editor|renderKnowledge|renderProcesses|renderSkills|renderSettings/`.

Print `frontend-module-boundaries-check: ok` on success.

- [ ] **Step 4: Run the full frontend JavaScript suite**

Run on Aliyun:

```bash
node tests/core_modules_check.mjs
node tests/module_boundaries_check.mjs
node tests/settings_ui_check.mjs
node tests/premium_ui_check.mjs
```

Expected: all four checks report `ok`.

- [ ] **Step 5: Start the service and perform a browser smoke check**

Verify dashboard, processes, knowledge, skills, assistant, and settings hash routes; verify one dialog open/cancel flow and one read-only state refresh. Do not mutate production-like knowledge data for this smoke check.

- [ ] **Step 6: Commit the final entry**

Commit with:

```text
refactor: complete frontend module split
```
