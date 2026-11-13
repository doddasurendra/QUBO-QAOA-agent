from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, ClassVar, Dict, Type

from pydantic import BaseModel

from ..core.model import CompiledModel, Model


class IndustryProblem(ABC):
    key: ClassVar[str]
    industry: ClassVar[str]
    title: ClassVar[str]
    description: ClassVar[str]
    formulation: ClassVar[str]       # human-readable math
    Input: ClassVar[Type[BaseModel]]
    limitations: ClassVar[str] = ""

    @abstractmethod
    def build_model(self, data: BaseModel) -> Model: ...

    @abstractmethod
    def interpret(self, data: BaseModel, assignment: Dict[str, int]) -> Dict[str, Any]: ...

    @abstractmethod
    def example(self) -> dict: ...

    def parse(self, raw: dict) -> BaseModel:
        return self.Input.model_validate(raw)

    def compile(self, raw: dict, penalty_scale: float = 1.0) -> tuple[BaseModel, CompiledModel]:
        data = self.parse(raw)
        model = self.build_model(data)
        model.metadata.update({"industry_problem": self.key})
        return data, model.compile(penalty_scale)

    def describe(self) -> dict:
        return {"key": self.key, "industry": self.industry, "title": self.title,
                "description": self.description, "formulation": self.formulation,
                "limitations": self.limitations, "input_schema": self.Input.model_json_schema(),
                "example": self.example(), "example_is_sample_data": True}
