from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Intent = Literal[
    "navigate", "create_task", "create_project", "complete_task",
    "get_schedule", "get_risks", "recover_schedule", "help", "back",
    "cancel", "repeat", "converse",
]


class AgentDecision(BaseModel):
    intent: Intent
    confidence: float = Field(default=0.5, ge=0, le=1)
    slots: dict[str, Any] = Field(default_factory=dict)
    response: str | None = None
    reasoning_summary: str = Field(default="", max_length=300)
    source: Literal["model", "fallback"] = "fallback"


class ToolEvent(BaseModel):
    tool: str
    status: Literal["running", "complete", "failed", "blocked"]
    detail: str | None = None


class CreateTaskArgs(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    duration_minutes: int = Field(ge=5, le=720)
    deadline: str | None = None
    description: str = ""
    priority: Literal["low", "medium", "high"] = "medium"
    flexibility: Literal["flexible", "fixed", "buffer"] = "flexible"
    splittable: bool = True
    tags: list[str] = Field(default_factory=list)
    project_id: str | None = None
    earliest_start: str | None = None
    fixed_start: str | None = None


class CreateProjectArgs(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = ""
    color: str = "#657c9a"
    target_date: str | None = None


class CompleteTaskArgs(BaseModel):
    task_id: str = Field(min_length=1)


class RecoveryArgs(BaseModel):
    disruption_minutes: int = Field(ge=1, le=720)
    reason: str = Field(min_length=1, max_length=500)
