from __future__ import annotations

import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.core.database import StoreError
from app.features.documents.service import document_profile, embed_texts
from app.features.documents.store import get_document
from app.features.processes.store import validate_process_step
from app.features.search.store import (
    keyword_chunk_candidates,
    keyword_reference_documents,
    keyword_template_candidates,
    parent_chunk_contents,
    scoped_chunk_candidates,
    scoped_reference_documents,
    scoped_template_candidates,
    vector_chunk_candidates,
    vector_reference_documents,
    vector_template_candidates,
)
from app.features.settings.store import get_department_settings


class ExternalServiceError(StoreError):
    status_code = 502


CONTEXT_PRIORITY = {"exact": 3, "same-process": 2, "global": 1, "semantic": 0}


def context_match(document: dict[str, Any], options: dict[str, Any]) -> str:
    process_id, step_id = options.get("processId"), options.get("stepId")
    task = str(options.get("taskScenario") or "").strip().casefold()
    document_process = str(document.get("applicableProcessId") or "")
    document_step = str(document.get("applicableStepId") or "")
    scenario = str(document.get("applicableScenario") or "").strip().casefold()
    if process_id and document_process == process_id and document_step == step_id:
        return "exact"
    if process_id and document_process == process_id:
        return "same-process"
    if task and not document_process and not document_step and scenario == task:
        return "exact"
    if not document_process and not document_step and not scenario:
        return "global"
    return "semantic"


def prioritize_ranked(
    candidates: list[dict[str, Any]],
    ranked: list[dict[str, float | int]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    values = [
        {
            "document": candidates[int(item["index"])],
            "score": item["score"],
            "contextMatch": context_match(candidates[int(item["index"])], options),
        }
        for item in ranked
    ]
    if not (options.get("processId") or options.get("taskScenario")):
        return values
    return sorted(
        values,
        key=lambda item: (-CONTEXT_PRIORITY[item["contextMatch"]], -item["score"]),
    )


def selection_reason(match: str, options: dict[str, Any]) -> str:
    if match == "exact":
        if options.get("processId"):
            return "直接关联当前流程步骤"
        return f"直接关联独立任务场景“{str(options.get('taskScenario') or '').strip()}”"
    return {
        "same-process": "关联当前业务流程",
        "global": "全局通用知识",
        "semantic": "与当前需求语义相关",
    }[match]


def rerank(
    query: str,
    documents: list[str],
    top_n: int,
    base_url: str,
    api_key: str,
    model: str,
) -> list[dict[str, float | int]]:
    if not documents:
        return []
    if not api_key:
        raise ExternalServiceError("尚未配置 SILICONFLOW_API_KEY")
    request = Request(
        f"{base_url}/rerank",
        data=json.dumps(
            {
                "model": model,
                "query": query,
                "documents": documents,
                "return_documents": False,
                "top_n": min(top_n, len(documents)),
            },
            ensure_ascii=False,
        ).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=120) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except HTTPError as error:
        raw = error.read().decode("utf-8", errors="replace")
        raise ExternalServiceError(f"Rerank 请求失败（{error.code}）：{raw[:500]}") from error
    except (OSError, URLError) as error:
        raise ExternalServiceError(f"Rerank 请求连接失败：{error}") from error
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ExternalServiceError("Rerank 请求返回了无效 JSON") from error
    results = payload.get("results")
    if not isinstance(results, list):
        raise ExternalServiceError("Rerank 没有返回结果数组")
    output: list[dict[str, float | int]] = []
    for item in results:
        if not isinstance(item, dict):
            continue
        index = item.get("index")
        score = item.get("relevance_score", item.get("score"))
        if isinstance(index, int) and isinstance(score, (int, float)) and 0 <= index < len(documents):
            output.append({"index": index, "score": float(score)})
    return output


def search_keywords(query: str, supplied: list[str]) -> list[str]:
    fragments = [
        value
        for value in re.split(r"[\s,，。；;：:、/]+", query)
        if 2 <= len(value) <= 24
    ]
    technical = re.findall(r"[A-Za-z][A-Za-z0-9+_.-]{1,30}", query)
    values = [*supplied, *technical, *fragments]
    return list(dict.fromkeys(value.strip() for value in values if value.strip()))[:10]


def newer_document(left: dict[str, Any], right: dict[str, Any]) -> dict[str, Any]:
    left_version = [int(value) for value in re.findall(r"\d+", left["version"])]
    right_version = [int(value) for value in re.findall(r"\d+", right["version"])]
    for index in range(max(len(left_version), len(right_version))):
        a = left_version[index] if index < len(left_version) else 0
        b = right_version[index] if index < len(right_version) else 0
        if a != b:
            return left if a > b else right
    return left if left["updatedAt"] >= right["updatedAt"] else right


def search_templates(
    pool: ConnectionPool, runtime: Settings, options: dict[str, Any]
) -> dict[str, Any]:
    if options.get("processId"):
        validate_process_step(pool, options["processId"], options["stepId"])
    settings = get_department_settings(pool)
    query = options["query"]
    keywords = search_keywords(query, options["keywords"])
    vector = embed_texts(
        [query],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["embeddingModel"],
    )[0]
    recall = settings["retrieval"]["vectorRecall"]
    semantic = vector_template_candidates(pool, vector, recall)
    lexical = keyword_template_candidates(pool, keywords, recall)
    scoped = scoped_template_candidates(
        pool,
        options.get("processId"),
        options.get("stepId"),
        options.get("taskScenario", ""),
        recall,
    )
    recalled = {item["id"]: item for item in [*semantic, *lexical, *scoped]}
    latest: dict[str, dict[str, Any]] = {}
    for document in recalled.values():
        key = f"{document['templateFamily'] or document['title']}\0{document['templateVariant'] or '默认'}"
        current = latest.get(key)
        latest[key] = document if current is None else newer_document(document, current)
    candidates = list(latest.values())
    ranked = rerank(
        query,
        [document_profile(item) for item in candidates],
        settings["retrieval"]["rerankTopN"],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["rerankModel"],
    )
    threshold = settings["retrieval"]["scoreThreshold"]
    count = min(options["limit"] or settings["retrieval"]["recommendCount"], 10)
    selected = prioritize_ranked(
        candidates,
        [rank for rank in ranked if threshold is None or rank["score"] >= threshold],
        options,
    )
    results: list[dict[str, Any]] = []
    for rank in selected:
        document = rank["document"]
        profile = document_profile(document).lower()
        results.append(
            {
                "id": document["id"],
                "title": document["title"],
                "family": document["templateFamily"],
                "variant": document["templateVariant"] or "默认",
                "version": document["version"],
                "scenario": document["applicableScenario"],
                "summary": document["summary"],
                "documentType": document["documentType"],
                "keywords": document["keywords"],
                "score": rank["score"],
                "source": document["originalName"],
                "applicableProcessId": document["applicableProcessId"],
                "applicableStepId": document["applicableStepId"],
                "applicableScenario": document["applicableScenario"],
                "contextMatch": rank["contextMatch"],
                "selectionReason": selection_reason(rank["contextMatch"], options),
                "matchedKeywords": [item for item in keywords if item.lower() in profile],
            }
        )
        if len(results) == count:
            break
    return {
        "query": query,
        "keywords": keywords,
        "count": len(results),
        "results": results,
        "instruction": (
            "知识库中没有匹配的真实模板，不要虚构选项。"
            if not results
            else "请解释这些真实模板的差异并让用户确认选择。"
        ),
    }


def search_knowledge(
    pool: ConnectionPool, runtime: Settings, options: dict[str, Any]
) -> dict[str, Any]:
    if options.get("processId"):
        validate_process_step(pool, options["processId"], options["stepId"])
    settings = get_department_settings(pool)
    query = options["query"]
    keywords = search_keywords(query, options["keywords"])
    document_id = options["documentId"]
    if document_id is not None:
        get_document(pool, document_id)
    vector = embed_texts(
        [query],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["embeddingModel"],
    )[0]
    recall = settings["retrieval"]["vectorRecall"]
    semantic = vector_chunk_candidates(pool, vector, recall, document_id)
    lexical = keyword_chunk_candidates(pool, keywords, recall, document_id)
    scoped = (
        scoped_chunk_candidates(
            pool,
            options.get("processId"),
            options.get("stepId"),
            options.get("taskScenario", ""),
            recall,
        )
        if document_id is None
        else []
    )
    candidates = list(
        {item["id"]: item for item in [*semantic, *lexical, *scoped]}.values()
    )

    document_candidates: list[dict[str, Any]] = []
    if document_id is None:
        semantic_documents = vector_reference_documents(pool, vector, recall)
        lexical_documents = keyword_reference_documents(pool, keywords, recall)
        scoped_documents = scoped_reference_documents(
            pool,
            options.get("processId"),
            options.get("stepId"),
            options.get("taskScenario", ""),
            recall,
        )
        document_candidates = list(
            {
                item["id"]: item
                for item in [*semantic_documents, *lexical_documents, *scoped_documents]
            }.values()
        )

    ranked = rerank(
        query,
        [item["content"] for item in candidates],
        settings["retrieval"]["rerankTopN"],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["rerankModel"],
    )
    ranked_documents = rerank(
        query,
        [document_profile(item) for item in document_candidates],
        settings["retrieval"]["rerankTopN"],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["rerankModel"],
    )
    threshold = settings["retrieval"]["scoreThreshold"]
    selected = prioritize_ranked(
        candidates,
        [item for item in ranked if threshold is None or item["score"] >= threshold],
        options,
    )
    selected_documents = prioritize_ranked(
        document_candidates,
        [
            item
            for item in ranked_documents
            if threshold is None or item["score"] >= threshold
        ],
        options,
    )
    selected = selected[: options["limit"] or settings["retrieval"]["rerankTopN"]]
    selected_documents = selected_documents[: settings["retrieval"]["recommendCount"]]
    parent_ids = list(
        {
            item["document"]["parentChunkId"]
            for item in selected
            if item["document"]["parentChunkId"] is not None
        }
    )
    parents = parent_chunk_contents(pool, parent_ids)
    results = []
    for item in selected:
        chunk = item["document"]
        results.append(
            {
                "documentId": chunk["documentId"],
                "title": chunk["title"],
                "source": chunk["source"],
                "section": chunk["sectionPath"],
                "score": item["score"],
                "content": chunk["content"],
                "context": parents.get(chunk["parentChunkId"], chunk["content"]),
                "applicableProcessId": chunk["applicableProcessId"],
                "applicableStepId": chunk["applicableStepId"],
                "applicableScenario": chunk["applicableScenario"],
                "contextMatch": item["contextMatch"],
                "selectionReason": selection_reason(item["contextMatch"], options),
            }
        )
    documents = []
    for item in selected_documents:
        document = item["document"]
        documents.append(
            {
                "id": document["id"],
                "title": document["title"],
                "documentType": document["documentType"],
                "summary": document["summary"],
                "outline": document["outline"],
                "keywords": document["keywords"],
                "scenario": document["applicableScenario"],
                "score": item["score"],
                "source": document["originalName"],
                "applicableProcessId": document["applicableProcessId"],
                "applicableStepId": document["applicableStepId"],
                "applicableScenario": document["applicableScenario"],
                "contextMatch": item["contextMatch"],
                "selectionReason": selection_reason(item["contextMatch"], options),
            }
        )
    return {
        "query": query,
        "keywords": keywords,
        "documentId": document_id,
        "documents": documents,
        "count": len(results),
        "results": results,
    }
