# 权限管理验收调整（2026-10-28）

> 2026-10-30 宿主权限收敛后，当前独立验收由 `department-identity-acceptance.service` 管理，实际运行配置是 `/var/lib/department-identity-acceptance/service.env`（专用账号私有）。下文旧 PID/nohup/owner-preview.log 记录仅为历史信息。查看状态用 `systemctl status department-identity-acceptance.service`；日志用 `journalctl -u department-identity-acceptance.service`。重启前须确认无执行中的任务；不要用旧脚本重新启动 root 监督进程。新部署说明见 [宿主收敛说明](assistant-hardening-stage.md)。

本轮在 identity-access 独立工作树完成，不合并或部署现网。

- 权限组以模块 / 操作树配置；用户授权以空间 / 权限组配置，并展示该空间合并后的功能。所有保存仍走现有后端权限校验与乐观锁。
- “使用已发布技能”独立于源码查看；功能树的依赖勾选必须与后端一致。
- 沿用现有能力编码：create 包含新增、本人新增草稿修改和提交；edit_any 包含已有资料修改送审。界面明确展示这层含义，不虚构尚无后端实现的独立“本人草稿编辑”开关。
- 系统管理增加公司基础信息页；本轮固定两家公司及部门共享，不增加组织创建、删除接口。
- 权限组列表支持搜索和分页。成员列表通过超级管理员专用 GET /api/admin/permission-groups/{group_id}/members?page=0 查询，返回 items、total、pageSize，每页 25 个“成员 / 空间”授权；不返回密码或登录信息。此接口不改变业务授权模型。
- 自动化回归继续使用 identity_test。用户验收使用独立数据库，保留 liao-admin 最新密码散列及账号状态，不复用回归测试垃圾数据；不搬迁现网业务数据。
- 提交审核时检查对应模块、空间是否有其他可用审核人；没有则保留草稿并提示补充审核人。发布仍走原有审核与发布权限。

## 验收结果

- 3181 用户验收服务使用 identity_acceptance_20261028；保留 liao-admin 已修改后的密码、姓名、公司和超级管理员身份。旧登录会话不复制，需要重新登录。
- 新库只有1个真实验收账号、4个可修改权限组模板，以及公司、共享空间、默认用途。正式知识、流程、技能尚未迁入，业务列表为空是预期结果。
- 原 identity_test 完整保留用于回归，其中 liao-admin 旧副本停用；用户验收账号在新库保持启用。
- 初始模板只在缺失时插入，永不覆盖管理员自定义能力。只读模板允许使用技能，不含源码查看；提交模板明确包含维护技能所需的源码权限。
- 后端身份回归33项、审核发布26项、修改审核21项通过；前端 identity/review/review-edit/permission-admin、CSS 和模块边界检查通过。
- 真实浏览器在临时3191合成数据服务验证：权限树折叠/半选、技能使用与源码分离、未保存关闭提示、按公司查看授权、权限组搜索、另一公司无权限空状态。568px窄屏页面宽度568px、弹窗530px，无横向溢出。未在浏览器保存真实成员授权。
- 严格静态UI扫描报告19处 actionless-button，为HTML模板扫描不识别后续onclick绑定。本轮admin标签、用户操作、组配置/复制/删除/成员已逐项核对绑定，新增路径有DOM及浏览器验证。报告保留在私有 .identity-state/permission-ui-audit.json；不声明静态扫描零告警。
- 临时3191服务及SSH转发已关闭，测试账号停用并撤销会话；3181验收入口保留。生产3080/3081的PID不变，代码未合并、提交或推送。

## 当前明确边界

- 新增、本人新增草稿修改、提交审核仍为同一授权项；没有独立的本人草稿编辑开关。
- 公司页展示现有公司与共享范围，不开放新增/删除公司。
- 3181仅提供权限与内容审核验收，个人AI网关未在此常驻预览启用；此前独立AI验证不表示此入口已经开启AI。
- 现网资料迁移继续使用已确认的公司归属清单；正式合并与迁移另行安排，不把合成记录当作正式数据。

验收入口仍为 http://127.0.0.1:3181/department ，使用原SSH转发、liao-admin及用户已修改的密码。
重启该独立预览使用 .identity-state/owner-preview.env（与 acceptance-preview.env 一致）；不要重新执行旧的 prepare-owner-access.py。
