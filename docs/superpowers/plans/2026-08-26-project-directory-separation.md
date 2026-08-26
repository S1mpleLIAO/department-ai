# Project Directory Separation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将部门自有前端、后端、Harness 配置和运行数据收拢进 `department-ai/`，使顶层 `deepseek-harness/` 只保留官方源码，同时保持现有页面、API、MCP 和数据不变。

**Architecture:** 前后端在源码目录中分开，FastAPI 继续从兄弟 `frontend/` 目录提供静态页面；根启动脚本从兄弟 `../deepseek-harness/` 启动官方 Harness。迁移先复制、后验证，旧 `department-ai-python/`、旧顶层 `runtime-data/` 和顶层启动脚本在用户确认前不删除。

**Tech Stack:** Python 3.12、FastAPI、Vanilla JavaScript、DeepSeek Harness、POSIX shell、PostgreSQL/pgvector

**Spec:** `docs/superpowers/specs/2026-08-26-project-directory-separation-design.md`

## Global Constraints

- 顶层只规划 `deepseek-harness/` 与 `department-ai/` 两个主要目录，但本次验证完成后仍保留旧目录作为可回滚副本。
- 前端与后端代码分目录，运行时仍由 FastAPI 提供前端静态页面。
- 页面 URL、REST API、MCP 工具名称和数据库结构不变。
- 不复制或修改 Harness 官方源码，不删除 PostgreSQL 数据、文档、Skill 或会话。
- 当前目录不是 Git 仓库，因此用可运行检查和保留旧目录代替每任务 commit。

---

### Task 1: 记录迁移前基线并建立目标目录

**Files:**
- Create: `department-ai/backend/`
- Create: `department-ai/frontend/`
- Create: `department-ai/harness/`
- Create: `department-ai/runtime-data/`
- Create: `department-ai/docs/`

**Interfaces:**
- Consumes: 当前 `department-ai-python/`、`department-ai/`、`runtime-data/` 和运行中的 3080/3081 服务。
- Produces: 可写入但尚未切换的目标目录，以及迁移前 API 数据数量基线。

- [ ] **Step 1: 读取健康状态和业务数量基线**

Run:

```bash
curl --fail --silent http://127.0.0.1:3081/health
curl --fail --silent http://127.0.0.1:3081/api/state
```

Expected: health 为 `ok`；记录流程、目录、文档、用途和 Skill 数量。

- [ ] **Step 2: 停止当前 3080 与 3081 服务**

Run:

```bash
lsof -tiTCP:3080 -sTCP:LISTEN
lsof -tiTCP:3081 -sTCP:LISTEN
```

只终止上述两个已解析 PID，随后再次运行 `lsof`，预期两个端口均无监听。

- [ ] **Step 3: 建立目标目录**

Run:

```bash
mkdir -p department-ai/backend department-ai/frontend department-ai/harness department-ai/docs
```

Expected: 四个目录存在，旧目录内容未删除。

### Task 2: 复制并按职责拆分自有项目

**Files:**
- Copy: `department-ai-python/app/` → `department-ai/backend/app/`
- Copy: Python tests → `department-ai/backend/tests/`
- Copy: `department-ai-python/web/*` → `department-ai/frontend/`
- Copy: Node UI tests → `department-ai/frontend/tests/`
- Copy: `department-ai/cordis.yml` and current Harness docs/scripts → `department-ai/harness/`
- Copy: `runtime-data/` → `department-ai/runtime-data/`
- Copy: project docs → `department-ai/docs/`

**Interfaces:**
- Consumes: Task 1 的空目标目录。
- Produces: 不依赖旧路径即可修改的完整自有项目副本。

- [ ] **Step 1: 复制 Python 后端，排除旧虚拟环境和构建产物**

复制 `app/`、Python 测试、`pyproject.toml`、`.gitignore` 和后端说明；不复制 `.venv/`、`department_ai_python.egg-info/`、`__pycache__/`、`.DS_Store` 或原 `web/`。

- [ ] **Step 2: 复制前端与前端测试**

复制 `index.html`、`app.js`、`styles.css`、`premium.css`、`DESIGN.md`、`premium-audit.json` 和两个 `.mjs` 检查到 `frontend/`。

- [ ] **Step 3: 复制 Harness 配置和运行数据**

将当前 `cordis.yml`、Harness README 和启动逻辑复制进 `harness/`；将顶层 `runtime-data/` 完整复制进 `department-ai/runtime-data/`。保留原数据目录不变。

- [ ] **Step 4: 复制文档并建立统一环境示例**

将现有 `docs/superpowers/` 和 Python 项目文档收拢到 `department-ai/docs/`，以当前 `department-ai/.env.example` 为主并补充数据目录、Skill 目录和 Python 端口说明。

### Task 3: 修改路径和启动链路

**Files:**
- Modify: `department-ai/backend/app/config.py`
- Modify: `department-ai/backend/app/main.py`
- Modify: `department-ai/backend/start.sh`
- Modify: `department-ai/frontend/tests/settings_ui_check.mjs`
- Modify: `department-ai/frontend/tests/premium_ui_check.mjs`
- Modify: `department-ai/harness/start.sh`
- Modify: `department-ai/start.sh`
- Modify: `department-ai/.env.example`

**Interfaces:**
- Consumes: `department-ai/.env`、`department-ai/frontend/`、`department-ai/runtime-data/`、`../deepseek-harness/`。
- Produces: `get_settings()` 使用新根目录；FastAPI 从新前端目录提供页面；一个根脚本启动两项服务。

- [ ] **Step 1: 写路径检查并验证旧实现失败**

在 `backend/tests/self_check.py` 增加断言：`PROJECT_DIR.name == "backend"`、默认数据目录父级位于 `department-ai/runtime-data`、前端目录等于 `PROJECT_DIR.parent / "frontend"`。运行：

```bash
cd department-ai/backend
.venv/bin/python -m tests.self_check
```

Expected: 新虚拟环境尚不存在或路径断言失败。

- [ ] **Step 2: 修改 Python 配置和静态目录**

`config.py` 只读取 `PROJECT_DIR.parent / ".env"`；默认 `data_dir` 为 `PROJECT_DIR.parent / "runtime-data" / "department-ai-python"`，默认 `skill_dir` 为 `PROJECT_DIR.parent / "runtime-data" / "department-skills"`。`main.py` 的 `web_dir` 改为 `Path(__file__).resolve().parents[2] / "frontend"`。

- [ ] **Step 3: 修改前端测试路径**

两个 Node 检查从 `frontend/tests/` 读取 `../index.html`、`../app.js`、`../premium.css`，并从 `../../../deepseek-harness/node_modules/jsdom/lib/api.js` 导入 JSDOM。

- [ ] **Step 4: 修改 Harness 启动脚本**

`harness/start.sh` 从自身父目录得到 `department-ai` 根目录，默认 Harness 为根目录兄弟 `../deepseek-harness`，默认运行数据为根目录 `runtime-data`，overlay 为自身 `cordis.yml`。

- [ ] **Step 5: 修改一键启动脚本**

`department-ai/start.sh` 启动 `backend/start.sh` 和 `harness/start.sh`，沿用 3081/3080 健康检查、PID 精确停止和 Ctrl+C 清理行为。

### Task 4: 重建环境并运行静态检查

**Files:**
- Create: `department-ai/backend/.venv/`（本地运行环境，不纳入源码）
- Modify: `department-ai/README.md`

**Interfaces:**
- Consumes: Task 3 的新路径实现。
- Produces: 可以从新目录独立启动和测试的 Python 环境。

- [ ] **Step 1: 创建虚拟环境并安装后端**

Run:

```bash
cd department-ai/backend
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

Expected: 安装成功，未引用旧 `department-ai-python` 路径。

- [ ] **Step 2: 运行后端和前端静态检查**

Run:

```bash
cd department-ai/backend
.venv/bin/python -m tests.self_check
cd ../frontend
node tests/settings_ui_check.mjs
node tests/premium_ui_check.mjs
```

Expected: 三项检查全部通过。

- [ ] **Step 3: 更新使用文档**

README 只给出 `cd department-ai && ./start.sh` 的日常启动命令，说明官方 Harness 位于兄弟目录，前后端代码分开但由同一 FastAPI 服务提供。

### Task 5: 启动新结构并做端到端验收

**Files:**
- Verify: `department-ai/start.sh`
- Verify: `department-ai/runtime-data/`
- Verify: `department-ai/backend/tests/`
- Verify: `department-ai/frontend/tests/`

**Interfaces:**
- Consumes: 完整的新目录项目。
- Produces: 运行于 3081/3080 的新结构，以及与迁移前一致的数据和功能。

- [ ] **Step 1: 从新项目根启动全部服务**

Run:

```bash
cd department-ai
./start.sh
```

Expected: Python 管理服务和 Harness 均报告已就绪。

- [ ] **Step 2: 运行服务与 MCP 回归**

Run:

```bash
curl --fail http://127.0.0.1:3081/health
cd department-ai/backend
.venv/bin/python -m tests.mcp_check
.venv/bin/python -m tests.live_admin_check
.venv/bin/python -m tests.live_process_check
```

Expected: health 为 `ok`，三项端到端检查通过并清理测试数据。

- [ ] **Step 3: 验证知识入库与检索**

使用现有受管理 `.docx` 运行 `tests.live_preview_check`，预期 Docling 解析、重新分块、向量入库、知识检索和测试数据清理全部成功。

- [ ] **Step 4: 比较迁移前后业务数据**

重新读取 `/api/state`，预期流程、目录、文档、用途和 Skill 数量与 Task 1 一致；检查 `department-ai/runtime-data/department-skills` 与 `dsh-home/.agent-presets/department` 存在。

- [ ] **Step 5: 保留旧副本并交付**

不删除 `department-ai-python/`、顶层 `runtime-data/`、顶层 `start.sh` 或旧文档。向用户说明新启动命令和旧副本位置，等待单独授权后再清理。
