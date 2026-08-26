# Project Instructions

## Execution environment

This workspace is mounted from the Aliyun server directory:
`/root/liao/DepartmentKnowledgeBase/department-ai`.

The corresponding mounted workspace on the Mac is:
`/Volumes/DepartmentKnowledgeBase/department-ai`.

- Read, search, and edit ordinary project files directly through the mounted workspace. Treat those edits as writes to the Aliyun server.
- By default, run project execution, dependency installation, tests, builds, Docker operations, database operations, and all Git commands on Aliyun with:
  `ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && ...'`
- This remote-execution requirement also applies to read-only Git commands such as `git status` and `git diff`.
- Never run the command categories above on the Mac unless the user explicitly authorizes the specific local execution.
- When operating in an isolated worktree, use that active worktree's corresponding Aliyun path and never execute against another checkout.
- Before running the first project command in a task, state that the command will run on Aliyun.
- If SSH execution is unavailable, stop and report the problem. Do not silently fall back to local execution.
- Do not move, copy, archive, unpack, hash, or batch-process large archives, build outputs, or binary files in the mounted directory unless the user explicitly requests it.

## Architecture boundaries

- Organize new business functionality under the matching backend and frontend feature domain.
- Keep `backend/app/main.py` limited to application composition, lifespan, health/portal endpoints, router registration, and mounts.
- Keep `frontend/js/main.js` limited to startup, hash routing, page registration, and initial state loading.
- Create a shared module only after at least two business domains need the same behavior.
- Shared `core` and `ui` modules must not import concrete feature modules.
- Do not mix REST contract changes, database schema changes, or cross-domain architecture changes into an ordinary feature change; design those separately first.
