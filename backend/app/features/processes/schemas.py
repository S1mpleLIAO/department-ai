from __future__ import annotations

from uuid import uuid4

from pydantic import Field, model_validator

from app.core.schemas import Identifier, NonEmpty, StrictModel


class ProcessStepInput(StrictModel):
    id: Identifier = Field(default_factory=lambda: str(uuid4()))
    name: NonEmpty
    objective: NonEmpty
    requiredInputs: list[NonEmpty] = Field(default_factory=list)
    requiredOutputs: list[NonEmpty] = Field(default_factory=list)
    completionCriteria: list[NonEmpty] = Field(default_factory=list)
    instructions: str = ""


class ProcessInput(StrictModel):
    id: Identifier = Field(default_factory=lambda: str(uuid4()))
    name: NonEmpty
    description: str = ""
    steps: list[ProcessStepInput] = Field(min_length=1)

    @model_validator(mode="after")
    def unique_step_ids(self) -> "ProcessInput":
        ids = [step.id for step in self.steps]
        if len(ids) != len(set(ids)):
            raise ValueError("流程步骤 ID 不能重复")
        return self
