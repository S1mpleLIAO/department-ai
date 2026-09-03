# 部门 AI Python 后端

这是部门 AI 的管理页面、REST API、知识库逻辑和 MCP 服务。业务功能已经从原 TypeScript 插件迁移到这里：

- 管理门户：`http://127.0.0.1:3081/department`
- Python API 文档：`http://127.0.0.1:3081/docs`
- Python MCP：`http://127.0.0.1:3081/mcp`
- DeepSeek Harness：`http://127.0.0.1:3080/harness`

管理门户通过 iframe 嵌入 Harness 对话页面；Harness 通过 MCP 调用这里的流程、模板和知识检索能力。

## 第一次安装

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai/backend"
python3 -m venv .venv
.venv/bin/python -m pip install -e .
```

程序读取部门项目根目录的 `../.env`。前端位于兄弟目录 `../frontend/`，由本服务提供静态页面。

## 一键启动整个项目

在项目根目录运行：

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai"
./start.sh
```

脚本会依次启动 Python 管理服务和 DeepSeek Harness。管理页面地址为
`http://127.0.0.1:3081/department`，按 `Ctrl+C` 可停止本次由脚本启动的服务。

## 单独启动 Python 服务

```bash
cd "/Users/liao/Desktop/Department Knowledge Base/department-ai/backend"
./start.sh
```

验证：

```bash
curl http://127.0.0.1:3081/health
curl http://127.0.0.1:3081/api/state
.venv/bin/python -m tests.mcp_check
```

浏览器接口说明：<http://127.0.0.1:3081/docs>

DeepSeek Harness 使用的 MCP 地址：<http://127.0.0.1:3081/mcp>

管理门户：<http://127.0.0.1:3081/department>

MCP 由官方 Python SDK 提供，并与 REST API 共用同一个进程和数据库连接池。目前公开六个只读工具：

- `department_context_get`：读取管理员在系统设置中维护的助手定位、工作原则和回答默认项
- `document_read`：通过 Docling 读取用户本轮上传到 `uploads/` 目录的 Office、PDF 或文本文件
- `process_list`：读取真实业务流程和步骤标准
- `template_search`：混合召回并重排真实生成模板
- `template_get`：用户确认后读取所选模板正文
- `knowledge_search`：检索参考知识分块及父块上下文

## 当前接口

- `GET /health`：数据库、Docling、DeepSeek Harness 的实时状态，以及硅基流动模型配置状态
- `GET /api/processes`：业务流程和步骤
- `POST /api/processes`：新建业务流程和步骤
- `PUT /api/processes/{id}`：编辑业务流程，步骤数组顺序就是显示顺序
- `DELETE /api/processes/{id}`：删除业务流程及其步骤
- `GET /api/categories`：知识目录
- `POST /api/categories`：新建目录，自动排在同级末尾
- `PUT /api/categories/{id}`：重命名或移动目录
- `PUT /api/categories/order`：调整同级目录顺序
- `DELETE /api/categories/{id}`：删除空目录
- `GET /api/purposes`：读取可自定义的文档用途及其索引能力
- `POST /api/purposes`：新增文档用途，ID 由后端自动生成
- `PUT /api/purposes/{id}`：修改用途说明、模板能力和默认分块规则
- `DELETE /api/purposes/{id}`：删除尚未被文档使用的用途
- `GET /api/documents`：文档元数据、分块数和索引状态
- `GET /api/documents/{id}/source`：下载文档原文件
- `PUT /api/documents/{id}`：编辑文档元数据、目录和模板属性
- `POST /api/documents/{id}/reindex`：使用当前模型重建文档与正文分块向量
- `GET /api/settings`、`PUT /api/settings`：读取和保存助手规则及知识库设置
- `GET /api/skills`：列出部门专用 Skill
- `POST /api/skills`：用英文 kebab-case 名称创建原生 `SKILL.md` Skill
- `PUT /api/skills/{name}`：编辑、重命名或启停 Skill
- `DELETE /api/skills/{id}`：删除 Skill
- `PUT /api/skills/{id}/resources/{path}`：上传 `scripts/`、`references/` 或 `assets/` 资源
- `GET /api/skills/{id}/resources/{path}`：下载 Skill 资源
- `DELETE /api/skills/{id}/resources/{path}`：删除 Skill 资源
- `POST /api/knowledge/preview`：解析文件、生成分块预览和 AI 元数据建议
- `POST /api/knowledge/previews/{id}/rechunk`：调整设置后重新分块
- `POST /api/knowledge/previews/{id}/index`：确认元数据、生成向量并正式入库
- `DELETE /api/knowledge/previews/{id}`：取消入库并清理临时文件
- `GET /api/documents/{id}`：读取文档正文、元数据和分块
- `DELETE /api/documents/{id}`：删除数据库记录和受管理的原文件
- `POST /api/search/templates`：元数据过滤、混合召回、Rerank 后推荐真实模板
- `POST /api/search/knowledge`：检索正文分块并返回父块上下文和相关文档卡片
- `GET /api/state`：一次返回上述数据和知识库设置

知识入库预览会保存在 `../runtime-data/department-ai-python/previews/`。取消入库时会立即清理；服务启动时也会自动清理超过 24 小时的遗留预览文件。

文档用途决定索引策略：所有文档都会保存标题、摘要、关键词、目录、正文和原始文件，并建立文档级目录索引；用途可以额外开启“整份模板推荐”和“正文分块检索”。用途可继承系统默认分块设置，也可维护自己的分块规则。模板检索不再按业务流程或步骤做硬过滤，业务流程只用于判断当前任务阶段和检查交付要求。

部门 Skill 保存在 `../runtime-data/department-skills/`。每个 Skill 都是 Harness 原生 bundle：`<name>/SKILL.md` 是入口，按需附带 `scripts/`、`references/` 和 `assets/`。frontmatter 使用英文 kebab-case `name` 和路由用 `description`；执行步骤与资源相对路径写在 Markdown 正文中。部门预设只加载这个目录并监听变更，因此升级或替换官方 Harness 源码不会覆盖这些 Skill。

管理页面人工创建和部门助手创建共用同一个目录。`department_context_get` 会把实际目录和 bundle 规则提供给模型；用户明确要求创建或修改 Skill 时，助手先读取 `skill-creator`，使用文件工具先写文本资源、最后写 `SKILL.md`，保存后页面会自动列出。由于 Harness 的文件工具按当前会话工作区隔离，首次写入外部部门 Skill 目录时会请求用户批准，这是预期的权限保护。

管理页面支持上传脚本、参考资料和二进制模板等资源。当前部门助手的文件工具只编写文本文件，也没有启用脚本执行能力；Office 模板、图片等二进制资源应从“技能”页面上传，`scripts/` 中的程序在增加受控执行沙箱前仅作为资源保存。
