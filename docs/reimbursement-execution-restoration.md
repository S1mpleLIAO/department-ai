# 独立验收环境报销执行恢复

范围：仅 identity-access 独立环境。复用已审核发布 travel-reimbursement-cn 的脚本和三份模板，不改财务计算规则，不改数据库及正式系统。

## 边界与接口
- Harness 原生二进制上传继续使用 /api/session/uploadFileBinary，网关核验登录、公司、来源和会话授权版本，限制单文件 20 MiB。
- department_uploaded_document_read 只接受当前实例原生附件路径，复用 Docling 正文解析。不得读取配置、其他用户、其他公司的文件。
- department_reimbursement_generate 接收 jobJson、profileJson；资料缺失或非法金额/路径拒绝生成。技能必须在当前公司已发布、启用，用户须有 skills.use，执行不要求 skills.source_read。
- 不提供任意 Shell。固定执行已发布技能 scripts/generate_documents.py，模板和脚本只读挂载，临时任务目录独占。Docker 无网络、非 root、无 capabilities、内存 512 MiB、CPU 0.5、超时 180 秒。复用本机 Python/LibreOffice 只读依赖，不安装大镜像。
- 每个网关最多同时一个生成任务，跨网关使用宿主 flock 串行；任务期间保留 runtime lease。权限撤销或停止取消任务。成功后才将 DOCX 和报告移入当前用户/公司工作区，并给出原生下载链接。
- 个人资料仅随本次任务输入使用，不从旧全局配置继承。后续重复报销可在自己的对话中提供，不新增独立资料管理页面。
- 只恢复附件 UI，保持权限模式与管理员设置不可自行切换。

## 验收
真实原生上传、Docling 解析、原生模型工具调用、固定脚本生成、Word 结构/金额/渲染、鉴权下载；异用户/异公司/撤权/未发布/路径穿越拒绝。仅验收进程在无活跃任务时重启，检查现网 PID 不变。

## 实施与验证结果（2026-10-30）
- 已恢复原生附件入口、带会话校验的二进制上传、本人附件正文解析、已发布报销技能执行和原生鉴权下载。
- 使用独立环境配置的 deepseek-v4-flash，真实运行上传材料 → 读取技能/材料 → 调用生成 → 下载链路；并使用确定性模型重复验收边界。
- 两次合成出差生成 5 份 Word（2 份审批单、2 份明细表、1 份总报销单）和 1 份核对报告。金额为 2552.36 + 150.00 = 2702.36，原始票据 5 张。
- 普通 skills.use 用户可执行但不可读取脚本源码；验证其他用户文件路径、异公司权限、路径穿越、无效会话、撤权下载拒绝。
- 13 项登录/权限/审核/助手/输入边界检查通过。生成文档逐页渲染核对，中文字体可用；仅移除表格后的无内容末尾段落以消除空白页，保留审批备注与财务签字栏。
- 上传验证使用合成 Word 材料，生成使用已发布三份真实模板。尚未替代用户对真实发票（尤其扫描件识别质量）和浏览器交互的人工验收。
- 运行准备：在目标独立目录执行 bash harness/identity/setup-reimbursement-runtime.sh。复用现有 Docker 镜像、系统 Python/LibreOffice，只在 .identity-state/reimbursement-fonts 解出 Ubuntu 中文字体，不修改宿主字体配置。
- 模型工具超时：解析沿用 Docling 600 秒，生成 180 秒；容器内另有 175 秒超时以覆盖网关异常退出。生成并发通过跨网关文件锁限定为 1，个人 AI 名额仍为 4。
- 证据：.identity-state/reimbursement-live-results.json、reimbursement-real-model-results.json、reimbursement-regression-results.json。测试输出/模型返回仅存受限 .identity-state 目录，不提交 Git。
