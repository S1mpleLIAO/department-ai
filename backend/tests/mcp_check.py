import asyncio
import os
from pathlib import Path

from mcp import Client


async def main() -> None:
    async with Client(os.getenv("DEPARTMENT_MCP_URL", "http://127.0.0.1:3081/mcp")) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools.tools}
        assert names == {
            "department_context_get",
            "document_read",
            "process_list",
            "template_search",
            "template_get",
            "knowledge_search",
        }
        schemas = {tool.name: tool.input_schema for tool in tools.tools}
        for name in ("template_search", "knowledge_search"):
            properties = schemas[name]["properties"]
            assert {"process_id", "step_id", "task_scenario"} <= properties.keys()
        context = await client.call_tool("department_context_get", {})
        assert context.structured_content.get("principles")
        assert context.structured_content.get("skillDirectory") == str(
            Path(
                os.getenv(
                    "DEPARTMENT_SKILL_DIR",
                    Path(__file__).resolve().parents[2]
                    / "runtime-data"
                    / "department-skills",
                )
            ).resolve()
        )
        assert context.structured_content.get("skillAuthoring", {}).get(
            "manifest"
        ) == "SKILL.md"
        result = await client.call_tool("process_list", {})
        assert isinstance(result.structured_content.get("result"), list)
        test_document = os.getenv("DEPARTMENT_TEST_DOCUMENT")
        if test_document:
            document_result = await client.call_tool(
                "document_read", {"file_path": test_document}
            )
            document = document_result.structured_content
            if not isinstance(document, dict):
                preview = ""
                if document_result.content:
                    preview = getattr(document_result.content[0], "text", "")[:200]
                raise AssertionError(
                    f"document_read 返回异常: isError={document_result.is_error}, "
                    f"structured={document_result.structured_content}, preview={preview!r}"
                )
            assert document.get("fileName") == os.path.basename(test_document)
            assert isinstance(document.get("content"), str) and document["content"].strip()
            print(
                "document-read:",
                {"fileName": document["fileName"], "characters": document["characters"]},
            )
        print("mcp-check: ok")


if __name__ == "__main__":
    asyncio.run(main())
