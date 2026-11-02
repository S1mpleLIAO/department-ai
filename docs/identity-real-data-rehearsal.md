# 真实资料独立迁移验收（2026-10-29）

目标为独立验收库 identity_acceptance_20261028，不切换生产。来源连接强制只读。

## 迁移约定

- 采用用户确认的2026-10-28归属清单。两个流程归中科信控；四份合同归中科信控；两条泰兴手册均归森远股份并保留旧ID；六个技能归中科信控。
- 目录按确认映射在各空间建立；未分配旧目录仍保留legacy，不对普通成员开放。
- 保留已有文档状态、正文、分块、向量、时间及流程步骤。迁移不调用模型、不重新抽取或向量化，不复制现网账号、设置密钥或Harness会话。
- 原作者未知的业务记录 owner_id 保持空值，不把验收管理员伪称为历史创建者。
- 销售合同补充协议的旧路径指向Mac。服务器已发现受管原件 runtime-data/department-ai/documents/knowledge-1787192769204.docx；使用这条明确映射，不开放任意外部路径兜底。
- 六个技能原始目录完整保留到独立待迁移区；五个符合现有格式的技能生成管理员持有的“迁移草稿”，不伪造审核或直接激活。草稿持有人是此次迁移处理人，不代表历史作者。
- travel_reimbursement_skill 的目录名与现有名称规则不同，且含templates/config/schemas/examples和顶层辅助文件。先完整保存待适配，不静默丢弃资源或替换其相对路径。
- 真实原文和技能二进制附件复制须得到用户对本次复制的明确确认（项目AGENTS.md要求）。确认前仅生成清单、编写脚本和合成数据测试。

## 执行与恢复

脚本默认只预览，显式 --apply 才写入；固定隔离容器标签、数据库名、工作树、目标根目录和确认清单。拒绝覆盖已有业务数据、目录或文件。来源事务只读并重复读；目标单事务、固定迁移审计标记防止重复导入。

原文以受管的空间目录存放。只处理清单内的普通文件，拒绝符号链接、隐藏/构建目录及大文件。失败回滚目标数据库，并只清理本次新建文件；已存在文件绝不删除。若发生进程强制中断，残留目标文件会阻止重跑，需依据私有清单核对，不自动覆盖。

验证包括：原ID、字段、分块/向量保持；原文下载逐份核验；两个公司查询和跨空间下载拒绝；迁移草稿尚未出现在正式技能列表；重复执行不产生副本；异常中断可回滚。正式上线仍另行确认。

## 本轮准备结果

- 默认只读预览已成功：9个历史目录、2种用途、2个流程、5个步骤、6份文档、52个分块；29个受管普通资源文件，共969383字节（约947KiB）。
- 报销技能的 scripts/__pycache__ 只记录为排除项，没有读取或复制其内容；不存在其他隐式构建产物处理。
- backend/tests/acceptance_import_check.py 已在一次性合成数据库通过：文件阶段中断恢复、写入后校验失败回滚、已有文件拒绝覆盖、同名记录与旧ID保留、原文内容与向量保留、分块父子关系、历史作者不伪造、技能保持草稿、跨公司RLS隔离、重复导入不覆盖后续修改。
- 测试数据库已移除，正式库和用户验收业务数据均未写入。没有运行真实 --apply；复制确认仍待用户回复。
- 私有逐文件清单：.identity-state/real-data-plan-20261029.json（0600，含源/目标路径、大小、修改时间；不含正文、向量或连接凭据）。
- 项目脚本：backend/app/features/identity/acceptance_import.py。执行目录必须为当前Aliyun独立工作树；默认生成预览。用户明确确认复制后才记录本次确认标记并执行 --apply。

## 用户确认后的实际执行

2026-10-29 用户明确回复“允许复制到独立验收环境”，本次复制确认记录存放于私有确认标记。随后已执行独立验收导入，前文“待确认/未apply”是准备阶段记录，现以本节为准。

- 中科信控：2个流程、5个步骤、4份合同；森远股份：两条泰兴手册记录均保留；部门共享为空。
- 6份原文、6个技能的必要原始资源共29个文件，969383字节，均复制到私有验收目录。原文件没有移动、修改或删除；技能缓存目录没有处理。
- 52个分块、原始文档/分块向量、旧ID、标题、时间、父子关系均逐字段比较一致；未知历史作者仍为空。
- 5个兼容技能作为验收管理员持有的迁移草稿，可在“提交与审核”中查看，没有假造审核记录或发布。报销技能完整资源保存在私有 acceptance/skill-imports/zkxk/travel_reimbursement_skill，尚待名称及资源路径适配，不会被AI加载。
- 实际数据校验24项通过：包含全部29个资源逐字节比较、6份原文真实下载处理器响应、按公司列表、跨公司403/404拒绝、无测试账号插入、单次迁移审计及无意外技能发布。
- 路由检查使用独立TestClient进程中的固定测试Principal；鉴权后的权限判断、存储查询、RLS及下载处理器为真实实现。没有修改运行服务的认证代码，没有生成用户会话或重置密码。现有3181匿名接口也确认返回401。
- 再次执行导入返回 already_imported=true，没有副本、没有覆盖验收数据。没有调用模型、重新解析或向量化。
- 私有证据：real-data-plan-20261029.json、real-data-result-20261029.json、real-data-verification-20261029.json。现网仍未迁移、未合并、未推送；3181刷新即可看到新数据。

## 报销技能名称及资源适配（2026-10-29）

用户要求继续在独立环境适配；本节更新前述“报销技能待适配”状态。正式系统、原技能及旧副本均未修改。

- 名称沿用原 SKILL.md 的 `travel-reimbursement-cn`，目录同名；旧名 `travel_reimbursement_skill` 仅作为来源记录保留。
- 脚本保持 `scripts/`；模板和公共规则改为 `assets/templates/`、`assets/config/`；说明、依赖清单、schema、输入示例及manifest移到 `references/`。17个文件/16个资源均通过现有技能草稿规范，不改REST、数据库结构或技能校验规则。
- 生成脚本路径引用与SKILL/README同步更新；原三个Word模板逐字节保留，原财务计算逻辑未改。
- 旧个人档案不进入共享技能，替换为空白 `assets/config/user_profile.example.json`。生成与档案脚本必须显式提供 `--profile`；档案写入助手禁止写入技能目录，私有档案文件权限0600。说明要求使用当前登录用户私有工作区。路径所属用户的强制隔离仍由Harness运行边界负责，CLI参数本身不是身份认证。
- 规范副本：`.identity-state/acceptance/skill-adapted/zkxk/travel-reimbursement-cn`。原暂存副本：`.identity-state/acceptance/skill-imports/zkxk/travel_reimbursement_skill`，未覆盖。
- 专用适配工具：`backend/app/features/identity/reimbursement_adaptation.py`。仅允许固定独立工作树；默认生成/校验副本，`--apply`复用隔离DB检查后创建草稿。已有不同文件拒绝覆盖，同一草稿重复执行不新增、不覆盖人工修改。
- 运行：`PYTHONPATH=backend .venv-identity/bin/python -m app.features.identity.reimbursement_adaptation --apply`，只在阿里云上述独立工作树执行。
- 验证：`PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend .venv-identity/bin/python backend/tests/reimbursement_adaptation_check.py`。服务器现有 `/usr/bin/python3` 已有python-docx 1.2.0和UNO，LibreOffice可用；本次没有安装依赖。
- 两套虚构个人档案生成8份Word，32项检查通过：金额分别2702.36与162.34、DOCX包/XML可读、数量/时间戳、本人姓名/账户、无另一套虚构档案内容、档案缺失提前失败、原始与适配技能执行后未改动等。未进行页面渲染视觉验收，也未声称已经验证全部多人并发或财务规则。
- 已新增中科信控草稿 `legacy-acceptance-20261029-travel-reimbursement-cn`，由验收管理员持有；独立环境目前共6个技能草稿、0个技能发布。重复执行返回already_imported，无重复审计。
- 独立TestClient固定身份检查：中科信控草稿/模板下载200，森远股份404；数据库资源与适配文件逐字节一致。使用真实权限/RLS/下载处理器；未新增用户、未更改密码、未创建浏览器会话。
- 私有证据：`.identity-state/reimbursement-adaptation-20261029.json`、`.identity-state/reimbursement-generation-check-20261029.json`、`.identity-state/verify-reimbursement-draft-20261029.py`。
- 尚未审核发布、未启用AI加载，未提交/推送/合并。没有重启3181或生产3080/3081；现网进程PID保持3455124/3455105。

