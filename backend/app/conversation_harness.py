from __future__ import annotations

from typing import Any


class ConversationHarness:
    """Owns dialogue continuity independently of voice, HTTP, and model vendors."""

    max_suspended_actions = 3

    def context(
        self,
        *,
        state: dict[str, Any],
        current_view: str | None,
        tool_catalog: list[dict[str, Any]],
        recent_turns: list[dict[str, Any]],
        schedule_facts: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "current_view": current_view,
            "available_tools": tool_catalog,
            "recent_turns": recent_turns,
            "schedule_facts": schedule_facts,
            "dialogue_frame": state.get("dialogue", {}),
        }

    def suspend(self, state: dict[str, Any]) -> None:
        action = state.pop("pending_action", None)
        if not action:
            return
        suspended = state.setdefault("suspended_actions", [])
        if not suspended or suspended[-1] != action:
            suspended.append(action)
            del suspended[:-self.max_suspended_actions]

    @staticmethod
    def resume(state: dict[str, Any]) -> dict[str, Any] | None:
        if state.get("pending_action"):
            return state["pending_action"]
        suspended = state.get("suspended_actions", [])
        if not suspended:
            return None
        action = suspended.pop()
        state["pending_action"] = action
        return action

    @staticmethod
    def draft_note(state: dict[str, Any]) -> str:
        if state.get("suspended_actions"):
            return " I kept your unfinished draft; say 'continue' when you want to resume it."
        return ""

    @staticmethod
    def record(
        state: dict[str, Any],
        *,
        intent: str,
        utterance: str,
        slots: dict[str, Any],
        current_view: str | None,
    ) -> None:
        state["dialogue"] = {
            "last_intent": intent,
            "last_user_message": utterance,
            "last_entities": slots,
            "current_view": current_view,
        }
