from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any, Callable, Literal

from pydantic import BaseModel

from .resolver import Resolver


@dataclass
class Outcome:
    say: str
    data: Any = None
    summary: str | None = None
    before: Any = None
    after: Any = None
    inverse: dict[str, Any] | None = None
    verified: bool | None = None
    ui: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    timeline: list[dict[str, Any]] = field(default_factory=list)
    focus: dict[str, str] = field(default_factory=dict)
    recovery: dict[str, Any] | None = None
    undo_action_id: str | None = None


@dataclass
class ExecContext:
    services: Any
    memory: dict[str, Any]
    session_id: str
    ledger: Any
    today: date
    _resolver: Resolver | None = None

    @property
    def resolver(self) -> Resolver:
        if self._resolver is None:
            self._resolver = Resolver(
                self.services.tasks(include_archived=True),
                self.services.projects(include_archived=True),
                self.memory.setdefault("focus", {}),
            )
        return self._resolver

    def invalidate(self) -> None:
        self._resolver = None


Prepare = Callable[[dict[str, Any], ExecContext], tuple[dict[str, Any], str | None]]
Execute = Callable[[dict[str, Any], ExecContext], Outcome]
Amend = Callable[[dict[str, Any], str, ExecContext], dict[str, Any] | None]


@dataclass
class Capability:
    name: str
    description: str
    args_model: type[BaseModel]
    examples: list[str]
    mode: Literal["read", "write", "ui"]
    confirmation: Literal["none", "required"]
    reversible: bool
    label: str
    execute: Execute
    prepare: Prepare | None = None
    amend: Amend | None = None
    required_context: list[str] = field(default_factory=list)

    def schema(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "mode": self.mode,
            "confirmation": self.confirmation,
            "reversible": self.reversible,
            "required_context": self.required_context,
            "input_schema": self.args_model.model_json_schema(),
            "examples": self.examples,
        }


class CapabilityRegistry:
    def __init__(self, capabilities: list[Capability]):
        self._items = {cap.name: cap for cap in capabilities}

    def get(self, name: str) -> Capability | None:
        return self._items.get(name)

    def names(self) -> list[str]:
        return list(self._items)

    def catalog(self) -> list[dict[str, Any]]:
        return [cap.schema() for cap in self._items.values()]

    def compact_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "name": cap.name,
                "description": cap.description,
                "arguments": list(cap.args_model.model_json_schema().get("properties", {})),
                "examples": cap.examples[:2],
            }
            for cap in self._items.values()
        ]
