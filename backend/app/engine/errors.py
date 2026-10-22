from __future__ import annotations

from typing import Any


class EngineSignal(Exception):
    """Base for conditions that pause or stop a plan instead of crashing it."""


class NeedsInfo(EngineSignal):
    def __init__(self, question: str, slot: str, kind: str = "text"):
        super().__init__(question)
        self.question = question
        self.slot = slot
        self.kind = kind


class Ambiguous(EngineSignal):
    def __init__(self, reference: str, kind: str, choices: list[dict[str, Any]]):
        names = [c.get("title") or c.get("name") for c in choices]
        listed = ", ".join(names[:-1]) + f" or {names[-1]}" if len(names) > 1 else names[0]
        super().__init__(f"Which {kind} did you mean: {listed}?")
        self.reference = reference
        self.kind = kind
        self.choices = choices


class NotFound(EngineSignal):
    pass


class Refused(EngineSignal):
    """A deterministic rule blocked the step (infeasible, stale, nothing to undo)."""
