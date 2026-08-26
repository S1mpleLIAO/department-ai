# Department UI Premium Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在不改变业务逻辑的前提下，统一六个页面的视觉层级、弹窗、表单和窄屏体验。

**Architecture:** 保持现有单页 Vanilla JavaScript 结构和所有 API 调用，仅在 `index.html` 增加共享确认弹窗，在 `app.js` 增加通用表单与确认交互，在 `styles.css` 收拢设计令牌并覆盖页面表现。视觉规范记录在 `department-ai-python/DESIGN.md`。

**Tech Stack:** HTML、CSS、Vanilla JavaScript、JSDOM、Node.js assert

**Spec:** `department-ai-python/DESIGN.md`

## Global Constraints

- 不改变 REST、MCP、数据库、知识检索和 Harness 接入逻辑。
- 不引入新前端依赖。
- 保留六个现有页面和现有业务字段。
- 使用 Apple Blue `#007aff` 和克制型 Liquid Glass。

---

### Task 1: Shared interaction regression tests

**Files:**
- Create: `department-ai-python/tests/premium_ui_check.mjs`
- Test: `department-ai-python/tests/premium_ui_check.mjs`

**Interfaces:**
- Consumes: existing `web/index.html` and `web/app.js`
- Produces: executable UI contract for route titles, accessible labels and in-app destructive confirmation

- [ ] **Step 1: Write the failing test**

```js
assert.equal(document.title, '系统设置 · 部门 AI')
assert.ok(document.querySelector('#skill-name').labels.length)
deleteButton.click()
assert.ok(document.querySelector('#confirm-dialog').open)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node department-ai-python/tests/premium_ui_check.mjs`
Expected: FAIL because the page title is static and no shared confirm dialog exists.

- [ ] **Step 3: Keep the test fixture minimal**

Use a real JSDOM document and only mock `/api/state` plus the eventual DELETE response.

- [ ] **Step 4: Re-run to confirm the same expected failure**

Run: `node department-ai-python/tests/premium_ui_check.mjs`
Expected: FAIL at the first missing production behavior.

### Task 2: Canonical dialog and form behavior

**Files:**
- Modify: `department-ai-python/web/index.html`
- Modify: `department-ai-python/web/app.js`
- Test: `department-ai-python/tests/premium_ui_check.mjs`

**Interfaces:**
- Consumes: `openDialog()`, existing delete handlers and `pageInfo`
- Produces: `confirmAction(message, detail)`, `bindFormLabels(root)`, `validateDialogForm()`

- [ ] **Step 1: Add the shared confirm dialog markup**

```html
<dialog id="confirm-dialog" class="confirm-dialog">...</dialog>
```

- [ ] **Step 2: Add minimal shared helpers**

```js
function bindFormLabels(root) { /* associate each .field label with its control */ }
function confirmAction(message, detail = '') { /* resolve true or false */ }
```

- [ ] **Step 3: Replace all native `confirm()` calls**

Each delete handler awaits `confirmAction()` before calling the unchanged API operation.

- [ ] **Step 4: Update route title and inline validation**

`renderPage()` sets `${title} · 部门 AI`; invalid fields receive `aria-invalid` and focus.

- [ ] **Step 5: Run the UI tests**

Run: `node department-ai-python/tests/premium_ui_check.mjs`
Expected: PASS.

### Task 3: Cross-page visual hierarchy

**Files:**
- Modify: `department-ai-python/web/index.html`
- Modify: `department-ai-python/web/app.js`
- Modify: `department-ai-python/web/styles.css`

**Interfaces:**
- Consumes: existing render functions and CSS class names
- Produces: restrained glass shell, readable content surfaces, process track, staged upload layout and compact assistant shell

- [ ] **Step 1: Add canonical visual tokens and focus/layer rules**

Define surface, spacing, radius, shadow and z-index variables; add `:focus-visible` and reduced-motion rules.

- [ ] **Step 2: Refine the shell and shared components**

Use glass for sidebar/topbar/dialogs and stable surfaces for cards, tables and forms; replace inconsistent navigation glyphs with one line-icon treatment.

- [ ] **Step 3: Refine each page without changing data or handlers**

Adjust dashboard hierarchy, process timeline, knowledge table/tree, skill cards, assistant height and settings card summaries using existing render data.

- [ ] **Step 4: Refine long-form dialogs**

Keep header/footer sticky, make process steps and upload stages visually explicit, and preserve all existing fields and button handlers.

- [ ] **Step 5: Verify responsive rules**

At `900px` collapse navigation labels; at `620px` use one-column cards/forms and horizontal table scrolling.

### Task 4: Verification

**Files:**
- Test: `department-ai-python/tests/settings_ui_check.mjs`
- Test: `department-ai-python/tests/premium_ui_check.mjs`
- Test: `department-ai-python/tests/self_check.py`

**Interfaces:**
- Consumes: completed UI and unchanged Python services
- Produces: fresh automated and browser evidence

- [ ] **Step 1: Run frontend UI checks**

Run: `node department-ai-python/tests/settings_ui_check.mjs && node department-ai-python/tests/premium_ui_check.mjs`
Expected: both print `ok`.

- [ ] **Step 2: Run Python self-check**

Run: `cd department-ai-python && .venv/bin/python -m tests.self_check`
Expected: `self-check: ok`.

- [ ] **Step 3: Run strict Premium audit**

Run: `python3 .../audit_project.py department-ai-python --mode strict --no-write`
Expected: zero violations.

- [ ] **Step 4: Inspect all six pages and representative dialogs in the browser**

Verify active navigation, readable hierarchy, keyboard focus, toast/dialog stacking, process editor, knowledge upload and skill editor.
