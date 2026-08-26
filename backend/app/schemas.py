from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field, StringConstraints, model_validator

from app.core.schemas import ChunkingSettings, Identifier, NonEmpty, ShortText, StrictModel


SkillName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


class CategoryInput(StrictModel):
    name: NonEmpty
    parentId: Identifier | None = None


class CategoryOrderInput(StrictModel):
    parentId: Identifier | None = None
    ids: list[Identifier] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_ids(self) -> "CategoryOrderInput":
        if len(self.ids) != len(set(self.ids)):
            raise ValueError("目录 ID 不能重复")
        return self


class RetrievalSettings(StrictModel):
    vectorRecall: int = Field(ge=1, le=100)
    rerankTopN: int = Field(ge=1, le=50)
    recommendCount: int = Field(ge=1, le=10)
    scoreThreshold: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_recall(self) -> "RetrievalSettings":
        if self.rerankTopN > self.vectorRecall:
            raise ValueError("Rerank 保留数量不能大于向量召回数量")
        if self.recommendCount > self.rerankTopN:
            raise ValueError("模板推荐数量不能大于 Rerank 保留数量")
        return self


class AssistantSettingsInput(StrictModel):
    role: NonEmpty
    principles: list[NonEmpty] = Field(min_length=1, max_length=30)
    defaultLanguage: Literal["zh-CN", "en"] = "zh-CN"
    draftByDefault: bool = True
    askWhenMissing: bool = True


class DepartmentSettingsInput(StrictModel):
    assistant: AssistantSettingsInput
    chunking: ChunkingSettings
    retrieval: RetrievalSettings
    embeddingModel: NonEmpty
    rerankModel: NonEmpty


class SkillInput(StrictModel):
    name: SkillName
    description: NonEmpty
    instructions: NonEmpty
    enabled: bool = True


class SkillResourceInput(StrictModel):
    contentBase64: NonEmpty


class KnowledgePurposeInput(StrictModel):
    name: NonEmpty
    description: ShortText = ""
    canGenerateTemplate: bool = False
    chunkBody: bool = True
    inheritChunking: bool = True
    chunkSettings: ChunkingSettings

    @model_validator(mode="after")
    def validate_capabilities(self) -> "KnowledgePurposeInput":
        if not self.canGenerateTemplate and not self.chunkBody:
            raise ValueError("文档用途至少需要启用生成模板或正文检索中的一项")
        return self


class KnowledgePreviewInput(StrictModel):
    fileName: NonEmpty
    fileBase64: NonEmpty
    mimeType: str = "application/octet-stream"
    chunkSettings: ChunkingSettings


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


class TemplateSearchInput(StrictModel):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=10)


class KnowledgeSearchInput(StrictModel):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    documentId: Identifier | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
