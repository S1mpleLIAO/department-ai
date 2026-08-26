from __future__ import annotations

from typing import Any

from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool


DEFAULT_SETTINGS: dict[str, Any] = {
    "assistant": {
        "role": "你是部门内部 AI 助手，不是办公审批系统。你帮助团队按照真实业务流程完成任务、检索内部知识并形成可追溯的标准交付物。",
        "principles": [
            "用户上传当前任务文件时，先读取文件内容，再查询真实业务流程；结合内容判断最可能的流程和步骤，并说明置信度、已完成内容和缺项。",
            "用户要生成合同、方案或报告时，先提取关键词、已知流程和步骤，再检索知识库中真实存在的模板，不得虚构模板或模板选项。",
            "检索结果存在不同模板变体时，说明差异并让用户选择；同一变体默认推荐最新有效版本，用户确认后才能读取完整模板。",
            "对照流程步骤的输入、交付物和完成标准检查资料；关键事实缺失时先询问，不得猜测。",
            "需要制度、条款或历史经验时检索参考知识；用户指定文档时只在该文档内检索，并引用真实来源和章节上下文。",
            "生成结果应说明依据和仍待确认的事项。",
        ],
        "defaultLanguage": "zh-CN",
        "draftByDefault": True,
        "askWhenMissing": True,
    },
    "chunking": {
        "mode": "structure",
        "delimiter": "\n\n",
        "maxTokens": 800,
        "overlapTokens": 80,
        "parentMaxTokens": 1500,
        "childMaxTokens": 300,
        "childOverlapTokens": 30,
        "cleanWhitespace": True,
        "removeUrlsEmails": False,
    },
    "retrieval": {
        "vectorRecall": 20,
        "rerankTopN": 8,
        "recommendCount": 3,
        "scoreThreshold": None,
    },
    "embeddingModel": "BAAI/bge-m3",
    "rerankModel": "BAAI/bge-reranker-v2-m3",
}


def get_department_settings(pool: ConnectionPool) -> dict[str, Any]:
    with pool.connection() as connection:
        rows = connection.execute("SELECT key, value FROM department_settings").fetchall()
    saved = {str(row["key"]): row["value"] for row in rows}
    return {key: saved.get(key, value) for key, value in DEFAULT_SETTINGS.items()}


def save_department_settings(pool: ConnectionPool, settings: dict[str, Any]) -> None:
    with pool.connection() as connection:
        for key, value in settings.items():
            connection.execute(
                """INSERT INTO department_settings (key, value, updated_at)
                   VALUES (%s, %s, now())
                   ON CONFLICT (key) DO UPDATE
                   SET value = EXCLUDED.value, updated_at = now()""",
                (key, Jsonb(value)),
            )
