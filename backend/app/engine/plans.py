from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    capability: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    confirmed: bool = False
    prepared: bool = False


class Plan(BaseModel):
    goal: str = ""
    acknowledgement: str | None = None
    steps: list[PlanStep] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    reply: str | None = None
    confidence: float = Field(default=0.8, ge=0, le=1)
    source: Literal["model", "rules"] = "rules"
