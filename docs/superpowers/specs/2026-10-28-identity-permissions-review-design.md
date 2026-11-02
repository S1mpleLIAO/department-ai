# 部门系统统一登录、公司权限、内容审核与 Harness 隔离设计

日期：2026-10-28。状态：已完成只读现状检查的设计草案，供用户审阅；不是已实施功能。

配套计划：[实施计划](../plans/2026-10-28-identity-permissions-review.md)。

后续进展（2026-10-28）：用户授权的独立环境核心技术验证已完成，见[Harness 验证记录](2026-10-28-harness-identity-feasibility.md)。本设计描述的正式账号/权限/审核功能尚未上线；当前共享生产实例未改动。

## 1. 已确认需求与本轮边界

- 公司为“中科信控”“森远股份”，另设“部门共享”空间。
- 普通成员仅访问本公司和获准的部门共享内容；跨公司管理人员经授权后可以切换公司。
- 超级管理员自定义权限组，勾选流程、知识、技能等模块的细粒度操作，并按空间分配给用户；不将普通成员、审核员、业务管理员固化为不可调整的角色。
- 支持只读、创建并提交审核、编辑、下架、审核、直接发布等组合。初始权限组只是可编辑模板。
- 新增内容默认审核后发布；授权的直接发布也必须留痕。审核通过前不能进入正式 AI 检索或技能加载范围。
- 统一登录、个人中心、账号管理、权限组管理、审核中心纳入本次设计。
- 初版设计阶段仅检查与编写文档；后续已获准的隔离技术验证另见验证记录。生产业务代码、数据库、Nginx、运行配置仍未因本方案改变，没有生产重启、构建、提交或推送。
- 机房运维、开放注册、短信验证码、企业身份平台接入暂不实施。

## 2. 检查基线与证据

本次通过 SSH 读取阿里云源码、Nginx 配置及数据库结构；数据库查询使用只读事务，只读取表名和列名，未读取业务记录、密码或密钥。

| 项目 | 实际结果 | 证据位置 |
|---|---|---|
| 部门系统 | `feature/batch-knowledge-ingestion`，HEAD `217e440`；22 个已有修改文件 | 本次 `git status`、`git diff --stat` |
| Harness | `dsh-v0.1.5-rc.1`，HEAD `183f08e9`；存在未跟踪 `output/`，未处理 | Harness `git describe/status` |
| Web 接入 | 前端直接以 `state.services.harnessUrl` 构造 iframe | `frontend/js/features/assistant.js` |
| 部门 API | 已检查入口和业务路由没有用户认证依赖 | `backend/app/main.py`、各领域 `router.py` |
| 首页聚合 | `/api/state` 汇总全量流程、目录、文档、技能及部门设置 | `features/dashboard/router.py` |
| 数据库 | 只有 7 张业务表，没有用户、公司、权限、审核或归属字段 | `information_schema.columns` 只读查询 |
| 流程 | 直接增改正式流程，更新时替换步骤 | `features/processes/store.py` |
| 知识检索 | 按有效状态、用途、向量和关键词查询，无用户/公司/审核过滤 | `features/search/store.py` |
| 预览与附件 | 使用 preview/document ID 获取、修改、下载，需补资源归属检查 | `features/documents/router.py` |
| 技能 | 文件系统保存；管理页面与 AI 共用技能根目录、监听即时发现 | `features/skills/service.py`、`harness/presets/department/agent.cordis.yml` |
| MCP | 单一全局 Runtime，无请求级用户；`document_read` 接受文件路径 | `backend/app/mcp_server.py` |
| Harness 数据 | 当前所有访问共用一个 `DSH_HOME` 和技能目录 | `harness/start.sh` |
| 公网路由 | 页面子路径、根 `/api/`、`/assets/`、`/plugins/` 和根兜底直接转发 3080；Host/Origin 被改为 loopback | `/etc/nginx/conf.d/api-ip.conf` |

7 张现有业务表：`business_processes`、`process_steps`、`knowledge_categories`、`knowledge_documents`、`knowledge_chunks`、`knowledge_purposes`、`department_settings`。技能当前不在数据库建档。

### 2.1 Harness 多用户能力的准确结论

当前安装版本具备多会话和会话级模型选择，但在所检查的 Web 认证、设置与会话存储链路中，没有可直接用于本项目的部门账号、公司授权及资源所有权隔离。

- `packages/client/connection/src/browser-auth.ts` 中 Cookie payload 只有 `version/authority/issuedAt/expiresAt`，没有用户或公司身份；同一实例的有效 Cookie 不能表示不同部门账号。
- `packages/settings/settings-file/README.md`：所有设置命名空间默认写入同一 Harness home 下的 `settings.yaml`。
- `packages/client/ui-model-selection/README.md`：`session.models/session.selectModel` 面向每个会话，可以选择模型、推理强度；不等于模型供应方/API Key 按部门用户隔离。
- `packages/session/session-persistence-jsonl/README.md`：会话按 root、工作目录、session ID 保存，目录组织本身不是公司访问控制。
- `packages/mcp/mcp-client/README.md`：HTTP MCP 支持额外请求头，可作为后续身份衔接扩展点；现配置尚未使用。

因此：目前“每个登录人员都有自己的对话配置”尚不成立。实现后应做到个人聊天、上传、输出、偏好独立；供应商、API Key、允许模型及工具策略由超级管理员统一管理。

本结论限于部署版本与已检查链路，不声称上游所有版本都不支持多用户。本轮没有升级 Harness。

### 2.2 认证提示的原因

当前版本每次进程启动生成 launch token，仅在 `GET /?token=...` 换取签名 Cookie，随后返回 `303 Location: /`。Cookie 默认绝对有效期 30 天，绑定请求 Host/port；缺失、过期、格式或签名不正确、authority 不匹配时返回 401 和所见原文。

签名密钥保存在对应 `DSH_HOME/.credentials.yaml`；普通重启若保留密钥，未过期 Cookie 不必然失效，但旧 launch token 会改变。清理/更换凭据或 home 会影响认证。当前公网 Nginx 将上游 Host 固定为 `127.0.0.1:3080`，所以不能只根据浏览器公网地址推断签名 authority；浏览器仍按公网域名保存 Cookie，与本地端口转发 Cookie 分离。

当前根路径返回 404，且 Harness token 交换重定向到 `/`，这解释了子路径认证后跳到首页 404 的路由原因；不等于认证一定失败。本轮没有复现某位用户的 Cookie，也无法判定某次提示究竟是过期还是清理导致。

上游版本化资料：[浏览器认证](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/packages/client/connection/README.md)、[会话模型选择](https://github.com/deepseek-ai/deepseek-harness/blob/dsh-v0.1.5-rc.1/packages/client/ui-model-selection/README.md)。本地源码是部署判断依据。

## 3. 身份、空间与权限

### 3.1 登录与账号

第一版管理员建号，用户名登录；密码使用成熟 Argon2id 实现，不自制加密。初始密码要求首次修改，重置后撤销旧会话。个人中心提供展示姓名、所属公司、权限摘要、修改密码、登录设备撤销和退出登录。

部门后端使用服务器存储的随机会话，不将授权内容长期缓存进自包含令牌。浏览器使用 `Secure/HttpOnly/SameSite=Lax` 的 host-only Cookie；写请求有 CSRF 校验与 Origin 校验，登录限速、统一错误提示，数据库保存会话令牌摘要。建议初值：8 小时空闲超时、7 天绝对超时，部署时由超级管理员统一设定。

停用用户、重置密码、退出其他设备立即使相应会话失效；授权修改递增权限版本并使相关缓存失效。API 返回结构化 401/403，页面引导重新登录或显示无权限。

### 3.2 空间与授权

- 建立中科信控、森远股份两个 company 空间与一个 shared 空间。正式名称可以后补，使用稳定 ID，不能将“company_id 为空”解释为对所有人共享。
- 授权基本单位：`(user_id, permission_group_id, space_id)`；同一空间内多个组取并集，不跨空间拼接权限。
- 普通成员默认授予本公司提交权限组与共享只读/技能使用组。跨公司范围只能由超级管理员赋予。
- 页面当前空间只是请求上下文；后端每次核对授权，客户端传入 company/space ID 本身不构成权限。
- 可访问列表、统计数、搜索建议、文件、父分块、审核附件全部应用同一授权边界。
- 超级管理员是独立受保护身份，不能由普通权限组提升；禁止删除/停用最后一个有效超级管理员。

### 3.3 可配置权限目录

权限组可自由命名、增删、复制、配置；可勾选的权限项由后端支持的操作目录提供，不让填写任意字符串产生不存在的能力。

| 模块 | 第一版操作 |
|---|---|
| 流程 | `read/create/edit_own_draft/edit_any/archive/review/publish_direct` |
| 知识 | `read/source_download/create/edit_own_draft/edit_any/archive/review/publish_direct/reindex` |
| 知识目录与用途 | `catalog.read/catalog.manage`（公司目录、用途均有明确空间） |
| 技能 | `use/source_read/create/edit_own_draft/edit_any/archive/review/publish_direct` |
| AI | `assistant.use`，在授权模型目录中设置个人偏好 |
| 部门共享 | 相同模块权限，以 shared 空间独立授权；迁移为共享还需 `content.share` |
| 系统 | 用户、权限组、公司、模型供应方、策略与审计管理限超级管理员 |

UI 父节点只表达选中/半选，不对应“所有未来功能自动授权”。依赖规则显式展示并在后端校验，例如审核包含读取待审版本的必要能力，不能依赖普通公开读取；移除读取能力时不能留下无法使用的编辑组合。组变更要展示影响成员和空间并记录审计。

`edit_any` 只允许形成新草稿，不自动发布；`review` 不等于 `publish_direct`。普通成员仅可编辑/撤回自己的草稿和退回版本，不能修改正式版本。第一版正式内容用归档/下架，草稿允许删除；不提供任意硬删正式历史的权限项。

技能“使用”与“管理源码”的 UI 权限可分开，但模型若加载文本技能、运行本地脚本，就可能获知其内容。不可承诺给用户可执行的本地技能同时实现源码保密；真正需要保密的实现改为受控服务器工具，不把源码挂载进个人实例。

## 4. 审核、版本与发布

### 4.1 状态机

审核状态：`draft → pending → approved/rejected`；撤回回到 draft，重新提交形成不可变提交快照；已提交版本不原地改写。

发布状态独立：`not_published → publishing → published/failed`。业务有效/废止状态与向量索引状态继续独立存在。

- 提交时校验必填属性、所属空间及当前创建权限；不存在可用审核人时明确提示，不自动通过。
- 审核时重新核验审核人的当前权限及目标空间；默认不允许自审。退回必须有意见。
- 审核通过只批准指定 revision/hash，采用版本号与行锁防止双重审核和旧版本覆盖。
- 同内容只保留一个在审变更；已有新版本时，旧审批不能覆盖它。提交人停用或失去创建权限后，待审变更转为需重新指派/提交，不自动发布。
- 直接发布走同一校验和发布服务，以 `publish_direct` 审计区别于普通审核；不是伪造他人审核通过记录。
- 已发布内容编辑产生新版本，正式指针仍指向旧版本，直到新版本完整发布成功。

### 4.2 三类内容的发布

- 流程：流程与全部步骤为同一个版本快照，发布时原子切换正式版本。
- 知识：解析和 AI 元数据建议可在草稿阶段完成；分块/向量按版本隔离。发布任务完成后切换正式版本指针；正式搜索 SQL 在召回、LIMIT、rerank 前先限制空间、发布版本和权限。不得先检索另一家公司再在结果末尾过滤。
- 技能：数据库登记稳定 ID、空间、版本与审核状态；草稿、提交快照和已发布包分开存储。仅把批准且有 use 权限的包以只读方式提供给对应实例；AI 生成技能先提交草稿接口，不直接写发布目录。
- 附件、预览均绑定 owner/space/revision；父块查询、下载、重切块、重索引和清理也必须鉴权。UUID 不作为授权凭证。
- 发布任务持久化于 PostgreSQL，使用幂等键、重试记录和锁恢复；第一版无需引入 Redis/Celery。数据库状态与文件发布通过版本目录、临时完成标记和指针切换协调，失败可重试，不清除旧正式版本。
- shared 内容不能引用公司私有资料；公司内容可引用本公司或可用共享资料。撤销共享或下架时检查依赖并使检索、缓存、技能挂载同步失效。

### 4.3 共享申请

普通成员可以提出“申请部门共享”，但不直接获得 shared 写权限。申请由专用提交动作受理，草稿仍按提交人私有及原公司管理权限可见；只有 shared 审核权限与共享授权的人员能批准目标空间。审核通过前不得把草稿对两家公司开放。既有公司资料转共享还需检查附件和全部引用；取消共享不能让已获取的历史文件或聊天内容被宣称为自动收回。

## 5. Harness 接入架构选择

### 5.1 方案比较与选定方向

| 方案 | 结论 |
|---|---|
| 共用 3080，只在外层加登录 | 只解决入口认证，不能隔离聊天、配置、文件和工具，不满足需求 |
| 深度改造 Harness 单实例，使全部 RPC、文件、设置支持租户 | 改动面大，升级耦合强；暂不作为第一版 |
| 按用户和空间建立独立运行单元，由统一网关路由 | 推荐验证方向，利用现有 Harness 能力，减少上游业务改造 |

运行单元键为 `(user_id, space_id)`，同一用户在两家公司分别保存会话、工作区、配置和上传/输出。管理员切换公司不能将旧聊天自动带到新公司；不同标签页的空间不能由一个全局可变 Cookie 决定。

仅设置不同 `DSH_HOME` 不够：现预设启用 bash/fs，进程若共用 root 权限仍能读其他用户文件。目标使用非 root、独立文件系统/网络边界的受限容器，持久化各自 home/workspace，受控只读挂载已发布技能，不挂载项目根、宿主 `/root`、数据库凭据、Docker socket 或其他用户数据。实例创建由隔离的管理进程处理，Web 服务不能接收任意 Docker 参数。

### 5.2 个人配置与管理配置

| 内容 | 归属与控制 |
|---|---|
| 聊天、上传、输出、工作目录 | 用户＋空间私有；管理员切公司不自动获得他人聊天内容 |
| 默认模型、可用推理强度、个人显示偏好 | 用户＋空间；只能选系统允许值 |
| 单次会话模型选择 | 保留 Harness 原生会话能力，服务端验证允许的模型 |
| 提示词、安全策略、插件、shell/fs 访问范围 | 平台管理，用户不能通过设置或修改配置绕过 |
| 模型供应方、URL、平台 API Key | 超级管理员统一管理；通过受控模型代理调用，不把平台密钥散发至个人 shell 环境 |

只隐藏 Harness 设置菜单不构成限制。上线前需枚举允许的 RPC、mux 方法、插件路由，后端拒绝插件安装、provider 改写、预设改写、权限策略升级等未授权动作；锁定运行组合和配置写入路径，模型代理独立执行模型白名单和配额。兼容层必须作为版本化适配项测试；尚未证明不改上游即可完成全部限制。

### 5.3 入口与域名方案

现有主站 `/api/` 与 Harness RPC 混用，根兜底还代理任意插件路径。为避免按“上一次切换空间”错路由，推荐为 AI 采用固定的空间独立 origin：

- `ai-zkxk.supercomputing7.xyz`
- `ai-senyuan.supercomputing7.xyz`
- `ai-shared.supercomputing7.xyz`

部门系统仍在 `https://supercomputing7.xyz/department`；iframe 的 origin 确定空间，认证身份确定用户，网关唯一映射到用户＋空间实例。现有 `/department-deepseekharness/` 保留为经部门认证的入口跳转，不继续作为绕过网关的直通路径。

这些域名是待部署的设计建议，本轮未修改 DNS/证书。实施首阶段要确认域名可配置；若必须严格保留同一 origin 子路径，则须先验证并实现 Harness base-path/RPC/WS/插件资源的完整路由适配，不能用全局 active-company Cookie 或 Referer 推断租户替代。域名选择是部署前决策点。

### 5.4 消除手工 Token 登录

1. 用户登录部门系统，点击 AI 助手；部门后端核验该空间 `assistant.use`。
2. 创建短期、一次性、绑定用户/空间/目标 origin/原登录会话的 bootstrap code。使用受控表单 POST 交换，不在 URL 暴露 Harness launch token；交换校验 Origin、有效期与防重放，禁止任意回跳地址。
3. AI 网关设置自身 host-only Secure/HttpOnly 会话 Cookie，关联部门服务器会话；iframe 后续请求、下载及 WS 均重新受部门身份控制。
4. 网关/运行管理器在私有网络从受保护启动通道获取实例当前 launch token，只在服务器内部调用 Harness 根路径交换 Cookie。签名凭据保持持久化。上游 Cookie 仅存服务端，浏览器不接触它。
5. 网关向正确实例注入其上游 Cookie，过滤客户端伪造身份头和上游 Set-Cookie，处理重定向；外部 Origin/CSRF 校验在重写内部 Host/Origin 之前完成。
6. 上游认证到期/重启导致 401 时，协调单次刷新认证。只重放可证明未派发的认证拒绝请求；不盲目重放 POST/上传/执行命令，网络结果不确定时查询任务状态或提示重试。WS 重新握手，不能回放可能已执行的消息。
7. 部门会话到期则展示登录入口；实例未就绪显示启动/重试状态，禁止无限刷新及直接暴露原始认证错误或 token。

因此目标是“部门登录有效时无需手工复制 Token”，不是取消认证，也不是让身份永久有效。退出/停用/权限撤销需要主动断开 WebSocket、撤销 bootstrap/网关关联，并阻止后台任务继续调用业务工具；执行中的副作用按任务取消边界处理。

Harness 仍只能从网关私网访问，不允许公网直连实例端口。部署前覆盖当前 `/api/`、根兜底、文件和插件路径，保留与本项目无关的 `/downloads`、OpenClaw 等配置。

### 5.5 MCP、文件和网络边界

- 当前 MCP 支持请求头，适配后实例使用绑定 user/space/instance 的可撤销服务凭据；后端从验证后的凭据生成 Principal，每次工具调用重新检查用户状态和权限。
- 不信任模型参数中的 user_id/company_id、自然语言角色声明或前端自报身份；没有 Principal 的工具请求拒绝执行，不回退全局权限。
- 初版现有 MCP 主要是读取；未来写工具复用同一草稿/审批服务，不能直接写正式数据。
- `document_read(file_path)` 不能继续按宿主任意绝对路径读取。改为受控文件 ID/句柄与实例所有权映射，或仅解析安全传入的文件流；不得为了兼容把所有用户目录挂载给每个实例。
- 网络默认只允许受控 MCP、模型代理和明确启用的业务出口；阻止实例 shell 直接访问数据库、其他实例、无鉴权内网管理服务和主站后门接口。
- 用户权限变化时更新/撤销实例授权、技能投影和缓存，必要时停止该实例后按新策略启动。历史对话已读入的内容不能靠检索过滤抹除，撤销整个公司访问时必须连同该空间聊天/文件入口撤销。

### 5.6 容量与验证边界

本次 `free -m` 快照：总内存约 7.1 GiB、可用约 1.6 GiB、无 swap；存在 Docker 命令，但未验证 daemon、隔离策略或实际容器兼容性。

采用按需启动、空闲回收、运行数上限和排队；不为所有用户永久启动实例。实际单实例 RSS、启动时长、并发消耗尚未测量，实施阶段先在隔离环境验证；容量不足时需扩容或单独 AI 主机，不以降低用户隔离作为回退。第一阶段未通过前，不承诺现服务器能承载指定人数。

## 6. 数据模型建议

数据库继续使用 PostgreSQL，新增版本化迁移，不在请求期间临时 ALTER，也不在本轮执行迁移。

| 新结构 | 关键字段/约束 |
|---|---|
| `companies`、`spaces` | company 简称与状态；space kind company/shared/legacy_unassigned；company 空间必须关联公司；共享唯一 |
| `users`、`user_company_memberships` | 用户名唯一、密码摘要、停用、超级管理员标志、权限版本；普通成员主公司明确 |
| `auth_sessions` | token 摘要、用户、空闲/绝对期限、撤销时间、CSRF 关联、最小设备信息 |
| `permission_groups`、`permission_group_actions` | 自定义名称、说明、系统操作目录中的动作集合 |
| `user_space_grants` | user/group/space 联合唯一，授权人及时间 |
| `content_items`、`content_revisions` | 逻辑资源 ID、类型、space、owner、正式版本指针；不可变提交快照及 hash，revision 编号唯一 |
| `review_requests`、`review_events` | 固定 revision、源/目标空间、提交人、审核人、结果/意见、乐观锁版本 |
| `publication_jobs` | revision、幂等键、状态、尝试次数、错误、可恢复时间与租约 |
| `managed_files`、`skill_packages` | 文件/技能稳定 ID、owner、space、revision、实际路径、类型/大小/hash；草稿路径和发布路径隔离 |
| `assistant_instances`、`assistant_preferences` | user＋space 唯一、持久化位置、状态、generation、资源上限；允许的个人设置 |
| `assistant_bridges`、`service_grants`、`audit_events` | 一次性票据与会话绑定、实例工具授权、业务审计（均不存明文 token 到日志） |

`content_items` 为跨领域真实复用的归属/版本元数据，正文仍由原业务领域负责。现有流程、目录、文档、用途增加明确 space/owner 关联；正式表作为可查询的发布投影，提交快照与旧正式版本分离；步骤继承流程归属，分块绑定文档版本。投影应具有复合外键或等效事务约束，避免文档目录、流程步骤跨空间误关联。

`legacy_unassigned` 仅为迁移隔离空间，只有超级管理员可查看，不能作为普通成员可选空间。每家公司及共享可有自己的用途配置；平台级模型配置保持系统级，不随用户切换空间而泄露。

## 7. 代码边界与页面范围（仅规划）

- 新增后端 `features/identity`（账号/会话/权限组）、`features/governance`（跨领域版本审核/发布/审计）、`features/assistant`（个人配置与受控启动入口）。
- 共享 Principal、空间约束、权限判断放在 `core/security.py` 等小模块，禁止 core 导入业务领域。领域 router/service/store 显式接收访问上下文。
- 现有 processes/catalog/documents/search/skills/settings/dashboard 按领域接入校验和发布投影；MCP 使用相同服务，且请求级身份不能存进当前全局 Runtime。
- Harness 网关与实例管理是独立部署职责；代码归属 `harness/gateway/`、`harness/runtime/`，先完成协议/资源验证再决定最小依赖。
- 前端新增登录、个人中心、系统管理（用户/权限组/公司/审计标签）、审核中心；各业务页提供已发布、我的提交及授权操作。
- 权限树支持分组/半选、依赖说明、空间授权预览；页面控制仅改善操作体验，不替代后端授权。
- 切换空间清理业务缓存、重载当前空间数据并更换 iframe；旧标签页绑定原空间，不因另一页切换而串线。
- 保持 `main.py`、`main.js` 只负责组合/路由，不在入口堆积权限业务代码。

## 8. 迁移、上线和回退

1. 先在测试库建立迁移并导出待归属清单；现有数据不能默认全部共享。用户确认清单后批量分配公司/共享和负责人。
2. 现有技能目录先登记和审阅，再发布到新目录；不得把未审批技能直接挂入所有实例。
3. 原 Harness 聊天/home 作为待确认归属的历史资料保留；不复制给每个新用户，不批量移动/解压本轮不在范围内的大文件。
4. 在维护窗口切换身份与路由，确保用户、权限、正式投影、文件鉴权、AI 网关整体闭环后才允许普通成员进入。
5. 迁移保留原 ID 与版本映射，备份数据库和所需配置/数据的范围提前明确；首次超级管理员通过服务器初始化，凭据不提交仓库。
6. 回退保留新数据和审计，在维护模式或管理员受限入口下回退；不能撤掉认证让旧的无权限 API 重新公开。新生成内容单独导出恢复，不直接丢弃新表。

## 9. 验收标准

- 中科信控用户无法经列表、猜 ID、附件、搜索、父块、预览、API/MCP/AI 或文件工具读取森远私有数据；共享可按权限读取。
- 同人不同空间、不同人同空间的聊天、上传与配置隔离；管理员切公司不会继承另一公司的聊天上下文。
- 权限树每个权限对应明确后端动作；新增不等于编辑他人、审核或直接发布。组修改及账号停用对 REST/MCP/WS 生效。
- 草稿、待审版本不可被普通读取/正式检索/技能发现；审核发布的是准确快照；失败保留旧版本，重试不重复发布。
- 普通成员退出后，AI 独立入口与下载不可继续使用；上游 Cookie 到期或实例重启时无需复制 token，错误可区分未登录、无权限、启动中及服务故障。
- 无权限的 provider/插件/预设/沙箱配置写入被服务端拒绝；shell 不能读宿主密钥或其他实例文件。
- 容量试验输出内存、启动时间、并发上限建议，并在上限时排队，不影响部门主服务。

## 10. 尚待验证/部署决策

业务规则以上按已确认方案整理；以下是实施前验证项，不冒充已完成能力：空间独立 AI 域名的 DNS/证书安排；容器内 Harness/文档工具可运行性及资源占用；原生 RPC 与插件收敛的适配量；单次启动 token 的受控获取与自动交换；人员规模和实际并发决定的容量；历史数据归属清单。验证不通过时记录证据和替代方案，再调整实施范围。
