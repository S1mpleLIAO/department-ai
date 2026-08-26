from __future__ import annotations

from pydantic import Field, model_validator

from app.core.schemas import ChunkingSettings, Identifier, NonEmpty, ShortText, StrictModel


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
