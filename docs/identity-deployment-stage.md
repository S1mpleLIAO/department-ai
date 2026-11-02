# 身份版本部署准备与上线门槛

2026-10-28。本阶段仅在独立工作区准备部署入口和进行合成数据验证，未合并、推送或部署现网。
生产代码目录、数据库、3080/3081、Nginx 和 DNS 保持不变。

## 新的启动方式

身份版本使用 `backend/identity_server.py`，旧的共享 Harness 部署及启停入口检测到身份版本会直接拒绝执行。
新入口显式读取一个属于运行用户、权限 0600 的环境文件，不回退读取项目 `.env`，
也不继承旧的部门、模型配置。它不会安装依赖、拉取镜像、执行迁移或结束已有端口进程。

在目标发布目录使用已准备好的 Python 环境执行：

```sh
PYTHONPATH=backend /path/to/venv/bin/python backend/identity_server.py check --env-file /path/to/private.env
PYTHONPATH=backend /path/to/venv/bin/python backend/identity_server.py serve --env-file /path/to/private.env
```

`check` 检查迁移编号及校验和、非管理数据库角色、表所有者权限、RLS、迁移和审计表写权限、
超级管理员是否存在，并返回 legacy 历史资料数量。检查事务只读，报告不含凭据或正文。
AI 启用时同时检查模型配置、Harness 构建所需路径、Node、已存在的容器镜像及独立入口。
检查成功不代表真实业务资料迁移或公网验收完成。

`serve` 在检查通过后启动部门 API；只有 AI origins 非空才启动网关。
任一子服务退出时停止本次启动的另一子服务，由 systemd 决定重启。
端口已被占用时拒绝启动；收到停止信号仅清理自己的子进程，不接管现网进程。
systemd 示例位于 `deploy/identity/department-identity.service.example`，需要替换发布路径，尚未安装。

## 个人 Harness 的持久化

生产候选配置必须显式指定 `DEPARTMENT_AI_RUNTIME_MODE=production` 和 `DEPARTMENT_AI_STATE_DIR`。
建议使用 `/var/lib/dai-ai`，由可信宿主服务拥有、权限 0700；不放临时目录或代码发布目录。
目录路径受 Unix socket 长度限制，过长时启动拒绝。

每个用户和空间保留独立 home、对话、个人设置与对话授权记录。
容器名称带存储根目录摘要，避免暂存与生产环境处理同名账号时互相停止容器。
文件锁阻止两个网关同时管理同一存储目录；不能使用多个 uvicorn workers。
个人目录不允许符号链接；清理容器前同时校验管理标签和 home 挂载归属。

现有资源上限保持不变：最多两个运行实例，每实例 640 MiB，15 分钟空闲停止。
这是小规模验证配置，不是部门并发容量承诺。当前候选仍限制 Shell 和附件能力；
用户已决定不新建另一套上传下载功能。后续如开放原生功能，仍需验证其权限边界。

## HTTPS 和自动认证

部门页面继续使用 `https://supercomputing7.xyz/department`。
AI 候选为同一站点下三个独立主机名：

| 空间 | 候选 origin |
| --- | --- |
| 中科信控 | `https://ai-zkxk.supercomputing7.xyz` |
| 森远股份 | `https://ai-senyuan.supercomputing7.xyz` |
| 部门共享 | `https://ai-shared.supercomputing7.xyz` |

这些只是配置建议，未申请证书或更改 DNS。三个主机名可反代同一 loopback 网关端口3182；
网关依据精确 origin 匹配空间，不信任浏览器指定的任意公司参数。
部门与 AI 不能同主机名，以免原生 Harness 前端和部门应用共享浏览器安全边界；
生产模式也拒绝用同一主机的不同端口充当公司隔离，因为 Cookie 不按端口隔离。

用户登录部门系统后，通过一次性 POST 票据进入个人 Harness，服务端完成上游认证。
不用复制 `?token=` 链接；重启后由服务端重新换取原生认证。
部门会话过期、退出或权限撤销仍应要求重新登录，不通过无限延长登录规避认证。

反代候选见 `deploy/identity/nginx.conf.example`。网关只监听127.0.0.1，
只信任同机代理的 forwarded headers；代理必须覆盖 Host、X-Forwarded-Proto、
X-Forwarded-For，保留 WebSocket 升级，关闭流式缓冲。原 `/api/` 的归属必须先核对。
正式切换时还要关闭旧共享 Harness 的公网旁路，否则新登录不能保护旧入口。
本阶段没有安装或 reload 示例配置，真实证书与浏览器 HTTPS 流程待验收。

## 迁移和资料归属

已完成一次只读现网盘点及合成旧结构迁移/中断回滚演练，见
[历史资料盘点与演练](identity-legacy-rehearsal.md)。归属尚待确认，现网未执行迁移。

服务启动不执行数据库迁移。使用已存在的显式管理命令：

```sh
# 先通过受控方式提供管理员 DSN；不要把密码放进 shell 历史。
PYTHONPATH=backend /path/to/venv/bin/python -m app.features.identity.manage migrate
PYTHONPATH=backend /path/to/venv/bin/python -m app.features.identity.manage bootstrap --username admin
```

这两个命令只读取显式 `IDENTITY_MIGRATION_DATABASE_URL`，不要用应用账号执行。
应用角色需按测试环境的授权清单创建：NOSUPERUSER、NOBYPASSRLS、NOCREATEROLE、
NOCREATEDB、非表所有者；撤销 public schema 的 CREATE，授予业务表所需读写和序列权限，
撤销 schema_migrations 的写权限及 audit_events 的 UPDATE/DELETE。

历史目录、流程、文档及其关联必须作为整体分配到公司或共享空间。
不能单独更新文档 space_id 而遗漏目录、用途、分块和原文受管路径。
旧技能文件需同时纳入正式发布记录；旧 Harness home 的归属也要单独确认。
目前仅输出数量，不猜测历史所有人，不移动原文、技能或旧会话。

## 上线和回退顺序

1. 核对生产工作区22项原有改动与身份分支的共同基线，整理可审阅提交；正式环境当前使用功能分支，不能假定它等于 GitHub main。
2. 确认历史资料归属清单、真实附件路径、管理员账号、AI 功能范围、域名及维护窗口。
3. 在独立数据库和独立文件目录演练批准的数据迁移，验证旧ID、引用、原文下载与真实向量服务；准备备份恢复记录。
4. 停止旧写入口，在维护窗口备份数据库及经批准的持久数据；执行迁移，初始化管理员，再用新入口 `check`。
5. 安装新服务和审核后的代理路由；验证匿名拒绝、两公司隔离、审核发布、下载、AI 自动认证与撤权，随后开放访问。
6. 若上线失败，先关闭入口进入维护状态；保留新数据和审计，使用已演练的备份恢复方案。不能仅切回旧代码并公开旧无权限接口。

正式迁移、备份、历史归属调整及公网切换须另行确认，本阶段不执行这些动作。

## 本阶段验证

`backend/tests/identity_deployment_check.py`：在独立真实 PostgreSQL 上验证迁移和只读预检、
拒绝超级用户角色、生产目录及 origin 约束、重复管理进程拒绝、私密环境配置、
AI关闭模式启动、匿名请求拒绝、端口冲突及停止后端口释放。
另以真实 loopback 服务模拟可信 HTTPS 反代头，验证生产模式网关启动、Secure Cookie、
一次性票据、错误 origin/公司/协议拒绝及退出后立即失效。这不等于真实 TLS/浏览器验收。

`backend/tests/assistant_restart_check.py`：仅用测试账号及 `/root/.dai-stage-20261028`
持久暂存目录，重新创建真实 Harness 容器验证会话、个人设置、授权记录和上游认证恢复。
测试不调用真实模型、不读生产业务资料；数据保留供复验，容器在测试结束时停止。

上述两份检查实际通过；网关授权回归10项、路由契约、后端模块边界、原服务器脚本检查、
`git diff --check` 同时通过。重启检查最初误读了设置文件路径，已改为调用原生设置接口，
重新运行验证成功。测试没有修改现网配置或重启现网服务。

这些检查不替代生产容量、真实 HTTPS、异常退出残留容器恢复及历史资料迁移验收。
