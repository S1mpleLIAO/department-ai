from types import SimpleNamespace
from unittest.mock import patch
import json
import sqlite3

from app.features.documents.router import document_update
from app.features.documents.schemas import KnowledgeDocumentUpdate
from app.features.documents.store import update_document


def editable(category_id: str | None, title: str = "网络手册") -> KnowledgeDocumentUpdate:
    return KnowledgeDocumentUpdate.model_validate(
        {
            "title": title,
            "categoryId": category_id,
            "status": "effective",
            "documentType": "手册",
            "keywords": ["网络"],
            "outline": ["第一章"],
            "templateFamily": "",
            "templateVariant": "",
            "version": "V1.0",
            "applicableScenario": "运维",
            "summary": "网络运维手册",
        }
    )


def current_document() -> dict:
    return {
        "id": "document-1",
        "title": "网络手册",
        "categoryId": "old",
        "status": "effective",
        "documentType": "手册",
        "keywords": ["网络"],
        "outline": ["第一章"],
        "templateFamily": "",
        "templateVariant": "",
        "version": "V1.0",
        "applicableScenario": "运维",
        "summary": "网络运维手册",
        "purposeName": "网络管理",
        "parsedText": "网络维护流程",
        "isGenerationTemplate": False,
    }


def request() -> SimpleNamespace:
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(pool=object(), settings=object())))


def runtime() -> SimpleNamespace:
    return SimpleNamespace(siliconflow_base_url="https://example.test", siliconflow_api_key="test-key")


class FakeConnection:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple]] = []

    def execute(self, statement: str, values: tuple = ()) -> SimpleNamespace:
        self.calls.append((statement, values))
        return SimpleNamespace(fetchone=lambda: object())


class FakePool:
    def __init__(self) -> None:
        self.connection_value = FakeConnection()

    def connection(self) -> "FakePool":
        return self

    def __enter__(self) -> FakeConnection:
        return self.connection_value

    def __exit__(self, *_args: object) -> None:
        return None


def category_only_change_preserves_existing_document_embedding() -> None:
    """Catches unconditional embedding recomputation for classification-only updates."""
    current = current_document()
    saved = {**current, "categoryId": "new"}
    with (
        patch("app.features.documents.router._settings", return_value=runtime()),
        patch("app.features.documents.router.get_document", side_effect=[current, saved]),
        patch("app.features.documents.router.get_department_settings") as settings,
        patch("app.features.documents.router.embed_texts") as embed,
        patch("app.features.documents.router.update_document") as update,
    ):
        result = document_update("document-1", request(), editable("new"))

    assert result == {"saved": True, "document": saved}
    settings.assert_not_called()
    embed.assert_not_called()
    assert update.call_args.args[3:] == (None, None)


def profile_change_replaces_document_embedding() -> None:
    """Catches accidentally preserving a stale embedding after a title edit."""
    current = current_document()
    saved = {**current, "title": "网络维护手册"}
    with (
        patch("app.features.documents.router._settings", return_value=runtime()),
        patch("app.features.documents.router.get_document", side_effect=[current, saved]),
        patch(
            "app.features.documents.router.get_department_settings",
            return_value={"embeddingModel": "test-embedding"},
        ) as settings,
        patch("app.features.documents.router.embed_texts", return_value=[[0.1] * 1024]) as embed,
        patch("app.features.documents.router.update_document") as update,
    ):
        result = document_update("document-1", request(), editable("old", "网络维护手册"))

    assert result == {"saved": True, "document": saved}
    settings.assert_called_once()
    assert embed.call_count == 1
    assert update.call_args.args[3:] == ([0.1] * 1024, "test-embedding")


def nullable_embedding_preserves_stored_document_vector() -> None:
    """Catches serializing a missing replacement vector before SQL can preserve it."""
    pool = FakePool()
    with patch("app.features.documents.store._validate_document_links"):
        update_document(pool, "document-1", editable("new").model_dump(), None, None)

    statement, values = pool.connection_value.calls[-1]
    assert pool.connection_value.calls[0][0].endswith("FOR UPDATE")
    assert "category_id = %s" in statement


def classification_write_preserves_concurrent_profile() -> None:
    """Execute production UPDATE SQL against a newer committed profile at lock acquisition.

    Catches writing an unlocked old profile while retaining the newer profile's vector.
    SQLite is an isolated in-memory SQL executor; only PostgreSQL binding/cast/lock syntax differs.
    """
    class InterleavedConnection(FakeConnection):
        def __init__(self) -> None:
            super().__init__()
            self.db = sqlite3.connect(":memory:")
            self.db.create_function("now", 0, lambda: "now")
            columns = "id title category_id status document_type keywords outline template_family template_variant version applicable_process_id applicable_step_id applicable_scenario summary document_embedding embedding_model updated_at"
            self.db.execute("CREATE TABLE knowledge_documents (" + ",".join(f"{name} TEXT" for name in columns.split()) + ")")
            self.db.execute("INSERT INTO knowledge_documents (id,title,summary,category_id,status,document_embedding,embedding_model) VALUES (?,?,?,?,?,?,?)", ("document-1", "并发新标题", "并发新摘要", "old", "draft", "new-vector", "new-model"))

        def execute(self, statement: str, values: tuple = ()):
            self.calls.append((statement, values))
            sql = statement.replace(" FOR UPDATE", "").replace("%s::vector", "?").replace("%s", "?")
            bound = tuple(json.dumps(value.obj) if hasattr(value, "obj") else value for value in values)
            return self.db.execute(sql, bound)

    pool = FakePool()
    pool.connection_value = InterleavedConnection()
    with patch("app.features.documents.store._validate_document_links"):
        update_document(pool, "document-1", editable("new").model_dump(), None, None)
    row = pool.connection_value.db.execute("SELECT title,summary,category_id,status,document_embedding,embedding_model FROM knowledge_documents").fetchone()
    assert row == ("并发新标题", "并发新摘要", "new", "effective", "new-vector", "new-model"), f"classification-only must preserve the locked row's profile/vector, got {row}"
    assert pool.connection_value.calls[0][0].endswith("FOR UPDATE")

    with patch("app.features.documents.store._validate_document_links"):
        update_document(pool, "document-1", editable("new", "主动编辑标题").model_dump(), [0.1], "replacement-model")
    row = pool.connection_value.db.execute("SELECT title,document_embedding,embedding_model FROM knowledge_documents").fetchone()
    assert row == ("主动编辑标题", "[0.1]", "replacement-model"), "profile edits must still replace metadata and its vector together"


def main() -> None:
    category_only_change_preserves_existing_document_embedding()
    profile_change_replaces_document_embedding()
    nullable_embedding_preserves_stored_document_vector()
    classification_write_preserves_concurrent_profile()
    print("document-update-check: ok")


if __name__ == "__main__":
    main()
