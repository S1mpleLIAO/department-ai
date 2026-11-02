# 六个真实技能的独立验收（2026-10-29）

范围：identity-access-20261028 工作树、identity_acceptance_20261028 数据库。用户明确要求验证审核发布与 AI 调用，并确认五个占位技能验证后停用。现网、现有3181验收服务、真实管理员密码不修改。

## 最终业务状态

| 技能 | 技术审核发布 | 最终启用 |
| --- | --- | --- |
| baoxiao | 通过 | 否（占位内容） |
| contract-risk-review | 通过 | 否（占位内容） |
| test123 | 通过 | 否（占位内容） |
| test456 | 通过 | 否（占位内容） |
| testli | 通过 | 否（占位内容） |
| travel-reimbursement-cn | 通过 | 是 |

全部归中科信控。审核理由明确标注“独立环境自动化技术验收，非人工业务审核”，没有把占位说明当成可用业务技能。五个停用技能保留审核版本和审计记录，不删除原件。

## 审核发布与权限证据

- 新增三个明确标为临时技术验收的账号：审核员、中科信控调用者、森远股份调用者。审核员只授予中科信控技能查看、审核、发布、停用权限；调用者仅有本公司的 assistant.use 与 skills.use。真实管理员的密码和权限不变。
- 提交人与审核员不同。作者侧提交和建临时账号的操作使用仅存在于 TestClient 进程的固定管理员 Principal；审核员及调用者通过真实账号登录、首次改密和授权校验。运行中的服务没有认证绕过开关。
- 六个草稿最初均不进入 AI 列表；未审核发布409、自审403、无权读取待审内容的成员404、过期revision审核409。
- 审核后但发布前仍不可调用；发布后6个技能逐一可读，所有附件与审核payload逐字节一致。重复发布不生成第二条发布审计。
- 森远股份列表为空，逐个猜测中科信控技能ID返回404。没有 skills.use 的调用返回403。
- 网页源码API需要 skills.source_read；仅技能使用权限不能查看/下载源码。
- 停用5个技能后，AI列表只剩报销技能，被停用ID读取404，授权/资料指纹变化。

## 真实 Harness 与模型

临时API使用3191、网关使用3182–3184；现有3181服务保持运行。模型使用既有私有配置中的 deepseek-v4-flash。API密钥未进入容器或日志报告。

实际验证了部门真实登录→一次性票据→原生Harness自动认证→WebSocket对话→模型调用 department_skill_list 与 department_skill_get。模型逐一读取6个技能说明；没有把合同、发票、Word二进制附件或旧个人银行卡档案发送给模型。

停用后旧对话保留历史，但续问返回409；新对话只接收报销技能。森远股份的真实对话调用工具后得到空列表，也不能列出另一用户会话；退出登录立即使AI Cookie失效。

当前“AI调用技能”仍指读取并采用已发布说明/允许资源；没有开放任意Shell、脚本执行或原生上传流程。报销脚本生成Word的验证仍是上一轮独立CLI检查，不能据此宣称AI已自动执行报销脚本。

## 本轮发现和修复

AI资源工具原来允许仅 skills.use 的用户读取 scripts/ 附件，能够绕过网页源码权限。已在独立代码的 assistant/resources.py 添加 scripts/ 资源读取时的 skills.source_read 校验。

回归先复现失败，再验证修复：使用权限读取脚本403；同时具备源码权限可读；技能说明与非脚本assets仍可用。这一限制针对规范中的 scripts/ 目录，不把模型已读取的说明或其他附件宣称为不可转述的秘密。

## 验证工具与私有证据

- backend/tests/acceptance_skills_check.py：prepare 为一次性真实草稿审核发布检查，finalize 停用占位技能，cleanup 撤销临时账号和授权。不能当作可反复重置真实验收数据的普通测试。
- backend/tests/acceptance_skills_model_check.py：真实模型的六技能读取、停用后上下文和公司隔离检查。
- backend/tests/acceptance_skill_source_check.py：源码工具权限回归。
- backend/tests/acceptance_skill_bridge_check.py：实际运行的Harness工具桥权限回归。
- 私有报告：.identity-state/six-skills-review-results.json、six-skills-model-results.json、six-skills-source-bridge-results.json。
- 临时账号密码及连接配置仅在0600文件内；不提交Git。审核人员配置仍须在正式上线前由超级管理员确认，临时验收账号不作为日常审核人员。

本轮未合并、未推送、未部署现网。


## 收尾结果

- 15项去重审核/发布/权限检查、10项真实Harness/模型检查通过；实际Harness工具桥确认脚本源码403、非脚本assets200、列表仅报销技能。
- 本轮源码权限修复只在临时验证服务重启后做真实工具桥复验。停止后的端口曾处于连接回收期，等待释放后重启成功；未为此重启或修改现网。
- 三个临时账号已停用、活动会话已撤销、临时授权及权限组已移除；保留账号记录用于审核审计。3191和3182–3184均无监听，本轮所属个人容器已退出。
- 原3181验收服务PID958532不变；现网3080/3081 PID3455124/3455105不变，状态分别为预期匿名401与health200。
- 原6份文档、2个流程保留。六个技能均有技术发布记录，五个占位技能enabled=false，travel-reimbursement-cn enabled=true。
- 最终证据：.identity-state/six-skills-final-results.json。现有验收页面刷新即可查看发布/停用状态，临时AI验证入口已关闭。

