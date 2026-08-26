from __future__ import annotations

from pydantic import Field

from app.core.schemas import Identifier, NonEmpty, StrictModel


class TemplateSearchInput(StrictModel):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    limit: int | None = Field(default=None, ge=1, le=10)


class KnowledgeSearchInput(StrictModel):
    query: NonEmpty
    keywords: list[NonEmpty] = Field(default_factory=list, max_length=10)
    documentId: Identifier | None = None
    limit: int | None = Field(default=None, ge=1, le=50)
