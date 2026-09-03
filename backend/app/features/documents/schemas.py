from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints

from app.core.schemas import Identifier, NonEmpty, ShortText, StrictModel


class KnowledgePreviewInput(StrictModel):
    fileName: NonEmpty
    fileBase64: NonEmpty
    mimeType: str = "application/octet-stream"


class KnowledgeChunkInput(StrictModel):
    index: Annotated[int, Field(ge=0)] | None = None
    parentIndex: Annotated[int, Field(ge=0)] | None = None
    sectionPath: ShortText = ""
    content: NonEmpty
    tokenCount: Annotated[int, Field(ge=0)] | None = None
    enabled: bool = True


class KnowledgeIndexInput(StrictModel):
    id: Identifier | None = None
    title: NonEmpty
    categoryId: Identifier | None = None
    status: Literal["draft", "effective", "obsolete"] = "effective"
    purposeId: Identifier
    documentType: ShortText = ""
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=20)
    outline: list[NonEmpty] = Field(default_factory=list, max_length=50)
    templateFamily: ShortText = ""
    templateVariant: ShortText = ""
    version: ShortText = ""
    applicableScenario: ShortText = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    chunks: list[KnowledgeChunkInput] | None = None

class KnowledgeDocumentUpdate(StrictModel):
    title: NonEmpty
    categoryId: Identifier | None = None
    status: Literal["draft", "effective", "obsolete"]
    documentType: ShortText = ""
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=20)
    outline: list[NonEmpty] = Field(default_factory=list, max_length=50)
    templateFamily: ShortText = ""
    templateVariant: ShortText = ""
    version: ShortText = ""
    applicableScenario: ShortText = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
