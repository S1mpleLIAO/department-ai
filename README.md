# 部门 AI

## 当前版本：统一登录与公司隔离

当前代码包含统一登录、自定义权限组、公司空间隔离、审核发布及个人 Harness。个人 AI 按需启动，实例上限可配置；会话、模型配置和工作区文件持久化。

此版本使用 `backend/identity_server.py check/serve --env-file <私有配置文件>`，先完成显式数据库迁移和部署预检，再启动服务。旧的一键部署、共享 Harness 启动方式不适用于此版本，相关脚本会拒绝启动。项目运行、测试和 Git 操作按 `AGENTS.md` 在阿里云执行。

- 合并范围与现网状态：[本次合并说明](docs/identity-main-merge.md)
- 部署及迁移顺序：[身份版本部署准备](docs/identity-deployment-stage.md)
- 专用运行账号、容器代理与存储管理：[宿主权限收敛](docs/assistant-hardening-stage.md)
- 原生个人模型设置：[验收接入说明](docs/assistant-personalization-acceptance.md)
- 部门助手、技能执行及文件下载：[能力恢复说明](docs/department-capabilities-restoration.md)

代码合并不代表生产数据库迁移或公网切换已完成。历史阶段文档中的能力限制以对应最新专题文档为准。

## 旧共享版本说明（历史参考，不用于当前版本部署）

部门自有代码、配置和运行数据统一保存在本目录；兄弟目录 `../deepseek-harness/` 只保存官方 Harness 源码。

```text
department-ai/
├── backend/        FastAPI、REST API、MCP 与知识检索
├── frontend/       管理页面静态资源
├── harness/        部门助手 overlay 与 preset
├── runtime-data/   文档、Skill、会话与预览数据
├── docs/           设计与实施文档
├── .env            本机私有配置
└── start.sh        一键启动全部服务
```

## 启动

第一次迁移或重新创建环境：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai/backend"
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

日常使用：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai"
./start.sh
```

- 管理页面：<http://127.0.0.1:3081/department>
- API 文档：<http://127.0.0.1:3081/docs>
- MCP：<http://127.0.0.1:3081/mcp>
- AI 助手：<http://127.0.0.1:3080/>

前端和后端代码已经分开，但前端仍由 FastAPI 提供，不需要额外启动前端服务。

## Ubuntu 服务器部署（Conda，不使用 Docker）

服务器目录约定：

```text
/root/liao/DepartmentKnowledgeBase/
├── department-ai/
└── deepseek-harness/
```

确认 `department-ai/.env` 已安全配置后，首次部署执行：

```bash
cd /root/liao/DepartmentKnowledgeBase/department-ai
chmod +x ./*.sh backend/start.sh harness/start.sh
./deploy-server.sh
```

脚本会创建独立的 `department-ai` Conda 环境、构建服务器当前检出的 Harness、
按 Linux x86_64 重新安装插件、运行自检并后台启动。它不会激活或修改现有
`base` 环境，也不会对 Harness 执行 `fetch`、升级或回退。

成功状态记录在 `runtime-data/deploy-state/`。Conda 环境、pnpm、Python 依赖、
Harness 源码和插件清单没有变化时会直接跳过对应步骤；依赖文件或 Harness
提交变化时才重新安装或构建。

日常管理：

```bash
./start-background.sh  # 后台启动
./stop-server.sh       # 停止
./restart-server.sh    # 重启
./status-server.sh     # 状态
./logs-server.sh       # 实时日志
```

如果只部署、不立即启动：

```bash
DEPARTMENT_SKIP_START=1 ./deploy-server.sh
```

## Harness 升级

当前已验证版本见 `harness/HARNESS_VERSION`。升级时将官方新版本克隆到临时目录，通过 `DEPARTMENT_HARNESS_DIR` 指向新版做兼容性测试。验证通过后只替换兄弟目录 `deepseek-harness/`；本目录的业务代码、配置、Skill 和运行数据不会被覆盖。
