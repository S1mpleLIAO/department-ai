from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from app.core.schemas import ChunkingSettings, NonEmpty, StrictModel


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
