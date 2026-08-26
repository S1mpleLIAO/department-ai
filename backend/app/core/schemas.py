from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


NonEmpty = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
Identifier = Annotated[
    str,
    StringConstraints(strip_whitespace=True, pattern=r"^[a-z0-9][a-z0-9-]{0,63}$"),
]
ShortText = Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChunkingSettings(StrictModel):
    mode: Literal["structure", "general", "parent-child"]
    delimiter: str = "\n\n"
    maxTokens: int = Field(ge=100, le=8000)
    overlapTokens: int = Field(ge=0, le=2000)
    parentMaxTokens: int = Field(ge=300, le=8000)
    childMaxTokens: int = Field(ge=100, le=4000)
    childOverlapTokens: int = Field(ge=0, le=1000)
    cleanWhitespace: bool = True
    removeUrlsEmails: bool = False

    @model_validator(mode="after")
    def validate_overlap(self) -> "ChunkingSettings":
        if self.overlapTokens >= self.maxTokens:
            raise ValueError("重叠 Token 必须小于每块最大 Token")
        if self.childOverlapTokens >= self.childMaxTokens:
            raise ValueError("子块重叠 Token 必须小于子块最大 Token")
        if self.childMaxTokens > self.parentMaxTokens:
            raise ValueError("子块最大 Token 不能大于父块最大 Token")
        return self
