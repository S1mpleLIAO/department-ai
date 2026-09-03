from __future__ import annotations

from pydantic import Field, model_validator

from app.core.schemas import Identifier, NonEmpty, ShortText, StrictModel


class SearchContextInput(StrictModel):
    processId: Identifier | None = None
    stepId: Identifier | None = None
    taskScenario: ShortText = ""

    @model_validator(mode="after")
    def validate_context(self) -> "SearchContextInput":
        has_process = self.processId is not None or self.stepId is not None
        if has_process and (self.processId is None or self.stepId is None):
            raise ValueError("流程检索上下文必须同时提供流程和步骤")
        if has_process and self.taskScenario:
            raise ValueError("流程步骤和独立任务场景不能同时作为检索上下文")
        return self


class TemplateSearchInput(SearchContextInput):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=10)


class KnowledgeSearchInput(SearchContextInput):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    documentId: Identifier | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
