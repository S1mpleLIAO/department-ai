from typing import Literal
from uuid import uuid4
from pydantic import Field
from app.core.schemas import StrictModel


class DraftInput(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-z0-9-]{1,64}$")
    kind: Literal["processes", "knowledge", "skills"]
    data: dict
    previewId: str | None = Field(default=None, pattern=r"^[a-z0-9-]{1,64}$")


class DraftUpdate(StrictModel):
    revision: int = Field(ge=1)
    data: dict


class EditInput(StrictModel):
    id: str = Field(default_factory=lambda: str(uuid4()), pattern=r"^[a-z0-9-]{1,64}$")
    kind: Literal["processes", "knowledge", "skills"]
    targetId: str = Field(min_length=1, max_length=200)


class Transition(StrictModel):
    revision: int = Field(ge=1)
    reason: str = Field(default="", max_length=2000)
