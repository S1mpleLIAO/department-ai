# Unified Skill Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Manage Harness-created and manually-created full skill bundles from one shared directory.

**Architecture:** Extend the existing filesystem-backed `app.skills` service with safe resource operations for `scripts`, `references`, and `assets`. Keep `SKILL.md` and the shared directory as the source of truth; the existing vanilla-JS editor stages uploads/deletions and applies them after the skill save.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, vanilla JavaScript, CSS, Node/JSDOM checks.

**Spec:** `docs/superpowers/specs/2026-08-25-unified-skill-management.md`

## Global Constraints

- No new runtime dependency.
- Preserve the existing REST, MCP, knowledge, and process behavior.
- Preserve the Apple Liquid Glass design tokens in `DESIGN.md`.
- Resource paths are restricted to `scripts/`, `references/`, and `assets/`.

---

### Task 1: Skill bundle resource service

**Files:**
- Modify: `tests/self_check.py`
- Modify: `app/skills.py`
- Modify: `app/schemas.py`

**Interfaces:**
- Produces: `save_skill_resource`, `read_skill_resource`, `delete_skill_resource`; skill payload field `resources`.

- [ ] Add a failing self-check that creates text and binary resources, lists them, rejects traversal, preserves extra frontmatter, and deletes one resource.
- [ ] Run `python -m tests.self_check` and confirm the new assertions fail because resource functions are absent.
- [ ] Implement path validation and the minimum resource operations with Python standard library APIs.
- [ ] Run the self-check and confirm it passes.

### Task 2: REST resource API

**Files:**
- Modify: `tests/live_admin_check.py`
- Modify: `app/main.py`
- Modify: `app/schemas.py`

**Interfaces:**
- Produces: `PUT/GET/DELETE /api/skills/{skill_id}/resources/{resource_path:path}`.

- [ ] Extend the live check to upload, download, list, and delete a resource through the real API.
- [ ] Run the live check against the old service and confirm the resource route returns 404.
- [ ] Add base64 resource input and the three routes with the existing `StoreError` handling.
- [ ] Re-run the live check after service restart.

### Task 3: Skill editor resource management

**Files:**
- Modify: `tests/premium_ui_check.mjs`
- Modify: `web/app.js`
- Modify: `web/styles.css`
- Modify: `web/premium.css`
- Modify: `web/index.html`

**Interfaces:**
- Consumes: resource entries `{path, kind, name, size, updatedAt}` and REST resource routes.

- [ ] Add failing JSDOM assertions for the three resource cards, resource counts, queued file upload, and accessible file controls.
- [ ] Run the UI check and confirm it fails because the resource manager does not exist.
- [ ] Add the resource cards and stage uploads/deletions in the existing editor without creating another modal system.
- [ ] Add minimal responsive styles derived from existing skill sections and update asset cache versions.
- [ ] Re-run the UI checks.

### Task 4: Harness authoring contract and verification

**Files:**
- Modify: `../runtime-data/dsh-home/.agent-presets/department/agent.cordis.yml`
- Modify: `README.md`

**Interfaces:**
- Produces: a documented direct-file authoring contract targeting `DEPARTMENT_SKILL_DIR`.

- [ ] Add a focused preset rule for explicit skill-authoring requests: use an available skill-creation skill, request permission when needed, write resources before `SKILL.md`, and never overwrite without confirmation.
- [ ] Document the shared directory and manual/AI management flow.
- [ ] Run Python checks, JSDOM checks, strict premium audit, and a browser workflow covering create/edit/resource upload/resource delete.
