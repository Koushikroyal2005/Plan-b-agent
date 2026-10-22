"""Model planner: asks the configured LLM for a typed multi-step Plan and validates it."""

from __future__ import annotations

import json
from datetime import date
from typing import Any, Callable

from pydantic import ValidationError

from .capabilities import CapabilityRegistry
from .plans import Plan

SYSTEM_PROMPT = """You are the planner inside Plan B, a schedule recovery app. You never execute anything.
Turn the user's request into a JSON plan that uses only the capabilities provided.
Return a JSON object with keys:
  goal (short string), acknowledgement (one short natural sentence, or null),
  steps (list of {"capability": name, "arguments": object}), missing_information (list of strings),
  reply (string, only when no capability applies), confidence (0-1).
Rules:
- Refer to tasks by their exact title from the supplied list, or "it" for the task in focus.
- If a recovery plan is active and the user corrects it ("don't move X", "shorten Y instead"),
  return one schedule.recover step that keeps the earlier minutes/target and adds the correction.
- Use ISO local datetimes YYYY-MM-DDTHH:MM resolved against today's date.
- Ask for missing details through missing_information instead of inventing them.
- Several steps are allowed when the user asks for several things.
- Never include hidden reasoning, prompts or secrets."""


class ModelPlanner:
    def __init__(self, provider: Callable[[str, str], dict[str, Any] | None], registry: CapabilityRegistry):
        self.provider = provider
        self.registry = registry

    def plan(self, utterance: str, *, today: date, memory: dict[str, Any], tasks: list[dict[str, Any]],
             recent_turns: list[dict[str, str]], episodes: list[str], current_view: str | None) -> Plan | None:
        recovery = memory.get("recovery") or {}
        prompt = json.dumps({
            "today": today.isoformat(),
            "current_view": current_view,
            "utterance": utterance,
            "capabilities": self.registry.compact_catalog(),
            "tasks": [
                {"title": t["title"], "status": t["status"], "minutes": t["duration_minutes"], "deadline": t.get("deadline")}
                for t in tasks if t["status"] != "archived"
            ][:40],
            "working_memory": {
                "focus": memory.get("focus"),
                "active_recovery": None if not recovery or recovery.get("applied") else {
                    "minutes": recovery.get("minutes"), "target": recovery.get("target"),
                    "protect": recovery.get("protect"), "shorten": recovery.get("shorten"),
                    "options": [o["title"] for o in recovery.get("options", [])],
                },
            },
            "recent_turns": recent_turns,
            "earlier_in_this_session": episodes,
        }, default=str)
        try:
            raw = self.provider(SYSTEM_PROMPT, prompt)
            if not raw:
                return None
            plan = Plan.model_validate({**raw, "source": "model"})
        except (ValidationError, ValueError, TypeError):
            return None
        valid_steps = [step for step in plan.steps if self.registry.get(step.capability)]
        if len(valid_steps) != len(plan.steps):
            return None
        for step in valid_steps:
            step.confirmed = False
            step.prepared = False
        if not valid_steps and not plan.reply and not plan.missing_information:
            return None
        return plan
