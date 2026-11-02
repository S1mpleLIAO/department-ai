"""Original departmental tools, with company data supplied by the authorized bridge."""
METADATA = {
    "name": "部门助手模式",
    "description": "读取当前任务文件，依据真实业务流程和内部知识库分析缺项、推荐模板并形成可确认的标准交付物。仅使用当前人员和公司有权限的已发布资料。",
    "order": 0,
}


def composition(root):
    def plugin(id, name, **config):
        return {"id": id, "name": name, **({"config": config} if config else {})}
    return [
        plugin("persona", "@deepseek-ai/dsh-persona", prefix=(root/"harness/identity/persona.md").read_text()),
        plugin("tool-bash", "@deepseek-ai/dsh-tool-bash"),
        plugin("tool-fs", "@deepseek-ai/dsh-tool-fs"),
        plugin("tool-fs-search", "@deepseek-ai/dsh-tool-fs-search", sampleOverCapGlobResults=False),
        # Native skill loader; its provider below checks live permissions instead of scanning host directories.
        plugin("department-tools", "/integration/tools.ts"),
        plugin("tool-skill", "@deepseek-ai/dsh-tool-skill"),
        {"id": "compaction", "name": "cordis:group", "group": True,
         "isolate": {"compaction": True, "toolResultPruner": True}, "config": [
            plugin("compaction-basic", "@deepseek-ai/dsh-compaction-basic"),
            plugin("command-compact", "@deepseek-ai/dsh-command-compact"),
            plugin("tool-result-pruner", "@deepseek-ai/dsh-compaction-tool-result-pruner",
                   thresholdChars=8192, headChars=4096, tailChars=1024)]},
        plugin("tool-ask-user", "@deepseek-ai/dsh-tool-ask-user"),
        plugin("tool-todo", "@deepseek-ai/dsh-tool-todo", allowParallelInProgress=True),
    ]
