# Project Instructions

## Production deployment

- The department portal, login and permissions, personal AI gateway and runtimes, and all live application data are on `huairouCPU` (`192.168.11.7`). Its PostgreSQL database is the source of truth for production reads and writes.
- For this project, Aliyun (`121.43.245.245`) serves only as the public HTTPS reverse proxy. Its Nginx terminates TLS. The internal server initiates and maintains the reverse SSH tunnel via `department-reverse-tunnel.service`.

| Public entry | Aliyun loopback endpoint | Service on huairouCPU |
| --- | --- | --- |
| `https://supercomputing7.xyz/department` and the portal's `/api/` requests | `127.0.0.1:23081` | Portal and API at `127.0.0.1:3081` |
| `https://ai-shared.supercomputing7.xyz` | `127.0.0.1:23182` | AI gateway for all company spaces at `127.0.0.1:3182` |

- On Aliyun, the former `department-identity.service` is stopped and disabled. The old PostgreSQL database is retained for historical reference. Direct all current business operations to the internal deployment.

## Execution environment

- The active service runs on the internal server `gpu-master-02`. The SSH alias `huairouCPU` connects to this server at `192.168.11.7`. Connect with `ssh root@huairouCPU` (or `ssh huairouCPU` when its configured user is root).
- The project collection is `/root/liao/DepartmentKnowledgeBase`. The department-ai project and the verified systemd working directory are `/root/liao/DepartmentKnowledgeBase/department-ai`. The sibling `deepseek-harness` directory is a separate project.
- Before the first project command, state that it will run on the internal server. Run project execution, dependency installation, tests, builds, Docker and database operations, and all Git commands (including status and diff) there, normally with `ssh root@huairouCPU 'cd /root/liao/DepartmentKnowledgeBase/department-ai && ...'`.
- The current Mac workspace `/Volumes/DepartmentKnowledgeBasehuairou/department-ai` is mounted from `huairouCPU:/root/liao/DepartmentKnowledgeBase/department-ai`. Read, search, and edit ordinary project files directly in this workspace. Changes write back to the internal server.
- The SSHFS mount maps `huairouCPU:/root/liao/DepartmentKnowledgeBase` to `/Volumes/DepartmentKnowledgeBasehuairou`, using `backend=fskit`, `reconnect`, `ServerAliveInterval=15`, and `ServerAliveCountMax=3`. Its log is `~/sshfs-department.log` on the Mac.
- Mount access permits ordinary file operations. Continue running project execution, dependency installation, tests, builds, Docker, database operations, and every Git command on the internal server over SSH.
- The older Mac path `/Volumes/DepartmentKnowledgeBase/department-ai` was the Aliyun workspace. Verify its mount source before using it for this project.
- Git 提交说明和 GitHub 操作说明使用中文。
- Make changes directly in the main project directory on the `main` branch. Use this checkout for code, Git, and verification. Create a separate branch, worktree, or isolated environment only when the user explicitly asks.
- If the internal SSH connection is unavailable, stop and report it. Use Aliyun only when specifically requested for HTTPS forwarding, its end of the tunnel, historical comparisons, or migration work. Do not run project commands on the Mac without explicit authorization for that local execution.
- Keep production data and personal Harness homes intact. Use read-only checks for live business data. Use explicit test accounts or records when the user requests a write-based live test. Do not move, copy, archive, unpack, hash, or batch-process large archives, build outputs, or binary files in a mounted workspace unless explicitly requested.

## Architecture boundaries

- Organize new business functionality under the relevant backend and frontend feature domains described in `docs/architecture.md`; domain names need not match one-to-one.
- Keep `backend/app/main.py` limited to application composition, lifespan, health/portal endpoints, router registration, and mounts.
- Keep `frontend/js/main.js` limited to startup, hash routing, page registration, and initial state loading.
- Create a shared module only after at least two business domains need the same behavior.
- Shared `core` and `ui` modules must not import concrete feature modules.
- Do not mix REST contract changes, database schema changes, or cross-domain architecture changes into an ordinary feature change; design those separately first.
