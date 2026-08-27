from __future__ import annotations

import base64
import json
import sys
import time
from pathlib import Path
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:3081"


def request_json(path: str, method: str = "GET", value: object | None = None) -> dict:
    body = None if value is None else json.dumps(value, ensure_ascii=False).encode()
    request = Request(
        f"{BASE_URL}{path}",
        data=body,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=900) as response:
        return json.load(response)


def main() -> None:
    source = Path(sys.argv[1]).resolve()
    settings = request_json("/api/settings")["chunking"]
    preview = request_json(
        "/api/knowledge/preview",
        "POST",
        {
            "fileName": source.name,
            "fileBase64": base64.b64encode(source.read_bytes()).decode(),
            "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        },
    )
    indexed_id = ""
    try:
        assert preview["characters"] > 0
        assert "metadata" not in preview
        assert "chunks" not in preview
        analyzed = request_json(
            f"/api/knowledge/previews/{preview['id']}/analyze",
            "POST",
        )
        metadata = analyzed["metadata"]
        rechunk = request_json(
            f"/api/knowledge/previews/{preview['id']}/rechunk",
            "POST",
            {**settings, "mode": "parent-child"},
        )
        assert any(not chunk["enabled"] for chunk in rechunk["chunks"])
        candidate_id = f"python-index-check-{int(time.time())}"
        indexed = request_json(
            f"/api/knowledge/previews/{preview['id']}/index",
            "POST",
            {
                "id": candidate_id,
                "title": metadata.get("title") or source.stem,
                "categoryId": "it",
                "status": "effective",
                "purposeId": "template-reference",
                "documentType": metadata.get("documentType", ""),
                "keywords": metadata.get("keywords", []),
                "outline": metadata.get("outline", []),
                "templateFamily": metadata.get("templateFamily") or "合同补充协议",
                "templateVariant": metadata.get("templateVariant", ""),
                "version": metadata.get("version", ""),
                "applicableScenario": metadata.get("applicableScenario", ""),
                "summary": metadata.get("summary", ""),
                "chunks": rechunk["chunks"],
            },
        )
        indexed_id = candidate_id
        document = request_json(f"/api/documents/{indexed_id}")
        knowledge = request_json(
            "/api/search/knowledge",
            "POST",
            {
                "query": "合同总金额调整和产品清单变更",
                "keywords": ["合同金额", "产品清单"],
                "documentId": indexed_id,
                "limit": 5,
            },
        )
        global_knowledge = request_json(
            "/api/search/knowledge",
            "POST",
            {
                "query": "合同金额变更参考资料",
                "keywords": ["合同金额", "补充协议"],
                "limit": 5,
            },
        )
        assert indexed["saved"] is True
        assert document["indexed"] is True
        assert document["chunkCount"] == len(rechunk["chunks"])
        assert knowledge["count"] > 0
        assert knowledge["results"][0]["context"]
        assert any(item["id"] == indexed_id for item in global_knowledge["documents"])
        print(
            json.dumps(
                {
                    "previewId": preview["id"],
                    "characters": preview["characters"],
                    "chunks": len(rechunk["chunks"]),
                    "metadataTitle": metadata.get("title", ""),
                    "parentChildChunks": len(rechunk["chunks"]),
                    "indexedDocument": indexed_id,
                    "documentIndexed": document["indexed"],
                    "knowledgeMatches": knowledge["count"],
                    "topKnowledgeScore": knowledge["results"][0]["score"],
                    "relatedDocuments": len(global_knowledge["documents"]),
                },
                ensure_ascii=False,
            )
        )
    finally:
        if indexed_id:
            request_json(f"/api/documents/{indexed_id}", "DELETE")
        else:
            request_json(f"/api/knowledge/previews/{preview['id']}", "DELETE")


if __name__ == "__main__":
    main()
