# 统一技能管理规格

## 目标

让 DeepSeek Harness 创建的技能与管理页面人工创建的技能共用 `DEPARTMENT_SKILL_DIR`，页面能够管理完整技能包，而不是只管理 `SKILL.md`。

## 单一事实来源

- 技能根目录由 `DEPARTMENT_SKILL_DIR` 指定，默认是 `runtime-data/department-skills`。
- Harness 的 `skill-filesystem.customSkillDirs` 与 Python 管理页面读取同一目录。
- 页面不区分技能由 AI 还是人工创建；目录中的合法技能均按相同方式展示和维护。

## 技能格式

```text
skill-name/
├── SKILL.md
├── scripts/       可选脚本
├── references/    可选参考资料
└── assets/        可选输出模板或素材
```

- `name` 使用英文小写、数字和短横线，并同时作为目录名。
- `description` 是简短说明，包含适用情形，不设单独的 `whenToUse`。
- 页面修改技能时保留 AI 创建的其他受支持 frontmatter 字段。
- `SKILL.md` 必须显式引用需要读取或执行的资源相对路径。

## 页面行为

- 技能列表显示脚本、参考资料和素材数量。
- 技能编辑弹窗提供三个资源区域，支持选择文件、查看、下载和标记删除。
- 新技能先保存 `SKILL.md`，再上传页面中选择的资源；AI 通过文件工具创建时应先写资源、最后写 `SKILL.md`。
- 页面上传单个资源最大 20 MiB；路径必须位于 `scripts/`、`references/` 或 `assets/`。
- 删除技能继续使用产品内确认弹窗。

## 安全边界

- 拒绝绝对路径、`..`、隐藏路径和不受支持的一级目录。
- 资源读写始终在已校验技能目录下进行。
- 页面删除资源是显式操作；AI 写入工作区外的共享技能目录时继续由 Harness 权限机制确认。
- 本阶段只管理脚本文件，不增加脚本执行能力。
