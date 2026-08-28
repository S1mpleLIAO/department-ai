# Harness Public Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the public Harness URL for browsers while using loopback health checks and proxying all Harness file/plugin routes needed for preview and download.

**Architecture:** The Department UI keeps `/department` and its known API prefixes on port 3081. The exact domain root remains unavailable, while every otherwise-unmatched request is forwarded by Nginx to loopback port 3080 with the trusted upstream Host/Origin and WebSocket headers. Backend settings separate the browser-facing URL from the internal health URL.

**Tech Stack:** FastAPI, Python dataclasses/urllib, Nginx, DeepSeek Harness

**Spec:** `docs/architecture.md` plus the user-approved routing design in this task.

## Global Constraints

- Execute tests, service restarts, Nginx operations, and Git commands only on Aliyun.
- Keep ports 3080 and 3081 bound to `127.0.0.1`.
- Do not expose server directories with an Nginx `alias`; downloads remain controlled by Harness.
- Do not change REST contracts or database schemas.

---

### Task 1: Separate browser and health-check URLs

**Files:**
- Modify: `backend/tests/self_check.py`
- Modify: `backend/app/core/config.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/features/dashboard/router.py`
- Modify: `.env`
- Modify: `.env.example`

**Interfaces:**
- Consumes: `DEPARTMENT_HARNESS_URL` for the browser-facing iframe URL.
- Produces: `Settings.harness_health_url: str`, loaded from `DEPARTMENT_HARNESS_HEALTH_URL` with a loopback default.

- [x] Add a self-check that independently supplies different public and loopback URLs and expects both settings to remain distinct.
- [x] Run `cd backend && /root/anaconda3/envs/department-ai/bin/python -m tests.self_check` on Aliyun and confirm it fails because `harness_health_url` does not exist.
- [x] Add `harness_health_url` to `Settings`, use it in both health checks, and document/configure the environment variable.
- [x] Run the self-check again and confirm it passes.

### Task 2: Forward Harness auxiliary and download routes

**Files:**
- Modify on server: `/etc/nginx/conf.d/api-ip.conf`

**Interfaces:**
- Consumes: all domain requests not claimed by `/department` or the Department API regex.
- Produces: forwarding to `http://127.0.0.1:3080` with trusted Host/Origin, WebSocket upgrade, and streaming enabled.

- [x] Record the failing public probe for `POST /sidebar/api/fs.tree` and the working direct-upstream response.
- [x] Change the domain root rule to exact-match `/` and add the Harness catch-all proxy.
- [x] Back up the installed configuration, run `nginx -t`, and reload only after validation.
- [x] Confirm `/sidebar/api/fs.tree`, `/_dsh/*`, file/plugin routes, and Harness WebSocket upgrades reach port 3080 instead of the Nginx 404 fallback.

### Task 3: Restart and verify end to end

**Files:**
- No additional files.

**Interfaces:**
- Consumes: Tasks 1 and 2.
- Produces: green dashboard health plus working public Harness file/plugin transport.

- [x] Restart the Department service with `restart-server.sh` on Aliyun.
- [x] Run the complete backend checks used by the project.
- [x] Verify `/api/state` reports `harness: true` and retains the public Harness URL.
- [x] Verify the public Department page, Harness entry, Files API, plugin route, and Nginx configuration.
