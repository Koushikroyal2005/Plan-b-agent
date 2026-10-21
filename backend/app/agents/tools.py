from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal

from pydantic import BaseModel


Risk = Literal["read", "write", "high_impact"]


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    risk: Risk
    handler: Callable[..., Any]
    args_model: type[BaseModel] | None = None

    def schema(self) -> dict[str, Any]:
        return self.args_model.model_json_schema() if self.args_model else {"type": "object", "properties": {}}


class ToolRegistry:
    def __init__(self, specs: list[ToolSpec]) -> None:
        self._tools = {spec.name: spec for spec in specs}

    def catalog(self) -> list[dict[str, Any]]:
        return [
            {"name": spec.name, "description": spec.description, "risk": spec.risk, "input_schema": spec.schema()}
            for spec in self._tools.values()
        ]

    def risk(self, name: str) -> Risk:
        return self._tools[name].risk

    def execute(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        if name not in self._tools:
            raise ValueError(f"Unknown or unauthorized tool: {name}")
        spec = self._tools[name]
        values = arguments or {}
        if spec.args_model:
            values = spec.args_model(**values).model_dump()
        return spec.handler(**values)
