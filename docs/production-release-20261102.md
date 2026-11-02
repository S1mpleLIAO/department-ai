# 公网统一登录上线记录（2026-11-02）

## 入口与运行方式

用户入口为 https://supercomputing7.xyz/department 。只需部门账号登录，AI 入口票据由系统自动兑换。
公司 AI 入口分别为 ai-zkxk、ai-senyuan、ai-shared.supercomputing7.xyz，三个主机共享网关进程，使用独立浏览器凭据。
Nginx 转发部门接口至 127.0.0.1:3081，AI 网关至 127.0.0.1:3182。端口仅监听本机，不再使用共享 3080 服务。
原有 IP 站点、OpenClaw、会议纪要 downloads 配置保持不变。

正式服务：department-identity.service；固定容器代理：department-identity-container-broker.service。
服务使用无 Docker/sudo 权限的既有 UID 10001。
正式数据库为原 PostgreSQL 17 容器中的 department_identity_20261102，应用使用非超级用户、非表所有者、不可绕过 RLS 的独立角色。
私有服务配置在 /var/lib/department-identity/service.env（服务用户所有，0600），业务资源在该目录下的 data/skills。

本次沿用验证完成的发布目录及依赖，避免同时更换沙箱和固定代理路径：
/root/liao/DepartmentKnowledgeBase/department-ai/runtime-data/worktrees/identity-access-20261028。
个人持久数据继续位于 /root/liao/identity-ai-acceptance。这些名称是历史命名，现已由正式服务使用，**不能作为临时验收文件删除**。
主工作目录已切换到 main。后续发布应先准备新的固定发布目录，完成代理路径及兼容预检后再切换 systemd；不要使用旧共享版本的 start/restart 脚本。

实例上限 4，空闲时间 900 秒，可在私有服务配置中调整。执行中任务不因空闲回收停止，个人会话和模型配置持久保存。
独立验收服务停用自动启动，避免两套服务竞争同一份个人数据。

## 数据保存与备份

冷备份目录：/root/department-release-backups/20261102-144357（root 私有）。
包含修改前 Nginx、证书、systemd、固定容器代理及私有服务配置；原共享数据库及验收数据库的 pg_dump 和角色备份；原共享 Harness、业务原件、技能、个人数据及三个服务器工作区的文件归档。
另保留文件内容校验清单，以及主目录中原来未跟踪的三份设计文档。

备份逐项核对 50,851 个普通文件及符号链接；文件归档未跟随链接展开。
新数据库从验收库恢复，22 张表在路径迁移前逐表内容指纹相同；旧 department_ai 数据库未覆盖。
27 个账号、全部权限组/授权、9 份文档、4 个流程及 6 个技能发布记录均保留，禁用状态不变。
业务文件转移至正式私有数据目录，文档及审核载荷中的受管理路径同步调整，未重解析正文或重建向量。

旧共享 Harness 的 27 个会话归到 liao-admin 的中科信控个人实例；三个服务器工作区文件在其个人 workspace/legacy-20261102 下。
现有 3 个个人会话以及已有个人配置保留，原记录的压缩事件尾部字节未改写，仅重定位会话工作目录头。
旧共享会话保留作历史查看；它们没有当前的权限快照绑定，继续处理请在迁入工作区新建对话，不能绕过当前权限校验延续旧上下文。
早期 /Users/liao/Desktop/testdsh 会话保留；其 Mac 原目录不在服务器上，没有声称迁入这些不存在的本地文件。

## HTTPS 原生设置适配

DSH v0.1.5-rc.1 原生客户端按 connection.isLoopback 决定是否读取宿主设置；公网域名默认仅内存设置。
认证网关的页面初始化脚本使用上游公开 __DSH_TRANSPORT__ 接口，声明该页面连接的是用户自己的隔离 Harness Host，从而恢复原生模型配置。
这仅是客户端界面适配，不授予操作系统或后端管理权限；RPC 继续经过同源网关，禁止跨源及重定向，平台命名空间/凭据/预设/路径仍由后端白名单校验。
上游源码及构建未修改，不额外创建模型配置页面。

先在隔离验证浏览器中加载候选适配，验证模型页面、模式选择和后端拒绝规则，再接入网关页面。
对应回归：backend/tests/assistant_managed_transport_check.mjs、assistant_personalization_check.py。
上线复验使用真实 HTTPS 入口，包括登录票据、Secure/HttpOnly/host-only Cookie、普通成员公司隔离、历史会话、文件下载及浏览器设置页。
临时验证账号和认证会话由 finally 清理，不更改正式用户密码或授权。

## 维护与回退

以下命令在阿里云执行。

- 状态：systemctl status department-identity.service
- 预检：在固定发布目录中，以服务用户执行 .venv-identity/bin/python backend/identity_server.py check --env-file /var/lib/department-identity/service.env，环境 PYTHONPATH=backend。
- 重启前先确认没有活动任务；不要以重启代替空闲回收。
- Nginx 修改前先备份，运行 nginx -t 后 reload。
- 新增子域名证书由 Certbot 管理，续期后通过 deploy hook 校验并 reload Nginx。

回退前先阻止新写入，备份上线后的数据库和个人文件，并确认没有运行任务。
原数据库、原共享 Harness 和源工作区仍保留。旧代码在 feature/batch-knowledge-ingestion（0a7ee9b），旧 Nginx 配置在冷备份中。
恢复旧共享服务会恢复没有统一账号隔离的旧入口，且不能把上线后的新数据自动倒回旧结构；因此回退必须明确维护窗口并保留新数据，不能直接覆盖或删除。
