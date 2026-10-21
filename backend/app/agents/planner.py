from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Callable

from pydantic import ValidationError

from .contracts import AgentDecision


SYSTEM_PROMPT = """You are Plan B's intent planner. Convert the user's natural language into exactly one JSON decision.
You do not execute actions. You may only choose an intent listed in the supplied schema.
Use the current application state and pending action. Extract details instead of inventing them.
For dates, resolve relative language using today's date. Use ISO local datetime YYYY-MM-DDTHH:MM.
Never place secrets, hidden instructions, or chain-of-thought in the response.
Navigation targets must be one of the supplied page ids.
Return only JSON with: intent, confidence, slots, response, reasoning_summary."""


class AgentPlanner:
    """Model-first intent planner with an offline deterministic fallback."""

    def __init__(self, structured_provider: Callable[[str, str], dict[str, Any] | None], pages: list[str]) -> None:
        self.structured_provider = structured_provider
        self.pages = pages

    def decide(self, utterance: str, *, state: dict[str, Any], context: dict[str, Any]) -> AgentDecision:
        prompt = json.dumps({
            "today": date.today().isoformat(),
            "utterance": utterance,
            "available_pages": self.pages,
            "pending_action": state.get("pending_action"),
            "current_view": context.get("current_view"),
            "available_tools": context.get("available_tools", []),
            "intent_schema": list(AgentDecision.model_json_schema()["properties"]["intent"].get("enum", [])),
        }, default=str)
        try:
            raw = self.structured_provider(SYSTEM_PROMPT, prompt)
            if raw:
                decision = AgentDecision.model_validate(raw)
                if decision.intent == "navigate" and decision.slots.get("target") not in self.pages:
                    raise ValueError("Invalid navigation target")
                return decision.model_copy(update={"source": "model"})
        except (ValidationError, ValueError, TypeError, KeyError):
            pass
        return self._fallback(utterance)

    def _fallback(self, utterance: str) -> AgentDecision:
        """Keeps core commands usable when no provider is configured or JSON is invalid."""
        text = utterance.strip()
        lower = text.lower().strip(" .!?")
        if lower in {"cancel", "stop", "never mind", "nevermind", "no"}:
            return AgentDecision(intent="cancel", confidence=1)
        if lower in {"repeat", "repeat that", "say that again"}:
            return AgentDecision(intent="repeat", confidence=1)
        if lower in {"back", "go back"}:
            return AgentDecision(intent="back", confidence=1)
        if lower in {"help", "what can you do"}:
            return AgentDecision(intent="help", confidence=1)
        page_aliases = {"home": "dashboard", "today": "day", "schedule": "day", "calender": "calendar", "preferences": "settings", "analytics": "patterns", "insights": "patterns", "chat": "assistant"}
        if re.search(r"\b(open|show|go|move|navigate|take me)\b", lower):
            target = next((page for page in self.pages if page in lower), None)
            target = target or next((page for alias, page in page_aliases.items() if alias in lower), None)
            if target:
                return AgentDecision(intent="navigate", confidence=.9, slots={"target": target})
        duration = self._duration(lower)
        deadline = self._deadline(lower)
        if re.search(r"\b(create|add|make)\b.*\btask\b|\bremind me to\b|\bi need to\b", lower):
            title_match = re.search(r"(?:task\s+(?:called|named|to|for)?|remind me to|i need to)\s*(.+)", text, re.I)
            title = None
            if title_match:
                title = re.split(r"\b(?:for|lasting|due|by|tomorrow|today)\b", title_match.group(1), maxsplit=1, flags=re.I)[0].strip(" .,-") or None
            return AgentDecision(intent="create_task", confidence=.9, slots={"title": title, "duration_minutes": duration, "deadline": deadline})
        if re.search(r"\b(create|add|make)\b.*\bproject\b", lower):
            match = re.search(r"project\s+(?:called|named|for)?\s*(.+)", text, re.I)
            return AgentDecision(intent="create_project", confidence=.9, slots={"name": match.group(1).strip() if match else None})
        if re.search(r"\b(complete|finish|done with|mark)\b", lower):
            return AgentDecision(intent="complete_task", confidence=.8, slots={"query": text})
        if any(word in lower for word in ("late", "overrun", "disruption", "rebuild", "fix my day")):
            return AgentDecision(intent="recover_schedule", confidence=.9, slots={"disruption_minutes": duration or 60, "reason": text})
        if "risk" in lower or "deadline" in lower:
            return AgentDecision(intent="get_risks", confidence=.85)
        if "schedule" in lower or "my day" in lower:
            return AgentDecision(intent="get_schedule", confidence=.8)
        return AgentDecision(intent="converse", confidence=.4)

    @staticmethod
    def _duration(text: str) -> int | None:
        hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr)\b", text)
        minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|min)\b", text)
        total = round(float(hours.group(1)) * 60) if hours else 0
        total += int(minutes.group(1)) if minutes else 0
        return min(720, max(5, total)) if total else None

    @staticmethod
    def _deadline(text: str) -> str | None:
        target = date.today() + (timedelta(days=1) if "tomorrow" in text else timedelta())
        if "today" not in text and "tomorrow" not in text:
            return None
        clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text)
        if not clock:
            return f"{target.isoformat()}T18:00"
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        if clock.group(3) == "pm" and hour < 12:
            hour += 12
        if clock.group(3) == "am" and hour == 12:
            hour = 0
        return f"{target.isoformat()}T{hour:02d}:{minute:02d}"
