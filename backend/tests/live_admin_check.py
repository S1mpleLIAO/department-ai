from __future__ import annotations

import base64
import json
from urllib.request import Request, urlopen


BASE_URL = "http://127.0.0.1:3081"


def request(path: str, method: str = "GET", body: dict | None = None) -> dict:
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode()
    headers = {} if data is None else {"content-type": "application/json"}
    with urlopen(Request(BASE_URL + path, data=data, headers=headers, method=method)) as response:
        return json.loads(response.read())


def main() -> None:
    original = request("/api/settings")
    skill_id = ""
    purpose_id = ""
    try:
        changed = {
            **original,
            "assistant": {
                **original["assistant"],
                "role": "端到端测试助手",
                "principles": ["只使用真实数据。"],
            },
        }
        saved = request("/api/settings", "PUT", changed)
        assert saved["settings"]["assistant"]["role"] == "端到端测试助手"

        created = request(
            "/api/skills",
            "POST",
            {
                "name": "live-admin-check",
                "description": "验证原生 Skill 管理链路。只用于自动化测试。",
                "instructions": "## 操作步骤\n1. 返回测试完成，不执行其他操作。",
                "enabled": True,
            },
        )["skill"]
        skill_id = created["id"]
        assert any(item["id"] == skill_id for item in request("/api/skills"))
        resource_path = "scripts/live_check.py"
        saved_resource = request(
            f"/api/skills/{skill_id}/resources/{resource_path}",
            "PUT",
            {"contentBase64": base64.b64encode(b"print('live')\n").decode()},
        )["resource"]
        assert saved_resource["path"] == resource_path
        with urlopen(f"{BASE_URL}/api/skills/{skill_id}/resources/{resource_path}") as response:
            assert response.read() == b"print('live')\n"
        listed = next(item for item in request("/api/skills") if item["id"] == skill_id)
        assert listed["resourceCounts"]["scripts"] == 1
        request(f"/api/skills/{skill_id}/resources/{resource_path}", "DELETE")
        listed = next(item for item in request("/api/skills") if item["id"] == skill_id)
        assert listed["resourceCounts"]["scripts"] == 0
        updated = request(
            f"/api/skills/{skill_id}",
            "PUT",
            {
                "name": created["name"],
                "description": created["description"],
                "instructions": created["instructions"],
                "enabled": False,
            },
        )["skill"]
        assert updated["enabled"] is False
        purpose = request(
            "/api/purposes",
            "POST",
            {
                "name": "自动化测试用途",
                "description": "验证用途管理链路。",
                "canGenerateTemplate": False,
                "chunkBody": True,
                "inheritChunking": False,
                "chunkSettings": original["chunking"],
            },
        )["purpose"]
        purpose_id = purpose["id"]
        assert purpose["chunkBody"] is True
        assert any(item["id"] == purpose_id for item in request("/api/purposes"))
    finally:
        if purpose_id:
            request(f"/api/purposes/{purpose_id}", "DELETE")
        if skill_id:
            request(f"/api/skills/{skill_id}", "DELETE")
        request("/api/settings", "PUT", original)
    print("live-admin-check: ok")


if __name__ == "__main__":
    main()
