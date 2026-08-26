# Department AI 业务域模块化重构设计

日期：2026-08-26  
状态：已确认，待实施计划

## 背景

项目功能已经完整覆盖部门流程、知识库、Skill 管理、系统设置和 AI 助手，但部分文件承担了过多职责：

- `backend/app/main.py` 同时负责应用生命周期、静态页面、健康检查和全部 REST 路由。
- `backend/app/db.py` 同时负责流程、目录、文档、检索和设置的数据访问。
- `backend/app/schemas.py` 集中维护所有业务域的输入模型。
- `frontend/app.js` 同时负责请求、状态、路由、公共交互和全部页面渲染。
- `frontend/styles.css` 与 `frontend/premium.css` 混合基础样式、布局、组件和页面样式。

当前主要问题不是功能缺失，而是新增功能时难以快速定位改动位置，且大文件会持续增加耦合。此次重构采用按业务域渐进拆分，不重写项目。

## 目标

1. 新增功能时可以根据业务域快速找到后端、前端和测试入口。
2. 缩小单次修改影响范围，降低修改一个功能时破坏其他功能的风险。
3. 保留现有 REST、MCP、数据库、页面行为、视觉效果和部署方式。
4. 建立长期架构约束，避免业务逻辑重新堆回入口文件。
5. 保持无前端构建流程，继续由 FastAPI 提供静态文件。

## 非目标

- 不迁移到 React、Vue、Vite 或其他前端框架。
- 不替换 FastAPI、Psycopg、MCP 或 DeepSeek Harness。
- 不修改数据库表结构或已有数据。
- 不重新设计 REST 路径、请求字段、响应字段或状态码。
- 不改变管理页面视觉和交互流程。
- 不在搬迁代码时顺便重写算法、SQL 或业务规则。
- 不引入 Repository 接口、依赖注入框架、BaseService 等当前没有实际收益的抽象。

## 总体原则

采用业务域优先的纵向切分。每个业务域维护自己的路由、校验模型、存储和业务逻辑；公共基础设施只保留确实被多个业务域复用的能力。

允许的主要依赖方向：

```text
application entry
  -> feature router
    -> feature service
      -> feature store
        -> core database/config
```

公共模块不得反向依赖具体业务域。MCP 直接复用业务域的 service/store，不通过本机 REST API 间接调用。

## 后端目标结构

```text
backend/app/
├── __init__.py
├── main.py
├── core/
│   ├── __init__.py
│   ├── config.py
│   ├── database.py
│   └── schemas.py
├── features/
│   ├── __init__.py
│   ├── dashboard/
│   │   ├── __init__.py
│   │   └── router.py
│   ├── processes/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── store.py
│   ├── catalog/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── store.py
│   ├── documents/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── store.py
│   │   └── service.py
│   ├── search/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   ├── store.py
│   │   └── service.py
│   ├── skills/
│   │   ├── __init__.py
│   │   ├── router.py
│   │   ├── schemas.py
│   │   └── service.py
│   └── settings/
│       ├── __init__.py
│       ├── router.py
│       ├── schemas.py
│       └── store.py
└── mcp_server.py
```

### 入口与基础设施

`main.py` 只负责：

- FastAPI 应用创建和 lifespan。
- 注册 StoreError 异常处理。
- 注册各业务域的 `APIRouter`。
- 提供根路径、管理页面和健康检查。
- 挂载静态前端和 MCP 子应用。

`core/config.py` 负责环境变量、路径和不可变运行配置。`core/database.py` 负责连接池以及多个业务域共同使用的数据库错误类型。`core/schemas.py` 只保存多个业务域确实共享的 Pydantic 基础类型和 `ChunkingSettings`，不放置单一业务域模型。

### 业务域

- `dashboard`：聚合 `/api/state` 所需的流程、目录、用途、文档、Skill、设置和服务状态；不拥有数据存储。
- `processes`：业务流程、步骤和对应 SQL。
- `catalog`：知识目录和可配置文档用途。
- `documents`：文档 CRUD、上传预览、解析、分块、元数据、Embedding、入库和重建索引。
- `search`：模板检索、知识检索、向量召回、关键词召回和 Rerank。
- `skills`：部门 Skill 及其资源文件管理。
- `settings`：部门助手、分块、检索和模型设置。

只有需要协调多个存储操作或外部服务的业务域才设置 `service.py`。直接 CRUD 不额外创建 service 层。

`mcp_server.py` 当前规模可控，继续保留为单文件。它改为从 `processes`、`documents`、`search` 和 `settings` 导入公开业务函数。

## 前端目标结构

```text
frontend/
├── index.html
├── styles.css
├── js/
│   ├── main.js
│   ├── core/
│   │   ├── http.js
│   │   ├── state.js
│   │   ├── dom.js
│   │   └── format.js
│   ├── ui/
│   │   ├── dialog.js
│   │   ├── form.js
│   │   └── feedback.js
│   └── features/
│       ├── dashboard.js
│       ├── processes/
│       │   ├── index.js
│       │   └── editor.js
│       ├── knowledge/
│       │   ├── index.js
│       │   ├── categories.js
│       │   ├── purposes.js
│       │   ├── documents.js
│       │   └── upload.js
│       ├── skills/
│       │   ├── index.js
│       │   └── editor.js
│       ├── assistant.js
│       └── settings.js
├── css/
│   ├── tokens.css
│   ├── base.css
│   ├── layout.css
│   ├── components.css
│   ├── features.css
│   └── responsive.css
└── tests/
```

### 前端运行方式

继续使用浏览器原生 JavaScript，不增加安装或构建步骤。`index.html` 通过以下入口启动：

```html
<script type="module" src="/department/js/main.js"></script>
```

`main.js` 只负责启动、Hash 路由、页面注册和首次状态加载。业务功能从 `features` 导出页面渲染和交互函数。

原来的 `api(action, body)` 动作分发器被明确的请求函数替代，例如 `getProcesses()`、`saveProcess()` 和 `deleteProcess()`。公共 `core/http.js` 只负责 fetch、JSON 编解码和统一错误解析。

`ui` 目录维护跨页面复用且具有一致行为的弹窗、表单校验和反馈能力。`ui` 不导入任何 `features` 模块。

### CSS

`styles.css` 作为稳定入口，通过 `@import` 引入拆分后的 CSS。拆分只按职责移动现有规则：

- `tokens.css`：颜色、间距、圆角、阴影和层级。
- `base.css`：基础元素、排版和全局行为。
- `layout.css`：应用外壳、侧边栏、顶部栏和主要布局。
- `components.css`：按钮、卡片、表单、弹窗和 Toast。
- `features.css`：流程、知识库、Skill、助手和设置的业务页面样式。
- `responsive.css`：窄屏、缩放和 reduced-motion。

现有 `premium.css` 中的规则迁移到上述文件；`index.html` 只保留 `styles.css` 这一个样式入口，确认视觉检查通过后删除 `premium.css`。

如果 `features.css` 后续再次明显膨胀，再按业务域继续拆分；本次不提前创建大量空样式文件。

## 数据流与接口边界

管理页面调用链保持为：

```text
feature UI -> core/http -> REST router -> service/store -> PostgreSQL or external service
```

部门助手调用链保持为：

```text
DeepSeek Harness -> MCP tool -> feature service/store -> PostgreSQL or external service
```

REST 和 MCP 共用业务函数，但维护各自的输入适配和输出契约。MCP 不依赖前端，也不调用 REST。

## 错误处理

- 保留现有 `StoreError`、`NotFoundError`、`ConflictError` 和 HTTP 状态码语义。
- Store 层负责把数据不存在、冲突和约束问题转换成既有业务错误。
- 外部 Docling、Embedding、Rerank 和元数据请求继续使用 `ExternalServiceError` 表示 502 类错误。
- Router 不吞掉业务错误，只负责输入适配和返回既有响应结构。
- 前端 `core/http.js` 统一解析 FastAPI 的字符串或数组形式 `detail`，页面只决定如何呈现错误。
- 迁移期间不改变删除确认、表单错误定位、Toast 和加载状态行为。

## 迁移策略

整个重构按可验证的小步骤推进，不采用一次性替换。

### 阶段一：保护线

1. 在阿里云运行当前离线测试并记录基线。
2. 在 `AGENTS.md` 增加架构边界。
3. 新增项目架构说明。
4. 增加 REST 路由契约和模块依赖方向检查。

### 阶段二：后端

按以下顺序迁移：

1. `core/config.py` 和 `core/database.py`。
2. `features/processes`。
3. `features/catalog`。
4. `features/skills`。
5. `features/settings`。
6. `features/search`。
7. `features/documents`。
8. 精简 `main.py` 并更新 MCP 导入。

每次只迁移一个业务域。SQL、校验规则和响应结构以机械移动为主；该业务域检查通过后才进入下一个业务域。

### 阶段三：前端 JavaScript

1. 将现有入口转换为原生 ES Module，并先适配测试运行方式。
2. 提取 `core` 公共能力。
3. 提取 `ui` 公共交互。
4. 迁移 `dashboard` 和 `assistant`。
5. 迁移 `processes`。
6. 迁移 `skills`。
7. 迁移 `settings`。
8. 最后迁移复杂度最高的 `knowledge`。
9. 更新 `index.html` 直接加载 `js/main.js`，确认 UI 检查通过后删除旧 `app.js`。

同一业务逻辑不得在旧文件和新模块中各保留一份。

### 阶段四：CSS

在 JavaScript 行为稳定后，依次提取 tokens、基础样式、布局、公共组件、业务样式和响应式规则。每一步通过页面检查后再继续。

## 测试与验证

所有项目运行、测试和 Git 命令在阿里云目录执行。

### 现有离线检查

- `tests/server_scripts_check.sh`
- `tests/deploy_state_check.sh`
- `backend/tests/self_check.py`
- `frontend/tests/settings_ui_check.mjs`
- `frontend/tests/premium_ui_check.mjs`

### 现有在线检查

- `backend/tests/mcp_check.py`
- `backend/tests/live_admin_check.py`
- `backend/tests/live_process_check.py`
- `backend/tests/live_preview_check.py`

### 新增保护检查

- REST 路由契约检查：固定现有业务 URL、HTTP 方法和关键状态码。
- 模块边界检查：公共模块不得导入具体业务域，入口文件不得重新承载业务逻辑。

不使用简单文件行数上限作为架构规则。文件长度只作为发现职责混合的信号，真正约束的是依赖方向和职责归属。

### 验证节奏

- 每个小步骤运行对应离线检查。
- 每个后端业务域完成后运行相关在线检查。
- 知识域完成后使用受控测试文档验证解析、分块、入库、检索和清理。
- 前端每迁移一个页面就运行两个 JSDOM 检查。
- 全部迁移完成后启动服务，检查管理页面、REST 文档、MCP 和 Harness 对话入口。

## 长期保护

`AGENTS.md` 增加以下项目规则：

- 新业务功能优先新增或扩展对应业务域。
- 禁止向 `backend/app/main.py` 和 `frontend/js/main.js` 添加业务逻辑。
- 公共模块只有出现真实跨业务复用时才能创建。
- 公共模块不得依赖具体业务域。
- 修改 API 契约、数据库结构或跨域共享规则必须单独设计，不能混入普通功能开发。
- 文件读写继续使用挂载工作区；运行、依赖、测试、Docker、数据库和 Git 命令继续通过阿里云执行。

`docs/architecture.md` 提供面向后续开发的简短地图，说明新增页面、API、数据库操作、MCP 工具和配置项分别从哪里开始。

## 回退策略

- 每个业务域独立迁移和验证，不混合多个域的大范围改动。
- 出现失败时只回退当前迁移步骤，不恢复或覆盖其他已有改动。
- 不进行数据库迁移，因此代码回退不需要数据回滚。
- 前端旧入口只有在新入口和 UI 检查通过后才删除。

## 完成标准

1. 现有 REST 路径、MCP 工具、数据库行为和页面功能保持不变。
2. `backend/app/main.py` 只承担应用组装职责。
3. 前端入口只承担启动、路由和页面注册职责。
4. 流程、目录、文档、检索、Skill 和设置代码分别位于明确业务域。
5. 前端业务页面分别位于明确的 feature 模块。
6. 公共模块与业务模块的依赖方向可被自动检查。
7. 现有离线、在线和 UI 检查全部通过。
8. 项目架构文档和 `AGENTS.md` 能指导后续功能进入正确模块。
