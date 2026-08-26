from __future__ import annotations

from typing import Annotated

from pydantic import StringConstraints

from app.core.schemas import NonEmpty, StrictModel


SkillName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=64,
        pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$",
    ),
]


class SkillInput(StrictModel):
    name: SkillName
    description: NonEmpty
    instructions: NonEmpty
    enabled: bool = True


class SkillResourceInput(StrictModel):
    contentBase64: NonEmpty
