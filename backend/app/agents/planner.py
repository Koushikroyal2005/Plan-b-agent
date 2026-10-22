from __future__ import annotations

import json
import re
from datetime import date, timedelta
from typing import Any, Callable

from pydantic import ValidationError

from .contracts import AgentDecision


SYSTEM_PROMPT = """You are Plan B's context-aware dialogue planner. Convert the user's latest message into exactly one JSON decision.
You do not execute actions. You may only choose an intent listed in the supplied schema.
Use the recent conversation, dialogue frame, current application state, and pending action. Resolve follow-ups such as
"yes", "it", "that task", corrections, and resumed requests from that context. Extract details instead of inventing them.
"Can I still finish everything?" is feasibility analysis, never a request to complete a task.
Only choose complete_task for an explicit request to mark a named task done.
If a message contains multiple actions, choose the first safe actionable intent and mention the remaining request in response.
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
        # Common product commands and replies to an active form should feel instant.
        # Keep the model for genuinely ambiguous language instead of paying network
        # latency for commands the deterministic parser already understands.
        fast = self._fallback(utterance)
        if state.get("pending_action") or (fast.intent != "converse" and fast.confidence >= 0.8):
            return fast.model_copy(update={"source": "deterministic"})
        prompt = json.dumps({
            "today": date.today().isoformat(),
            "utterance": utterance,
            "available_pages": self.pages,
            "pending_action": state.get("pending_action"),
            "suspended_actions": state.get("suspended_actions", []),
            "dialogue_frame": state.get("dialogue", {}),
            "recent_turns": context.get("recent_turns", []),
            "schedule_facts": context.get("schedule_facts", {}),
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
        return fast

    def _fallback(self, utterance: str) -> AgentDecision:
        """Keeps core commands usable when no provider is configured or JSON is invalid."""
        text = utterance.strip()
        lower = text.lower().strip(" .!?")
        lower = re.sub(r"\ba\.?\s*m\.?(?=\W|$)", "am", lower)
        lower = re.sub(r"\bp\.?\s*m\.?(?=\W|$)", "pm", lower)
        if lower in {"cancel", "stop", "never mind", "nevermind", "no"}:
            return AgentDecision(intent="cancel", confidence=1)
        if lower in {"repeat", "repeat that", "say that again"}:
            return AgentDecision(intent="repeat", confidence=1)
        if lower in {"back", "go back"}:
            return AgentDecision(intent="back", confidence=1)
        if lower in {"help", "what can you do"}:
            return AgentDecision(intent="help", confidence=1)
        if lower in {"continue", "resume", "continue that", "resume that", "continue task", "go back to the task"}:
            return AgentDecision(intent="resume", confidence=1)
        page_aliases = {"home": "dashboard", "today": "dashboard", "day": "dashboard", "schedule": "dashboard", "calender": "calendar", "preferences": "settings", "analytics": "patterns", "insights": "patterns", "chat": "assistant", "replan": "dashboard", "recovery": "dashboard"}
        if re.search(r"\b(open|show|go|move|navigate|take me)\b", lower):
            target = next((page for page in self.pages if page in lower), None)
            target = target or next((page for alias, page in page_aliases.items() if alias in lower), None)
            if target:
                return AgentDecision(intent="navigate", confidence=.9, slots={"target": target})
        duration = self._duration(lower)
        deadline = self._deadline(lower)
        if re.search(r"\b(can|could|will|do)\s+i\s+(still\s+)?(finish|fit|complete)|\benough time\b|\bfinish everything\b|\bfit everything\b", lower):
            return AgentDecision(intent="assess_feasibility", confidence=.96)
        if re.search(r"\b(create|add|make)\b.*\btask\b|\bremind me to\b|\bi need to\b|^task\b|\b(?:create|make|build)\b.*\bschedule\b", lower):
            title = self._task_title(text)
            fixed_start = deadline if re.search(r"\b(at|from)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)\b", lower) else None
            range_duration = self._range_duration(lower)
            return AgentDecision(intent="create_task", confidence=.94, slots={
                "title": title, "duration_minutes": range_duration or duration,
                "deadline": deadline, "fixed_start": fixed_start,
                "flexibility": "fixed" if fixed_start else "flexible",
            })
        if re.search(r"\b(create|add|make)\b.*\bproject\b", lower):
            match = re.search(r"project\s+(?:called|named|for)?\s*(.+)", text, re.I)
            return AgentDecision(intent="create_project", confidence=.9, slots={"name": match.group(1).strip() if match else None})
        if re.search(r"\b(?:mark|set)\b.+\b(?:complete|done)\b|\b(?:complete|finish)\s+(?:the\s+)?(?:task\s+)?[\w]", lower) or lower.startswith("done with "):
            return AgentDecision(intent="complete_task", confidence=.9, slots={"query": text})
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
        days = 2 if "day after tomorrow" in text or "after tomorrow" in text else (1 if "tomorrow" in text else 0)
        target = date.today() + timedelta(days=days)
        if "today" not in text and "tomorrow" not in text and "tonight" not in text:
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

    @staticmethod
    def _task_title(text: str) -> str | None:
        text = re.sub(r"\ba\.?\s*m\.?(?=\W|$)", "am", text, flags=re.I)
        text = re.sub(r"\bp\.?\s*m\.?(?=\W|$)", "pm", text, flags=re.I)
        trailing = re.search(
            r"^\s*task\b.*?\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)\s+(.+)$",
            text, re.I,
        )
        if trailing:
            title = re.sub(r"^(?:to|on)\s+", "", trailing.group(1), flags=re.I).strip(" .,-")
            if title:
                return title[:160]
        body = re.sub(
            r"^\s*(?:please\s+)?(?:create|add|make|build)\s+(?:a\s+)?(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)\s+)?(?:task|schedule)\b",
            "", text, flags=re.I,
        )
        if body == text:
            body = re.sub(r"^\s*(?:remind me to|i need to)\s+", "", text, flags=re.I)
        body = re.sub(r"^\s*(?:called|named|to|for)\b\s*", "", body, flags=re.I)
        body = re.split(
            r"\b(?:for\s+\d|lasting\s+\d|due\b|by\b|day after tomorrow\b|after tomorrow\b|today\b|tomorrow\b|at\s+\d|from\s+\d)",
            body, maxsplit=1, flags=re.I,
        )[0]
        title = re.sub(r"\s+", " ", body).strip(" .,-")
        return title[:160] if title and title.lower() not in {"task", "a task", "it"} else None

    @staticmethod
    def _range_duration(text: str) -> int | None:
        match = re.search(
            r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(?:to|until|till)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
            text,
        )
        if not match:
            return None
        start_h, start_m = int(match.group(1)), int(match.group(2) or 0)
        end_h, end_m = int(match.group(4)), int(match.group(5) or 0)
        start_meridiem = match.group(3) or match.group(6)
        end_meridiem = match.group(6)
        if start_meridiem == "pm" and start_h < 12:
            start_h += 12
        if start_meridiem == "am" and start_h == 12:
            start_h = 0
        if end_meridiem == "pm" and end_h < 12:
            end_h += 12
        if end_meridiem == "am" and end_h == 12:
            end_h = 0
        minutes = (end_h * 60 + end_m) - (start_h * 60 + start_m)
        return minutes if 5 <= minutes <= 720 else None
