from __future__ import annotations

from typing import Any

from psycopg_pool import ConnectionPool

from app.core.config import Settings
from app.db import (
    get_department_settings,
    get_document,
    keyword_chunk_candidates,
    keyword_reference_documents,
    keyword_template_candidates,
    parent_chunk_contents,
    vector_chunk_candidates,
    vector_reference_documents,
    vector_template_candidates,
)
from app.knowledge import (
    document_profile,
    embed_texts,
    newer_document,
    rerank,
    search_keywords,
)


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
