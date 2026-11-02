# Harness identity feasibility probe

This is a disposable integration experiment, **not production authentication**.
It uses the installed Harness source, tsx and frontend assets read-only. It never
loads the department `.env`, production DSH home, database or model credentials.
No dependency installation, image pull, production restart or Nginx edit occurs.

Run from the Mac only through SSH:

```sh
ssh aliyun 'cd /root/liao/DepartmentKnowledgeBase/department-ai && /root/anaconda3/envs/department-ai/bin/python -B harness/tests/identity_probe/run.py'
```

Requirements: the existing Node 22 installation and installed Harness checkout
at the paths in `run.py`; Docker; existing `pgvector/pgvector:0.8.6-pg17-bookworm`
image. This image supplies an existing Debian filesystem only: its entrypoint is
overridden with Node, and **PostgreSQL is never started**. It is not the proposed
production AI image.

Each instance runs as UID 10001, with a read-only root filesystem and code mounts,
all Linux capabilities dropped, no-new-privileges, no host ports and `network=none`.
Only its generated home and `/tmp` are writable. Each has 640 MiB memory, no extra
swap, 0.5 CPU and 128 PIDs. At most two instances run together. Free-memory checks
stop the experiment if there is not enough headroom; they are not a load test or
a guarantee against changing production load. Do not run during a load peak.

`run.py` creates private `/tmp/department-identity-probe-*` artifacts on Aliyun.
It stops/removes only the containers it created in `finally`, retaining isolated
homes and redacted logs/results for inspection. Tokens and cookies are kept in
memory and are not printed. Test homes contain disposable signing credentials;
do not publish those directories. After an abrupt host/process interruption,
inspect containers with label `department.identity-probe=true` and remove only
the specific leftover probe names after confirming their ownership.

Coverage:

- Separate users' real session creation/rename/list and persisted locale settings.
- Same user routed to two distinct space runtimes using a trusted fixture identity.
- Real authenticated file download, denied host paths, raw filesystem/network boundaries.
- Launch-token exchange, invalid/expired/cross-runtime cookie rejection.
- In-memory server-side broker refreshing auth before one mutation; deny unknown
  identity/space and non-allowlisted RPC. No blind replay of mutations.
- Real WebSocket mux `$events` readiness and heartbeat with an injected upstream cookie.
- Restart with persistent home, cookie-signing continuity, new launch token, retained data.

Important limits:

- The broker is a Python test adapter transporting requests via `docker exec`, not
  an HTTP reverse proxy or real login service. Its identities are fixtures.
- No browser iframe, DNS, TLS, shared-origin cookie, full frontend or three-origin
  multi-tab test is performed here.
- No model calls, actual MCP authorization/revocation, document-tool execution,
  long answer stream, production sandbox nesting, load test or adversarial sandbox
  escape audit is performed.
- Direct settings APIs and arbitrary-file download remain native owner capabilities.
  A test records native access to the **test** credential file as a security finding;
  “all tests passed” does not mean the application is safe for untrusted users.
- Real gateway authorization must protect HTTP **and each WebSocket mux frame**, plus
  AI tools, filesystem, network and MCP. A login screen alone is insufficient.
