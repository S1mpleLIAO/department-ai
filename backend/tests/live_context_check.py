from __future__ import annotations

import base64
import json
import os
import sys
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


BASE_URL = os.getenv("DEPARTMENT_BASE_URL", "http://127.0.0.1:3081").rstrip("/")


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


def cleanup_resources(
    document_ids: list[str],
    preview_ids: set[str],
    process_id: str,
    requester=request_json,
) -> tuple[list[str], list[str]]:
    targets = [
        *((f"/api/documents/{item}", item) for item in document_ids),
        *((f"/api/knowledge/previews/{item}", item) for item in sorted(preview_ids)),
        (f"/api/processes/{process_id}", process_id),
    ]
    cleaned: list[str] = []
    errors: list[str] = []
    for path, label in targets:
        try:
            requester(path, "DELETE")
        except HTTPError as error:
            if error.code != 404:
                errors.append(f"{label}: HTTP {error.code}")
                continue
        except Exception as error:
            errors.append(f"{label}: {error}")
            continue
        cleaned.append(label)
    return cleaned, errors


def check_cleanup_best_effort() -> None:
    attempts: list[str] = []

    def fake_request(path: str, method: str = "GET", _value: object | None = None) -> dict:
        attempts.append(path)
        if len(attempts) == 1:
            raise RuntimeError("first delete failed")
        if len(attempts) == 2:
            raise HTTPError(path, 404, "not found", None, None)
        return {"deleted": True}

    cleaned, errors = cleanup_resources(
        ["doc-1", "doc-2"], {"preview-1"}, "process-1", fake_request
    )
    assert attempts == [
        "/api/documents/doc-1",
        "/api/documents/doc-2",
        "/api/knowledge/previews/preview-1",
        "/api/processes/process-1",
    ]
    assert cleaned == ["doc-2", "preview-1", "process-1"]
    assert len(errors) == 1 and "doc-1" in errors[0]


def main() -> None:
    check_cleanup_best_effort()
    token = uuid4().hex[:12]
    process_id = f"context-process-{token}"
    step_id = f"context-step-{token}"
    document_ids = [
        f"context-global-{token}",
        f"context-task-{token}",
        f"context-process-doc-{token}",
    ]
    pending_previews: set[str] = set()
    shared_phrase = f"星港校准方案 {token}"

    try:
        request_json(
            "/api/processes",
            "POST",
            {
                "id": process_id,
                "name": f"上下文检索验证 {token}",
                "description": "仅供自动检查",
                "steps": [
                    {
                        "id": step_id,
                        "name": "编写验证方案",
                        "objective": "验证流程上下文检索",
                    }
                ],
            },
        )

        scopes = [
            {"scopeType": "global"},
            {"scopeType": "task", "applicableScenario": "编写设计方案"},
            {
                "scopeType": "process",
                "applicableProcessId": process_id,
                "applicableStepId": step_id,
            },
        ]
        for index, (document_id, scope) in enumerate(zip(document_ids, scopes)):
            source = f"{shared_phrase}\n这是第 {index + 1} 份真实上下文检索模板。".encode()
            preview = request_json(
                "/api/knowledge/preview",
                "POST",
                {
                    "fileName": f"{document_id}.txt",
                    "fileBase64": base64.b64encode(source).decode(),
                    "mimeType": "text/plain",
                },
            )
            pending_previews.add(preview["id"])
            request_json(
                f"/api/knowledge/previews/{preview['id']}/index",
                "POST",
                {
                    "id": document_id,
                    "title": f"上下文检索模板 {index + 1} {token}",
                    "purposeId": "generation-template",
                    "templateFamily": f"上下文检索模板族 {index + 1} {token}",
                    **scope,
                },
            )
            pending_previews.remove(preview["id"])

        task_result = request_json(
            "/api/search/templates",
            "POST",
            {"query": shared_phrase, "taskScenario": "编写设计方案", "limit": 3},
        )
        process_result = request_json(
            "/api/search/templates",
            "POST",
            {
                "query": shared_phrase,
                "processId": process_id,
                "stepId": step_id,
                "limit": 3,
            },
        )
        task_top = task_result["results"][0]
        process_top = process_result["results"][0]
        assert task_top["id"] == document_ids[1]
        assert task_top["contextMatch"] == "exact"
        assert isinstance(task_top["score"], (int, float))
        assert task_top["selectionReason"] == "直接关联独立任务场景“编写设计方案”"
        assert process_top["id"] == document_ids[2]
        assert process_top["contextMatch"] == "exact"
        assert isinstance(process_top["score"], (int, float))
        assert process_top["selectionReason"] == "直接关联当前流程步骤"
    finally:
        test_failed = sys.exc_info()[0] is not None
        cleanup, cleanup_errors = cleanup_resources(
            document_ids, pending_previews, process_id
        )
        print("live-context-cleanup:", json.dumps(cleanup, ensure_ascii=False))
        if cleanup_errors:
            message = "；".join(cleanup_errors)
            print(f"live-context-cleanup-errors: {message}", file=sys.stderr)
            if not test_failed:
                raise AssertionError(message)

    print("live-context-check: ok")


if __name__ == "__main__":
    main()
