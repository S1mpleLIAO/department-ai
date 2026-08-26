import json
import os
from urllib.request import Request, urlopen
from uuid import UUID


BASE_URL = os.getenv("DEPARTMENT_API_URL", "http://127.0.0.1:3081")


def request_json(path: str, method: str = "GET", body: dict | None = None):
    data = None if body is None else json.dumps(body).encode()
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={} if data is None else {"content-type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.load(response)


def main() -> None:
    created = request_json(
        "/api/processes",
        "POST",
        {
            "name": "自动 ID 验证流程",
            "steps": [{"name": "第一步", "objective": "验证自动生成步骤 ID"}],
        },
    )["process"]
    process_id = created["id"]
    step_id = created["steps"][0]["id"]
    UUID(process_id)
    UUID(step_id)
    try:
        updated = request_json(
            f"/api/processes/{process_id}",
            "PUT",
            {
                "name": "自动 ID 验证流程",
                "steps": [
                    {"id": step_id, "name": "第一步", "objective": "保留原步骤 ID"},
                    {"name": "第二步", "objective": "自动生成新步骤 ID"},
                ],
            },
        )["process"]
        assert updated["id"] == process_id
        assert updated["steps"][0]["id"] == step_id
        UUID(updated["steps"][1]["id"])
        assert all("knowledgeScopes" not in step for step in updated["steps"])
        listed = request_json("/api/processes")
        saved = next(item for item in listed if item["id"] == process_id)
        assert all("knowledgeScopes" not in step for step in saved["steps"])
        print("live-process-check: ok")
    finally:
        request_json(f"/api/processes/{process_id}", "DELETE")


if __name__ == "__main__":
    main()
