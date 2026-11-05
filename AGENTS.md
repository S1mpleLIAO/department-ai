# Project Instructions

## Execution environment

- The active service runs on the internal server `gpu-master-02`. Connect with `ssh root@huairouCPU`. The service VIP is `192.168.11.7`.
- The project collection is `/root/liao/DepartmentKnowledgeBase`. The department-ai project and the verified systemd working directory are `/root/liao/DepartmentKnowledgeBase/department-ai`. The sibling `deepseek-harness` directory is a separate project.
- Before the first project command, state that it will run on the internal server. Run project execution, dependency installation, tests, builds, Docker and database operations, and all Git commands (including status and diff) there, normally with `ssh root@huairouCPU 'cd /root/liao/DepartmentKnowledgeBase/department-ai && ...'`.
- Read and edit active service files over SSH, or through a mount whose source has been verified as this server and project. The existing Mac path `/Volumes/DepartmentKnowledgeBase/department-ai` was the Aliyun workspace. A matching directory name does not establish that the mount points to the new server.
- Make changes directly in the main project directory on the `main` branch. Use this checkout for code, Git, and verification. Create a separate branch, worktree, or isolated environment only when the user explicitly asks.
- If the internal SSH connection is unavailable, stop and report it. Use Aliyun only when specifically requested for historical comparisons or migration work. Do not run project commands on the Mac without explicit authorization for that local execution.
- Keep production data and personal Harness homes intact. Use read-only checks for live business data. Use explicit test accounts or records when the user requests a write-based live test. Do not move, copy, archive, unpack, hash, or batch-process large archives, build outputs, or binary files in a mounted workspace unless explicitly requested.

## Architecture boundaries

- Organize new business functionality under the relevant backend and frontend feature domains described in `docs/architecture.md`; domain names need not match one-to-one.
- Keep `backend/app/main.py` limited to application composition, lifespan, health/portal endpoints, router registration, and mounts.
- Keep `frontend/js/main.js` limited to startup, hash routing, page registration, and initial state loading.
- Create a shared module only after at least two business domains need the same behavior.
- Shared `core` and `ui` modules must not import concrete feature modules.
- Do not mix REST contract changes, database schema changes, or cross-domain architecture changes into an ordinary feature change; design those separately first.
