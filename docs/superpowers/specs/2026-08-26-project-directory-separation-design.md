# 部门 AI 与 DeepSeek Harness 目录隔离设计

## 目标

将官方 DeepSeek Harness 源码与部门 AI 自有代码、配置和数据彻底隔离，避免 Harness 升级覆盖业务内容；同时将前端与后端代码分目录维护，但暂时保持单一 Web 服务，避免引入额外部署复杂度。

## 最终目录

```text
Department Knowledge Base/
├── deepseek-harness/          # 官方源码，只负责安装、编译和升级
└── department-ai/             # 部门自有项目
    ├── backend/               # FastAPI、REST API、MCP、数据库与检索逻辑
    │   ├── app/
    │   ├── tests/
    │   ├── pyproject.toml
    │   └── start.sh
    ├── frontend/              # 管理页面静态资源与前端测试
    │   ├── index.html
    │   ├── app.js
    │   ├── styles.css
    │   ├── premium.css
    │   └── tests/
    ├── harness/               # 部门助手的 Harness overlay 和 preset 配置
    │   ├── cordis.yml
    │   └── presets/
    ├── runtime-data/          # 文档、预览、Skill、DSH_HOME 与会话数据
    ├── docs/
    ├── .env                   # 部门项目统一环境配置
    ├── .env.example
    ├── README.md
    └── start.sh               # 一键启动 Python 服务与 Harness
```

顶层只保留两个主要目录。`deepseek-harness/` 不存放任何部门业务代码或运行数据；`department-ai/` 不复制 Harness 官方源码。

## 组件边界

### Backend

`backend/` 管理 FastAPI、REST API、MCP、PostgreSQL/pgvector、Docling、硅基流动接口和知识检索。它通过配置定位 `frontend/`、`runtime-data/` 和 Harness 地址，不依赖 Harness 源码内部模块。

### Frontend

`frontend/` 只包含 HTML、CSS、JavaScript 和前端检查。浏览器继续访问 FastAPI 的 `/department`，由 FastAPI 托管该目录的静态资源；不新增 Vite、React、独立前端端口或 CORS 配置。

### Harness 配置

`harness/` 只保存部门助手 overlay、preset 和启动适配配置。启动时通过绝对计算出的项目路径加载 `deepseek-harness/`，并把 `DSH_HOME`、Skill 目录和 MCP 地址指向 `department-ai/`。

### Runtime data

`runtime-data/` 保存所有不可随源码升级丢失的数据，包括已上传文档、入库预览、部门 Skill、Harness 会话和本地交付物。数据库数据仍保存在 PostgreSQL，不因目录迁移而变更。

## 运行方式

用户仍只执行：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai"
./start.sh
```

启动脚本负责：

1. 启动 `backend/` 的 FastAPI 服务，默认端口 `3081`。
2. 从兄弟目录 `../deepseek-harness/` 启动官方 Harness，默认端口 `3080`。
3. 将部门 overlay、`DSH_HOME`、Skill 目录和 MCP 地址显式传给 Harness。

页面地址保持不变：

- 管理页面：`http://127.0.0.1:3081/department`
- AI 助手：`http://127.0.0.1:3080/harness`
- MCP：`http://127.0.0.1:3081/mcp`

## 配置规则

- 唯一主配置文件为 `department-ai/.env`。
- 后端不再回退读取旧的 `department-ai-python/.env` 或旧 Harness 配置目录。
- 所有数据目录从项目根目录推导，也允许通过现有环境变量覆盖。
- 不在代码中写死某个 Harness 版本目录；默认使用 `../deepseek-harness`，测试新版时可用 `DEPARTMENT_HARNESS_DIR` 临时覆盖。

## 迁移策略

迁移采用“复制验证后切换”，避免直接移动导致无法回滚：

1. 停止当前 Python 与 Harness 服务，记录端口和数据目录状态。
2. 备份 `.env`、`runtime-data/` 和数据库连接配置。
3. 在新的 `department-ai/` 结构中整理后端、前端、Harness 配置、文档和运行数据。
4. 不搬运旧 `.venv`；在 `backend/` 重新创建虚拟环境并安装当前项目。
5. 修改 FastAPI 静态目录、启动脚本、配置默认路径和测试引用。
6. 用新目录启动服务，完成健康检查和端到端回归。
7. 验证现有流程、文档、向量、Skill、会话和 AI 助手均可访问。
8. 验证完成前保留旧目录；切换成功后再由用户确认是否清理旧副本。

迁移过程不删除 PostgreSQL 数据、知识库原文件、Skill 或 Harness 会话。

## 验证标准

- 根目录的自有项目内容全部位于 `department-ai/`，Harness 官方源码只位于 `deepseek-harness/`。
- `department-ai/start.sh` 可以一键启动两个服务。
- FastAPI 健康检查、管理页面、MCP 和 Harness 页面均正常。
- 现有 Python 自检、MCP、业务流程、管理接口、知识入库与检索测试通过。
- 前端设置页与弹窗测试通过，页面静态资源可以正常加载。
- 原有业务流程、目录、文档、向量索引、Skill 和会话数量在迁移前后保持一致。
- 使用另一份 Harness ZIP 配置 `DEPARTMENT_HARNESS_DIR` 后，可以在不修改 `department-ai/` 的情况下进行兼容性测试。

## 升级方式

以后升级 Harness 时：

1. 将新版 ZIP 解压到临时兄弟目录。
2. 通过 `DEPARTMENT_HARNESS_DIR` 使用新版启动。
3. 运行 MCP、部门 preset、文件上传、Skill 和对话回归。
4. 验证通过后再替换 `deepseek-harness/`。

整个升级过程不修改 `department-ai/`，也不移动 `runtime-data/`。

## 暂不实施

- 不把前端拆成独立服务。
- 不引入 React、Vue、Vite 或新的包管理体系。
- 不改变 REST API、MCP 工具名称、数据库结构或页面 URL。
- 不在本次迁移中重构业务模块内部代码。
