# Frontend CSS Modularization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split the existing CSS into stable responsibility-based files while preserving the exact current cascade, responsive behavior, and visual appearance.

**Architecture:** `frontend/styles.css` remains the single public stylesheet and imports tokens, base, layout, components, features, and responsive files in a fixed order. Existing premium overrides are merged into the owning file after the base declarations they currently override.

**Tech Stack:** Native CSS `@import`, existing design tokens, JSDOM selector checks, real-browser visual smoke testing.

**Spec:** `docs/superpowers/specs/2026-08-26-domain-modularization-design.md`

## Global Constraints

- Complete the frontend JavaScript plan first.
- Do not change HTML structure, class names, colors, spacing, typography, transitions, breakpoints, or z-index behavior.
- Do not add preprocessors, PostCSS, Tailwind, bundlers, or dependencies.
- Preserve source-order semantics: declarations moved from `premium.css` must remain after the base declarations they override.
- Run UI checks, browser checks, and Git commands on Aliyun.

---

### Task 1: Lock the CSS Contract

**Files:**
- Create: `frontend/tests/css_contract_check.mjs`
- Read: `frontend/DESIGN.md`
- Read: `frontend/styles.css`
- Read: `frontend/premium.css`

**Interfaces:**
- Produces: a dependency-free source contract for entry files, tokens, selectors, breakpoints, reduced motion, and stacking behavior.

- [ ] **Step 1: Create a CSS source contract before moving rules**

Use `node:assert/strict` and `node:fs/promises`. Read `index.html`, `styles.css`, and `premium.css`, then assert:

```javascript
assert.match(html, /\/department\/styles\.css/)
assert.match(html, /\/department\/premium\.css/)
assert.match(styles, /:root\s*\{/)
assert.match(styles + premium, /\.process-card \.step-card::before/)
assert.match(styles + premium, /\.confirm-dialog/)
assert.match(styles + premium, /\.toast/)
assert.match(styles + premium, /@media \(max-width: 1050px\)/)
assert.match(styles + premium, /@media \(max-width: 900px\)/)
assert.match(styles + premium, /@media \(max-width: 620px\)/)
assert.match(premium, /@media \(prefers-reduced-motion: reduce\)/)
```

Print `css-contract-check: ok`.

- [ ] **Step 2: Run the contract against current CSS**

Run:

```bash
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai/frontend && conda run --no-capture-output -n department-ai node tests/css_contract_check.mjs'
```

Expected: `css-contract-check: ok`.

- [ ] **Step 3: Commit the characterization check**

Commit with:

```text
test: lock frontend CSS contract
```

### Task 2: Extract Tokens, Base, and Layout

**Files:**
- Create: `frontend/css/tokens.css`
- Create: `frontend/css/base.css`
- Create: `frontend/css/layout.css`
- Modify: `frontend/styles.css`
- Modify: `frontend/premium.css`
- Modify: `frontend/tests/css_contract_check.mjs`

**Interfaces:**
- Produces: stable variables, document defaults, and application-shell layout while temporary legacy files retain all not-yet-moved rules.

- [ ] **Step 1: Make the contract expect the first three imports**

Update the check to require this exact prefix in `styles.css`:

```css
@import url("./css/tokens.css");
@import url("./css/base.css");
@import url("./css/layout.css");
```

Run it and expect failure before the imports exist.

- [ ] **Step 2: Move tokens in cascade order**

Move both existing `:root` blocks into `tokens.css`: first the block from `styles.css`, then the later block from `premium.css`. Preserve every custom-property name and value.

- [ ] **Step 3: Move base and layout rules**

Move reset/document typography and native element defaults into `base.css`. Move `.app-shell`, `.sidebar`, `.brand`, navigation, `main`, `.topbar`, `.content`, and assistant-host structural rules into `layout.css`.

Within each destination file, place declarations originating from `premium.css` after the declarations originating from `styles.css` so the current override order is retained.

- [ ] **Step 4: Keep legacy remainder explicit**

After the three imports, `styles.css` temporarily retains all remaining non-moved rules. `premium.css` temporarily retains all remaining premium rules. Do not copy rules; remove each moved block from its source in the same edit.

- [ ] **Step 5: Run CSS and UI checks**

Run `css_contract_check.mjs`, `settings_ui_check.mjs`, and `premium_ui_check.mjs` on Aliyun. Open all six pages at desktop and one narrow viewport; compare shell, navigation, topbar, scrolling, and focus states with the pre-task baseline.

- [ ] **Step 6: Commit**

Commit with:

```text
refactor: extract CSS foundations
```

### Task 3: Extract Components, Features, and Responsive Rules

**Files:**
- Create: `frontend/css/components.css`
- Create: `frontend/css/features.css`
- Create: `frontend/css/responsive.css`
- Modify: `frontend/styles.css`
- Delete: `frontend/premium.css`
- Modify: `frontend/index.html`
- Modify: `frontend/tests/css_contract_check.mjs`
- Modify: `frontend/tests/premium_ui_check.mjs`

**Interfaces:**
- Produces: the final six-file CSS layout behind one `styles.css` entry.
- Preserves: component states, feature-specific layouts, all media queries, and reduced-motion behavior.

- [ ] **Step 1: Update the contract to the final entry shape and verify failure**

The final `styles.css` must be exactly the ordered imports plus a short ownership comment:

```css
@import url("./css/tokens.css");
@import url("./css/base.css");
@import url("./css/layout.css");
@import url("./css/components.css");
@import url("./css/features.css");
@import url("./css/responsive.css");
```

Require that `index.html` has one stylesheet link and no `premium.css` reference. Run the contract and expect failure before extraction.

- [ ] **Step 2: Move reusable component rules**

Move buttons, icon buttons, cards, badges, forms, fields, dialogs, confirmation UI, Toast, loading/empty states, tables/lists, and shared interactive states into `components.css`.

Keep premium-origin overrides after base-origin rules for the same selector. Preserve `:hover`, `:focus-visible`, disabled, invalid, open, and closing states.

- [ ] **Step 3: Move business-feature rules**

Move dashboard, process timeline, category tree, knowledge document/upload/preview, Skill resource editor, assistant iframe, and settings-specific rules into `features.css`.

Keep `.process-card .step-card::before` and its desktop centering declarations together so the existing premium UI assertion remains meaningful.

- [ ] **Step 4: Move all responsive and motion rules**

Move media queries in their current source order into `responsive.css`, preserving these breakpoints exactly:

```text
1200px
1050px
900px
620px
prefers-reduced-motion: reduce
```

Do not merge breakpoints when their original order affects overrides.

- [ ] **Step 5: Remove legacy premium entry**

After both legacy files contain no rules, replace `styles.css` with the six imports, remove the `premium.css` link from `index.html`, delete `premium.css`, and update `premium_ui_check.mjs` to read `css/features.css` for the process-node rule.

- [ ] **Step 6: Run all static/UI checks**

Run on Aliyun:

```bash
node tests/css_contract_check.mjs
node tests/core_modules_check.mjs
node tests/module_boundaries_check.mjs
node tests/settings_ui_check.mjs
node tests/premium_ui_check.mjs
```

Expected: every check reports `ok`.

- [ ] **Step 7: Perform the required real-browser comparison**

Check all six hash routes at desktop and narrow widths. Exercise open/close dialog transitions, form errors, Toast over dialog, process timeline, category scrolling, document preview, Skill resource cards, keyboard focus, and reduced motion. Compare against `frontend/DESIGN.md`; fix only regressions caused by moving CSS.

- [ ] **Step 8: Commit the final CSS split**

Commit with:

```text
refactor: split frontend CSS by responsibility
```

### Task 4: Run End-to-End Completion Verification

**Files:**
- Modify only if a verification failure exposes a real migration regression.

**Interfaces:**
- Consumes: all four modularization plans.
- Produces: evidence that the modularized project preserves current behavior.

- [ ] **Step 1: Run root, backend, and frontend offline checks**

Run every project-owned shell, Python, and Node check on Aliyun, including route and module-boundary checks introduced by these plans.

- [ ] **Step 2: Run online backend checks**

With services running, execute MCP, live admin, and live process checks. Run live preview only with an explicitly selected small test document.

- [ ] **Step 3: Verify final source boundaries**

Expected read-only results:

```text
backend/app/main.py contains no /api business route decorators
frontend/app.js does not exist
frontend/premium.css does not exist
frontend/js/core and frontend/js/ui contain no feature imports
legacy backend modules db.py, schemas.py, knowledge.py, search.py, skills.py, config.py do not exist
```

- [ ] **Step 4: Inspect Git diff and commit only regression fixes**

Do not squash or rewrite unrelated history. If no fixes are needed, create no empty commit.
