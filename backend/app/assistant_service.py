from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, Callable

from app.agents import AgentPlanner, ToolRegistry, ToolSpec
from app.agents.contracts import CreateProjectArgs, CreateTaskArgs, CompleteTaskArgs, RecoveryArgs
from app.conversation_harness import ConversationHarness


ROUTES = {
    "dashboard": ("dashboard", "dashboard", "home"),
    "day": ("day", "my day", "today", "schedule"),
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
    lower = re.sub(r"\ba\.?\s*m\.?(?=\W|$)", "am", lower)
    lower = re.sub(r"\bp\.?\s*m\.?(?=\W|$)", "pm", lower)
    target = date.today()
    if "day after tomorrow" in lower or "after tomorrow" in lower:
        target += timedelta(days=2)
    elif "tomorrow" in lower:
        target += timedelta(days=1)
    elif "today" not in lower and "tonight" not in lower and not re.search(r"\d{4}-\d{2}-\d{2}", lower):
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
    trailing = re.search(
        r"^\s*task\b.*?\bfor\s+\d+(?:\.\d+)?\s*(?:hours?|hrs?|minutes?|mins?)\s+(.+)$",
        text, re.I,
    )
    if trailing:
        value = re.sub(r"^(?:to|on)\s+", "", trailing.group(1), flags=re.I).strip(" .,-")
        if value:
            return _clean(value)[:160]
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
    value = _clean(body.strip(" .,-"))
    return value[:160] if value and value.lower() not in {"a task", "task", "it"} else None


def _range_duration(text: str) -> int | None:
    text = re.sub(r"\ba\.?\s*m\.?(?=\W|$)", "am", text, flags=re.I)
    text = re.sub(r"\bp\.?\s*m\.?(?=\W|$)", "pm", text, flags=re.I)
    match = re.search(
        r"\bfrom\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\s+(?:to|until|till)\s+(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text, re.I,
    )
    if not match:
        return None
    start_h, start_m = int(match.group(1)), int(match.group(2) or 0)
    end_h, end_m = int(match.group(4)), int(match.group(5) or 0)
    start_meridiem = (match.group(3) or match.group(6)).lower()
    end_meridiem = match.group(6).lower()
    if start_meridiem == "pm" and start_h < 12:
        start_h += 12
    if start_meridiem == "am" and start_h == 12:
        start_h = 0
    if end_meridiem == "pm" and end_h < 12:
        end_h += 12
    if end_meridiem == "am" and end_h == 12:
        end_h = 0
    minutes = end_h * 60 + end_m - (start_h * 60 + start_m)
    return minutes if 5 <= minutes <= 720 else None


def _task_slots(text: str) -> dict[str, Any]:
    start = _when(text)
    fixed = bool(start and re.search(r"\b(?:at|from)\s+\d{1,2}(?::\d{2})?\s*(?:am|pm)?\b", text, re.I))
    return {
        "title": _task_title(text),
        "duration_minutes": _range_duration(text) or _duration(text),
        "deadline": start,
        "fixed_start": start if fixed else None,
        "flexibility": "fixed" if fixed else "flexible",
    }


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
        self.harness = ConversationHarness()
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

    def history(self, session_id: str, limit: int = 80) -> dict[str, Any]:
        safe_limit = min(200, max(1, limit))
        with self.db() as conn:
            rows = conn.execute(
                "SELECT id,utterance,response_json,created_at FROM assistant_turns "
                "WHERE session_id=? ORDER BY created_at DESC LIMIT ?",
                (session_id, safe_limit),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            response = json.loads(row[2])
            messages.extend([
                {"id": f"{row[0]}-user", "role": "user", "text": row[1], "status": "Sent", "created_at": row[3]},
                {"id": f"{row[0]}-assistant", "role": "assistant", "text": response.get("say", ""),
                 "meta": response.get("agent", {}), "tools": response.get("tools", []), "created_at": row[3]},
            ])
        return {"session_id": session_id, "messages": messages}

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
        timing = ""
        if slots.get("fixed_start"):
            timing = f", scheduled {slots['fixed_start'].replace('T', ' at ')}"
        elif slots.get("deadline"):
            timing = f", due {slots['deadline'].replace('T', ' at ')}"
        say = f"Create {slots['title']} for {slots['duration_minutes']} minutes{timing}?"
        return self._response(say, state="confirming", pending=action, listen_again=True, confirmation=True)

    def _continue(self, state: dict[str, Any], text: str) -> tuple[dict[str, Any], dict[str, Any]]:
        action = state["pending_action"]
        lower = text.lower().strip(" .!?")
        if any(value == lower or value in lower for value in NO):
            state.pop("pending_action", None)
            return state, self._response("Cancelled. I did not change anything.", commands=[{"type": "close_modal"}])
        if action["status"] == "confirming":
            if not any(value == lower or value in lower for value in YES):
                # Corrections should update the preview rather than trapping the user
                # behind a yes/no gate.
                if action["intent"] == "task.create" and re.search(r"\b(actually|change|make it|instead|at|tomorrow|today|minutes?|hours?)\b", lower):
                    updates = _task_slots(text)
                    action["slots"].update({key: value for key, value in updates.items() if value is not None})
                    action["status"] = "collecting"
                    return state, self._ask_task(action)
                return state, self._response("I’m holding the preview. Say yes to create it, tell me what to change, or say cancel.", state="confirming", pending=action, listen_again=True, confirmation=True)
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
            parsed = _task_slots(text)
            if not slots.get("title"):
                candidate = parsed.get("title") or _clean(text)[:160]
                if re.fullmatch(r"(?:tomorrow|today|at|for|from|\d|am|pm|minutes?|hours?|hrs?|\s|:|-)+", candidate, re.I):
                    candidate = None
                slots["title"] = candidate
            for key in ("duration_minutes", "deadline", "fixed_start", "flexibility"):
                if parsed.get(key) is not None:
                    slots[key] = parsed[key]
            if slots.get("fixed_start"):
                slots["flexibility"] = "fixed"
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
        try:
            schedule = self.registry.execute("get_day_schedule")
            schedule_facts = {
                "scheduled_blocks": len(schedule.get("blocks", [])),
                "free_buffer_minutes": schedule.get("metrics", {}).get("free_buffer_minutes"),
                "overrun_minutes": schedule.get("metrics", {}).get("overrun_minutes"),
            }
        except Exception:
            schedule_facts = {}
        decision = self.planner.decide(
            text,
            state=state,
            context=self.harness.context(
                state=state,
                current_view=payload.get("current_view"),
                tool_catalog=self.registry.catalog(),
                recent_turns=self._recent_turns(session_id),
                schedule_facts=schedule_facts,
            ),
        )
        intent, slots = decision.intent, decision.slots
        if intent == "repeat":
            with self.db() as conn:
                row = conn.execute("SELECT last_response_json FROM assistant_sessions WHERE id=?", (session_id,)).fetchone()
            return json.loads(row[0]) if row else self._response("There is nothing to repeat yet.")
        pending = state.get("pending_action")
        same_pending_intent = pending and {
            "task.create": "create_task", "project.create": "create_project", "task.complete": "complete_task",
        }.get(pending.get("intent")) == intent
        explicit_confirmation = pending and pending.get("status") == "confirming" and any(
            value == text.lower().strip(" .!?") or value in text.lower() for value in YES
        )
        if explicit_confirmation or same_pending_intent:
            state, result = self._continue(state, text)
        elif intent == "resume":
            action = self.harness.resume(state)
            if not action:
                result = self._response("There is no unfinished request to resume.")
            elif action["intent"] == "task.create":
                result = self._ask_task(action)
            else:
                result = self._response("I resumed the unfinished request. What would you like to add?", state="asking", pending=action, listen_again=True)
        elif intent == "help":
            result = self._response("I can navigate Plan B, create tasks and projects, complete tasks, explain your day and risks, and build recovery options. You can also say stop, cancel, repeat, or go back.", commands=[{"type": "show_help"}])
        elif intent == "back":
            result = self._response("Going back.", commands=[{"type": "back"}])
        elif state.get("pending_action") and intent not in {
            "navigate", "create_task", "create_project", "complete_task",
            "recover_schedule", "get_risks", "get_schedule", "assess_feasibility",
        }:
            state, result = self._continue(state, text)
        elif intent == "cancel":
            result = self._response("There is no pending action to cancel.")
        elif intent == "navigate":
            self.harness.suspend(state)
            route = slots.get("target")
            result = self._response((f"Opening {route.replace('_', ' ')}." if route else "I could not find that page.") + self.harness.draft_note(state), commands=[{"type": "navigate", "target": route}] if route else [])
        elif intent == "create_task":
            self.harness.suspend(state)
            parsed_slots = _task_slots(text)
            parsed_slots.update({key: value for key, value in slots.items() if value is not None})
            action = {"intent": "task.create", "status": "collecting", "slots": {"title": slots.get("title"), "duration_minutes": slots.get("duration_minutes"), "deadline": slots.get("deadline"), "description": slots.get("description", ""), "priority": slots.get("priority", "medium"), "flexibility": slots.get("flexibility", "flexible"), "splittable": slots.get("splittable", True), "tags": slots.get("tags", []), "project_id": slots.get("project_id"), "earliest_start": slots.get("earliest_start"), "fixed_start": slots.get("fixed_start")}}
            for key, value in parsed_slots.items():
                if value is not None:
                    action["slots"][key] = value
            state["pending_action"] = action
            result = self._ask_task(action)
        elif intent == "create_project":
            self.harness.suspend(state)
            name = slots.get("name")
            action = {"intent": "project.create", "status": "confirming" if name else "collecting", "slots": {"name": name, "description": "", "color": "#657c9a", "target_date": None}}
            state["pending_action"] = action
            result = self._response(f"Create a project called {name}?" if name else "What should I call the project?", state=action["status"] if name else "asking", pending=action, listen_again=True, confirmation=bool(name))
        elif intent == "complete_task":
            self.harness.suspend(state)
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
            self.harness.suspend(state)
            minutes = int(slots.get("disruption_minutes") or 60)
            recovery = self.registry.execute("generate_recovery_options", {"disruption_minutes": minutes, "reason": slots.get("reason") or text})
            result = self._response(f"I built and validated recovery options for the {minutes}-minute disruption. Nothing has changed until you approve one.", commands=[{"type": "navigate", "target": "recovery"}], tools=[{"tool": "find_affected_tasks", "status": "complete"}, {"tool": "generate_recovery_options", "status": "complete"}, {"tool": "validate_schedule", "status": "complete"}], recovery=recovery)
        elif intent == "get_risks":
            self.harness.suspend(state)
            risk_result = self.registry.execute("check_deadline_risks")
            risks = risk_result.get("risks", []) if isinstance(risk_result, dict) else risk_result
            if risks:
                first = risks[0]
                task_name = first.get("task")
                say = f"{task_name + ': ' if task_name else ''}{first['reason']}"
            else:
                say = "Your current plan has no calculated deadline risk."
            say += self.harness.draft_note(state)
            result = self._response(say, tools=[{"tool": "check_deadline_risks", "status": "complete"}])
        elif intent == "get_schedule":
            self.harness.suspend(state)
            day = self.registry.execute("get_day_schedule")
            result = self._response(f"You have {len(day['blocks'])} scheduled blocks and {day['metrics']['free_buffer_minutes']} minutes of free buffer." + self.harness.draft_note(state), commands=[{"type": "navigate", "target": "dashboard"}], tools=[{"tool": "get_day_schedule", "status": "complete"}])
        elif intent == "assess_feasibility":
            self.harness.suspend(state)
            day = self.registry.execute("get_day_schedule")
            risk_result = self.registry.execute("check_deadline_risks")
            risks = risk_result.get("risks", []) if isinstance(risk_result, dict) else risk_result
            free = int(day.get("metrics", {}).get("free_buffer_minutes") or 0)
            overrun = int(day.get("metrics", {}).get("overrun_minutes") or 0)
            if overrun:
                say = f"Not within the current day: the plan overruns capacity by {overrun} minutes"
            elif risks:
                say = f"It fits by capacity with {free} minutes free, but {len(risks)} deadline risk{'s' if len(risks) != 1 else ''} remain"
            else:
                say = f"Yes. The current plan fits with {free} minutes of free buffer and no calculated deadline risks"
            result = self._response(say + "." + self.harness.draft_note(state), tools=[{"tool": "get_day_schedule", "status": "complete"}, {"tool": "check_deadline_risks", "status": "complete"}])
        else:
            # The planner is also the conversational agent and must provide the reply
            # in its structured decision. Avoid a second LLM call on fallback/timeouts.
            reply = decision.response if decision.source == "model" else None
            result = self._response(reply or "I can control Plan B tasks, projects, calendar, recovery, patterns, and settings. Try saying: create a task, or open calendar.")
        self.harness.record(state, intent=intent, utterance=text, slots=slots, current_view=payload.get("current_view"))
        result["agent"] = {"role": "planner", "intent": intent, "confidence": decision.confidence, "source": decision.source, "max_steps": 6}
        self._save(session_id, state, text, result, idempotency_key)
        return result
