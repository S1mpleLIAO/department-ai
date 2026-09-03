from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import Identifier, NonEmpty, ShortText, StrictModel


OptionalIdentifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^$|^[a-z0-9][a-z0-9-]{0,63}$"),
]


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


class KnowledgeScopeInput(StrictModel):
    scopeType: Literal["global", "task", "process"] = "global"
    applicableProcessId: OptionalIdentifier = ""
    applicableStepId: OptionalIdentifier = ""
    applicableScenario: ShortText = ""

    @model_validator(mode="after")
    def validate_scope(self) -> "KnowledgeScopeInput":
        if self.scopeType == "global":
            self.applicableProcessId = ""
            self.applicableStepId = ""
            self.applicableScenario = ""
        elif self.scopeType == "task":
            if not self.applicableScenario:
                raise ValueError("独立任务场景不能为空")
            self.applicableProcessId = ""
            self.applicableStepId = ""
        elif not self.applicableProcessId or not self.applicableStepId:
            raise ValueError("业务流程范围必须同时选择流程和步骤")
        return self


class KnowledgeIndexInput(KnowledgeScopeInput):
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
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
    chunks: list[KnowledgeChunkInput] | None = None


class KnowledgeDocumentUpdate(KnowledgeScopeInput):
    title: NonEmpty
    categoryId: Identifier | None = None
    status: Literal["draft", "effective", "obsolete"]
    documentType: ShortText = ""
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=20)
    outline: list[NonEmpty] = Field(default_factory=list, max_length=50)
    templateFamily: ShortText = ""
    templateVariant: ShortText = ""
    version: ShortText = ""
    summary: Annotated[str, StringConstraints(strip_whitespace=True, max_length=2000)] = ""
