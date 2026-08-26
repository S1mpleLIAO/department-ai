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
from app.features.search.store import (
    keyword_chunk_candidates,
    keyword_reference_documents,
    keyword_template_candidates,
    parent_chunk_contents,
    vector_chunk_candidates,
    vector_reference_documents,
    vector_template_candidates,
)
from app.features.settings.store import get_department_settings


class ExternalServiceError(StoreError):
    status_code = 502


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
    recalled = {item["id"]: item for item in [*semantic, *lexical]}
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
    results: list[dict[str, Any]] = []
    for rank in ranked:
        if threshold is not None and rank["score"] < threshold:
            continue
        document = candidates[int(rank["index"])]
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
    candidates = list({item["id"]: item for item in [*semantic, *lexical]}.values())

    document_candidates: list[dict[str, Any]] = []
    if document_id is None:
        semantic_documents = vector_reference_documents(pool, vector, recall)
        lexical_documents = keyword_reference_documents(pool, keywords, recall)
        document_candidates = list(
            {item["id"]: item for item in [*semantic_documents, *lexical_documents]}.values()
        )

    ranked = rerank(
        query,
        [item["content"] for item in candidates],
        options["limit"] or settings["retrieval"]["rerankTopN"],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["rerankModel"],
    )
    ranked_documents = rerank(
        query,
        [document_profile(item) for item in document_candidates],
        settings["retrieval"]["recommendCount"],
        runtime.siliconflow_base_url,
        runtime.siliconflow_api_key,
        settings["rerankModel"],
    )
    threshold = settings["retrieval"]["scoreThreshold"]
    selected = [item for item in ranked if threshold is None or item["score"] >= threshold]
    parent_ids = list(
        {
            candidates[int(item["index"])]["parentChunkId"]
            for item in selected
            if candidates[int(item["index"])]["parentChunkId"] is not None
        }
    )
    parents = parent_chunk_contents(pool, parent_ids)
    results = []
    for item in selected:
        chunk = candidates[int(item["index"])]
        results.append(
            {
                "documentId": chunk["documentId"],
                "title": chunk["title"],
                "source": chunk["source"],
                "section": chunk["sectionPath"],
                "score": item["score"],
                "content": chunk["content"],
                "context": parents.get(chunk["parentChunkId"], chunk["content"]),
            }
        )
    documents = []
    for item in ranked_documents:
        document = document_candidates[int(item["index"])]
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
