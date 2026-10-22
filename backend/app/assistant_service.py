from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

from app.agents import AgentPlanner, ToolRegistry, ToolSpec
from app.agents.contracts import CreateProjectArgs, CreateTaskArgs, CompleteTaskArgs, RecoveryArgs


ROUTES = {
    "dashboard": ("dashboard", "home", "my day", "today", "schedule"),
    "calendar": ("calendar", "calender"),
    "tasks": ("tasks", "task list", "projects", "project list"),
    "assistant": ("assistant", "chat", "plan b"),
    "recovery": ("recovery", "replan", "repair"),
    "patterns": ("patterns", "analytics", "insights", "focus score"),
    "mcp": ("mcp", "tools"),
    "settings": ("settings", "preferences"),
}

YES = {"yes", "yeah", "yep", "confirm", "confirmed", "do it", "create it", "apply it", "okay", "ok"}
NO = {"no", "nope", "cancel", "stop", "never mind", "nevermind", "don't", "do not"}


def _clean(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip())


def _duration(text: str) -> int | None:
    hours = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?|hr)\b", text, re.I)
    minutes = re.search(r"(\d+)\s*(?:minutes?|mins?|min)\b", text, re.I)
    total = 0
    if hours:
        total += round(float(hours.group(1)) * 60)
    if minutes:
        total += int(minutes.group(1))
    return min(720, max(5, total)) if total else None


def _when(text: str) -> str | None:
    lower = text.lower()
    target = date.today()
    if "tomorrow" in lower:
        target += timedelta(days=1)
    elif "today" not in lower and not re.search(r"\d{4}-\d{2}-\d{2}", lower):
        return None
    iso = re.search(r"\d{4}-\d{2}-\d{2}", lower)
    if iso:
        try:
            target = date.fromisoformat(iso.group())
        except ValueError:
            return None
    clock = re.search(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", lower)
    if not clock:
        return f"{target.isoformat()}T18:00"
    hour, minute, meridiem = int(clock.group(1)), int(clock.group(2) or 0), clock.group(3)
    if meridiem == "pm" and hour < 12:
        hour += 12
    if meridiem == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    return f"{target.isoformat()}T{hour:02d}:{minute:02d}"


def _task_title(text: str) -> str | None:
    patterns = [
        r"(?:create|add|make)\s+(?:a\s+)?task\s+(?:called|named|to|for)?\s*(.+)",
        r"(?:remind me to|i need to)\s+(.+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, re.I)
        if match:
            value = re.split(r"\b(?:for|lasting|due|by|tomorrow|today)\b", match.group(1), maxsplit=1, flags=re.I)[0]
            value = _clean(value.strip(" .,-"))
            if value and value.lower() not in {"a task", "task", "it"}:
                return value[:160]
    return None


def _project_name(text: str) -> str | None:
    match = re.search(r"(?:create|add|make)\s+(?:a\s+)?project\s+(?:called|named|for)?\s*(.+)", text, re.I)
    return _clean(match.group(1).strip(" .,-"))[:100] if match and match.group(1).strip() else None


class AssistantService:
    def __init__(
        self,
        db: Callable[[], Any],
        tools: dict[str, Callable[..., Any]],
        provider: Callable[[str], str | None],
        structured_provider: Callable[[str, str], dict[str, Any] | None] | None = None,
    ) -> None:
        self.db = db
        self.tools = tools
        self.provider = provider
        self.planner = AgentPlanner(structured_provider or (lambda _system, _prompt: None), list(ROUTES))
        self.registry = ToolRegistry([
            ToolSpec("create_task", "Create a validated task", "write", lambda **v: tools["create_task"](v), CreateTaskArgs),
            ToolSpec("create_project", "Create a project", "write", lambda **v: tools["create_project"](v), CreateProjectArgs),
            ToolSpec("complete_task", "Mark a task complete", "write", lambda **v: tools["complete_task"](v["task_id"]), CompleteTaskArgs),
            ToolSpec("list_tasks", "Read open tasks", "read", lambda **_: tools["list_tasks"]()),
            ToolSpec("list_projects", "Read active projects", "read", lambda **_: tools["list_projects"]()),
            ToolSpec("get_day_schedule", "Read the current schedule", "read", lambda **_: tools["day"]()),
            ToolSpec("check_deadline_risks", "Calculate schedule risks", "read", lambda **_: tools["risks"]()),
            ToolSpec("generate_recovery_options", "Build deterministic recovery options", "high_impact", lambda **v: tools["recovery"](v["disruption_minutes"], v["reason"]), RecoveryArgs),
        ])

    def _load(self, session_id: str) -> dict[str, Any]:
        with self.db() as conn:
            row = conn.execute("SELECT state_json FROM assistant_sessions WHERE id=?", (session_id,)).fetchone()
        return json.loads(row[0]) if row else {}

    def _recent_turns(self, session_id: str) -> list[dict[str, Any]]:
        with self.db() as conn:
            rows = conn.execute(
                "SELECT utterance,response_json FROM assistant_turns WHERE session_id=? ORDER BY created_at DESC LIMIT 6",
                (session_id,),
            ).fetchall()
        return [
            {"user": row[0], "assistant": json.loads(row[1]).get("say", "")}
            for row in reversed(rows)
        ]

    def _save(self, session_id: str, state: dict[str, Any], utterance: str, response: dict[str, Any], idempotency_key: str | None = None) -> None:
        stamp = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        with self.db() as conn:
            conn.execute(
                "INSERT INTO assistant_sessions(id,state_json,last_response_json,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json,last_response_json=excluded.last_response_json,updated_at=excluded.updated_at",
                (session_id, json.dumps(state), json.dumps(response), stamp),
            )
            conn.execute(
                "INSERT INTO assistant_turns(id,session_id,utterance,response_json,created_at) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), session_id, utterance, json.dumps(response), stamp),
            )
            if idempotency_key:
                conn.execute(
                    "INSERT OR REPLACE INTO assistant_idempotency(key,session_id,response_json,created_at) VALUES(?,?,?,?)",
                    (idempotency_key, session_id, json.dumps(response), stamp),
                )

    def _response(self, say: str, *, state: str = "completed", pending: dict[str, Any] | None = None,
                  commands: list[dict[str, Any]] | None = None, tools: list[dict[str, str]] | None = None,
                  recovery: Any = None, listen_again: bool = False, confirmation: bool = False) -> dict[str, Any]:
        result = {
            "turn_id": str(uuid.uuid4()), "message": say, "say": say, "display": say,
            "state": state, "pending_action": pending, "ui_commands": commands or [],
            "tools": tools or [], "tool_events": tools or [], "requires_confirmation": confirmation,
            "listen_again": listen_again,
        }
        if recovery is not None:
            result["recovery"] = recovery
        return result

    def _ask_task(self, action: dict[str, Any]) -> dict[str, Any]:
        slots = action["slots"]
        if not slots.get("title"):
            return self._response("What task should I create?", state="asking", pending=action, listen_again=True)
        if not slots.get("duration_minutes"):
            return self._response(f"How long should {slots['title']} take?", state="asking", pending=action, listen_again=True)
        action["status"] = "confirming"
        due = f", due {slots['deadline'].replace('T', ' at ')}" if slots.get("deadline") else ""
        say = f"Create {slots['title']} for {slots['duration_minutes']} minutes{due}?"
        return self._response(say, state="confirming", pending=action, listen_again=True, confirmation=True)

    def _continue(self, state: dict[str, Any], text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        action = state["pending_action"]
        lower = text.lower().strip(" .!?")
        if any(value == lower or value in lower for value in NO):
            state.pop("pending_action", None)
            return state, self._response("Cancelled. I did not change anything.", commands=[{"type": "close_modal"}])
        if action["status"] == "confirming":
            if not any(value == lower or value in lower for value in YES):
                return state, self._response("Please say yes to confirm, or cancel.", state="confirming", pending=action, listen_again=True, confirmation=True)
            if action["intent"] == "task.create":
                task = self.registry.execute("create_task", action["slots"])
                state.pop("pending_action", None)
                return state, self._response(f"Created {task['title']}. I opened it in Tasks.", commands=[{"type": "navigate", "target": "tasks"}, {"type": "highlight", "target": "task", "id": task["id"]}, {"type": "close_modal"}], tools=[{"tool": "create_task", "status": "complete"}])
            if action["intent"] == "project.create":
                project = self.registry.execute("create_project", action["slots"])
                state.pop("pending_action", None)
                return state, self._response(f"Created the {project['name']} project.", commands=[{"type": "navigate", "target": "tasks"}, {"type": "highlight", "target": "project", "id": project["id"]}], tools=[{"tool": "create_project", "status": "complete"}])
            if action["intent"] == "task.complete":
                task = self.registry.execute("complete_task", {"task_id": action["slots"]["task_id"]})
                state.pop("pending_action", None)
                return state, self._response(f"Marked {task['title']} complete.", commands=[{"type": "navigate", "target": "tasks"}], tools=[{"tool": "update_task", "status": "complete"}])
        if action["intent"] == "task.create":
            slots = action["slots"]
            if not slots.get("title"):
                slots["title"] = _task_title("create task " + text) or _clean(text)[:160]
            elif not slots.get("duration_minutes"):
                slots["duration_minutes"] = _duration(text)
                slots["deadline"] = _when(text) or slots.get("deadline")
                if not slots["duration_minutes"]:
                    return state, self._response("Tell me a duration such as 30 minutes or 2 hours.", state="asking", pending=action, listen_again=True)
            return state, self._ask_task(action)
        if action["intent"] == "project.create":
            action["slots"]["name"] = _clean(text)[:100]
            action["status"] = "confirming"
            return state, self._response(f"Create a project called {action['slots']['name']}?", state="confirming", pending=action, listen_again=True, confirmation=True)
        return state, self._response("I lost the pending action, so I cancelled it safely.")

    def turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = _clean(payload.get("utterance") or payload.get("message") or "")
        session_id = payload.get("session_id") or "default"
        idempotency_key = payload.get("idempotency_key")
        if idempotency_key:
            with self.db() as conn:
                cached = conn.execute(
                    "SELECT response_json FROM assistant_idempotency WHERE key=? AND session_id=?",
                    (idempotency_key, session_id),
                ).fetchone()
            if cached:
                return json.loads(cached[0])
        state = self._load(session_id)
        decision = self.planner.decide(
            text,
            state=state,
            context={
                "current_view": payload.get("current_view"),
                "available_tools": self.registry.catalog(),
            },
        )
        intent, slots = decision.intent, decision.slots
        if intent == "repeat":
            with self.db() as conn:
                row = conn.execute("SELECT last_response_json FROM assistant_sessions WHERE id=?", (session_id,)).fetchone()
            return json.loads(row[0]) if row else self._response("There is nothing to repeat yet.")
        if intent == "help":
            result = self._response("I can navigate Plan B, create tasks and projects, complete tasks, explain your day and risks, and build recovery options. You can also say stop, cancel, repeat, or go back.", commands=[{"type": "show_help"}])
        elif intent == "back":
            result = self._response("Going back.", commands=[{"type": "back"}])
        elif state.get("pending_action"):
            state, result = self._continue(state, text)
        elif intent == "cancel":
            result = self._response("There is no pending action to cancel.")
        elif intent == "navigate":
            route = slots.get("target")
            result = self._response(f"Opening {route.replace('_', ' ')}." if route else "I could not find that page.", commands=[{"type": "navigate", "target": route}] if route else [])
        elif intent == "create_task":
            action = {"intent": "task.create", "status": "collecting", "slots": {"title": slots.get("title"), "duration_minutes": slots.get("duration_minutes"), "deadline": slots.get("deadline"), "description": slots.get("description", ""), "priority": slots.get("priority", "medium"), "flexibility": slots.get("flexibility", "flexible"), "splittable": slots.get("splittable", True), "tags": slots.get("tags", []), "project_id": slots.get("project_id"), "earliest_start": slots.get("earliest_start"), "fixed_start": slots.get("fixed_start")}}
            state["pending_action"] = action
            result = self._ask_task(action)
        elif intent == "create_project":
            name = slots.get("name")
            action = {"intent": "project.create", "status": "confirming" if name else "collecting", "slots": {"name": name, "description": "", "color": "#657c9a", "target_date": None}}
            state["pending_action"] = action
            result = self._response(f"Create a project called {name}?" if name else "What should I call the project?", state=action["status"] if name else "asking", pending=action, listen_again=True, confirmation=bool(name))
        elif intent == "complete_task":
            tasks = self.registry.execute("list_tasks")
            query = str(slots.get("query") or slots.get("title") or text).lower()
            task_id = slots.get("task_id")
            task = next((item for item in tasks if item["id"] == task_id), None) if task_id else None
            task = task or next((item for item in tasks if item["title"].lower() in query), None)
            if not task:
                result = self._response("I could not match that to an open task. Say the full task name.")
            else:
                action = {"intent": "task.complete", "status": "confirming", "slots": {"task_id": task["id"], "title": task["title"]}}
                state["pending_action"] = action
                result = self._response(f"Mark {task['title']} complete?", state="confirming", pending=action, listen_again=True, confirmation=True)
        elif intent == "recover_schedule":
            minutes = int(slots.get("disruption_minutes") or 60)
            recovery = self.registry.execute("generate_recovery_options", {"disruption_minutes": minutes, "reason": slots.get("reason") or text})
            result = self._response(f"I built and validated recovery options for the {minutes}-minute disruption. Nothing has changed until you approve one.", commands=[{"type": "navigate", "target": "recovery"}], tools=[{"tool": "find_affected_tasks", "status": "complete"}, {"tool": "generate_recovery_options", "status": "complete"}, {"tool": "validate_schedule", "status": "complete"}], recovery=recovery)
        elif intent == "get_risks":
            risk_result = self.registry.execute("check_deadline_risks")
            risks = risk_result.get("risks", []) if isinstance(risk_result, dict) else risk_result
            say = risks[0]["reason"] if risks else "Your current plan has no calculated deadline risk."
            result = self._response(say, tools=[{"tool": "check_deadline_risks", "status": "complete"}])
        elif intent == "get_schedule":
            day = self.registry.execute("get_day_schedule")
            result = self._response(f"You have {len(day['blocks'])} scheduled blocks and {day['metrics']['free_buffer_minutes']} minutes of free buffer.", commands=[{"type": "navigate", "target": "dashboard"}], tools=[{"tool": "get_day_schedule", "status": "complete"}])
        else:
            # The planner is also the conversational agent and must provide the reply
            # in its structured decision. Avoid a second LLM call on fallback/timeouts.
            reply = decision.response if decision.source == "model" else None
            result = self._response(reply or "I can control Plan B tasks, projects, calendar, recovery, patterns, and settings. Try saying: create a task, or open calendar.")
        result["agent"] = {"role": "planner", "intent": intent, "confidence": decision.confidence, "source": decision.source, "max_steps": 6}
        self._save(session_id, state, text, result, idempotency_key)
        return result
