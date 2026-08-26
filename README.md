# 部门 AI

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
- AI 助手：<http://127.0.0.1:3080/harness>

前端和后端代码已经分开，但前端仍由 FastAPI 提供，不需要额外启动前端服务。

## Harness 升级

将新版 ZIP 解压到临时目录，通过 `DEPARTMENT_HARNESS_DIR` 指向新版做兼容性测试。验证通过后只替换兄弟目录 `deepseek-harness/`；本目录的业务代码、配置、Skill 和运行数据不会被覆盖。
