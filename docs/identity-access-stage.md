# 身份与公司隔离阶段交付

2026-10-28。仅独立开发环境，未上线、未推送、未重启生产。

后续状态：新增资料审核发布已继续实现，见 [审核发布阶段](review-publishing-stage.md)。
以下“阶段边界”保留身份阶段交付时的历史范围，以后续阶段记录为准。

## 已实现范围

- 管理员建号，用户名/密码登录、退出、首次和重置后强制改密。
- Argon2id 哈希、服务端随机会话、数据库只存会话令牌摘要、HttpOnly Cookie；
  HTTPS 使用 Secure，SameSite=Lax，写操作同时校验 CSRF 和精确 Origin。
- 8小时空闲、7天绝对过期；登录失败限流。个人中心修改姓名/密码、查看和撤销自己的登录设备。
- 用户属于中科信控或森远股份。公司、部门共享是独立空间；
  默认本公司普通成员 + 部门共享只读。超级管理员可显式配置其他范围。
- 权限组：名称、说明、模块/动作勾选、半选、依赖验证、复制；同一空间组权限并集，
  不把A空间权限用于B空间。最后一位有效超级管理员不能停用/降级。
- 权限和授权每次请求读取，不依赖浏览器缓存；停用、换公司、重置密码撤销旧会话。
- PostgreSQL RLS + 显式 ScopedPool；业务表 space_id/owner_id、同空间外键；
  未设置空间默认读不到业务行。应用账号禁止超级用户和 BYPASSRLS。
- 文档和技能按空间分文件目录；解析预览再按用户隔离；原文下载校验受管目录。
- 流程归档、文档废止、技能停用保留原资料；身份、授权及业务写操作保留审计记录。
- 系统管理与个人中心页面，用户25条服务端分页，操作记录50条游标读取；
  隐藏无权限入口，服务端重复检查，支持确认/错误/空状态与窄屏横向表格滚动。

## 阶段边界

审核版本与发布任务尚未实现，因此现有发布接口必须同时有 create/edit 与 publish_direct。
普通成员虽然可获“新增”权限，本阶段尚不能在页面提交审核或直接发布；
不能把上传向导中的人工确认解释成管理员审核。后续接入审核后开放成员提交入口。

个人 Harness 和 MCP 身份桥接不在本阶段：身份测试版关闭相关入口，
绝不复用现网共享实例。生产 Harness 和现有登录方式未被修改。
细粒度技能 use 权限、文件元数据注册表、版本审批、撤权主动断开 WS、
共享申请与个人草稿进入下一阶段。

迁移把历史资料标为 legacy（仅超级管理员查看），不会自动设成共享；
原文件不搬动。历史原文和技能归属/路径迁移需单独确认并演练后上线。
当前原文下载只允许新的空间受管目录，因此旧路径不会被公开为兼容兜底。

## 实施位置与运行约束

远端工作区：
`/root/liao/DepartmentKnowledgeBase/department-ai/runtime-data/worktrees/identity-access-20261028`

分支：`codex/identity-access`，基于217e440并带入原工作区22项未提交源码改动作为基线；
原工作区未被回退/切换/暂存。身份新增代码在本工作区。

隔离数据库：容器department-identity-dev-20261028，127.0.0.1:15433，
identity_test，仅合成数据；应用账号department_app非超级用户。
依赖只安装在工作区.venv-identity，测试凭据保存在被Git忽略的.identity-state（0600）。
临时预览127.0.0.1:3181；公网、Nginx和生产3080/3081未变动。

收尾已停止临时预览、SSH转发与测试数据库容器，保留工作区及测试数据卷。
复核生产3081进程3455105、3080进程3455124未变；部门健康检查200，
Harness未认证入口401（既有认证门禁）。没有提交、推送或执行生产部署。

## 复验命令

以下命令仅在上述阿里云工作区执行，不能用生产环境变量或运行旧 live_* 测试。

```sh
PYTHONPATH=backend .venv-identity/bin/python backend/tests/identity_environment.py
PYTHONPATH=backend .venv-identity/bin/python backend/tests/identity_check.py
PYTHONPATH=backend .venv-identity/bin/python backend/tests/identity_migration_check.py
PYTHONPATH=backend .venv-identity/bin/python backend/tests/route_contract_check.py
DEPARTMENT_TEST_JSDOM=/root/liao/DepartmentKnowledgeBase/deepseek-harness/node_modules/jsdom/lib/api.js node frontend/tests/premium_ui_check.mjs
```

独立预览（不要使用现网部署脚本）：

```sh
.venv-identity/bin/python -m uvicorn app.main:app --app-dir backend --env-file .identity-state/app.env --host 127.0.0.1 --port 3181
```

测试库停止后，先运行identity_environment.py恢复；禁止将.identity-state或其密码提交Git。

## 本轮验证记录

- 真实 PostgreSQL + HTTP 回归30项通过，覆盖匿名、CSRF/Origin、首次改密、停用/重置/空闲过期、
  跨公司/共享范围、权限组并集、旧修订冲突、最后一个超级管理员、检索、原文、
  个人预览及技能附件、会话归属、归档和审计。
- 旧结构合成数据迁移、外键关联、legacy归属及重复执行通过；未触及生产数据。
- 后端 self_check、knowledge_ingestion_check、document_update_check、
  route_contract_check、module_boundaries_check 通过。
- 前端12个检查脚本通过，覆盖原有上传/编辑/滚动以及新增成员入口限制；
  原测试中等待 dialog.open=false 的竞态改为同时等待 closePromise 清理。
- 实际浏览器验证登录、退出、管理列表、权限树保存回显、必填错误/焦点、保存确认，
  桌面1366px与窄屏568px布局；普通成员直接访问管理页被拒绝，
  只能看到本公司与部门共享，知识库没有新增/编辑/删除入口。临时预览仅经SSH转发。
- premium-ui严格静态审查无未决组件归属项；17项“无点击行为”告警是模板HTML检测器
  不识别渲染后的 onclick 绑定。逐项核对 admin/profile、知识筛选/用途/批次、
  流程及技能的绑定，并由对应DOM检查和浏览器操作验证；保留原始 premium-audit.json，
  不把该扫描误报为零告警。没有通过伪造内联处理器来消除告警。

## 上线前必须完成（仍未实施）

1. 审核和不可变版本接入，明确普通成员创建/修改的提交路径。
2. Harness个人实例、模型凭据与MCP文件句柄/身份网关接入及真实并发验证。
3. 用户确认历史资源公司归属，演练文件迁移和受限回退。
4. 生产数据库角色、HTTPS会话、可信反向代理限流、日志保留及部署维护窗口验收。

目前不承诺完整多用户AI已可上线；仅登录、权限和业务隔离底座已具备独立测试条件。
