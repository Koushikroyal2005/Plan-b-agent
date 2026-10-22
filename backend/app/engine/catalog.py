"""Every product action the assistant can take, described once and executed deterministically."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field

from .capabilities import Capability, CapabilityRegistry, ExecContext, Outcome
from .errors import NeedsInfo, NotFound, Refused
from .language import datetime_reference, duration_minutes, normalize

PAGES = {
    "dashboard": "Today",
    "calendar": "Calendar",
    "tasks": "Tasks",
    "assistant": "Assistant",
    "recovery": "Recovery",
    "patterns": "Patterns",
    "mcp": "MCP tools",
    "settings": "Settings",
}
TASK_FIELDS = ("title", "duration_minutes", "deadline", "priority", "earliest_start", "fixed_start", "project_id", "status")


def _clock(iso: str | None) -> str:
    if not iso:
        return ""
    moment = datetime.fromisoformat(iso[:16])
    hour = moment.hour % 12 or 12
    return f"{hour}:{moment.minute:02d} {'AM' if moment.hour < 12 else 'PM'}"


def _when(iso: str | None, today: date) -> str:
    if not iso:
        return ""
    moment = datetime.fromisoformat(iso[:16])
    if moment.date() == today:
        prefix = "today"
    elif moment.date() == today + timedelta(days=1):
        prefix = "tomorrow"
    else:
        prefix = moment.strftime("%a %d %b")
    return f"{prefix} at {_clock(iso)}"


def _task_snapshot(task: dict[str, Any]) -> dict[str, Any]:
    return {key: task.get(key) for key in TASK_FIELDS} | {"id": task["id"]}


def _step(label: str, detail: str = "", status: str = "done") -> dict[str, Any]:
    return {"label": label, "detail": detail, "status": status}


# ---------- argument schemas ----------

class NoArgs(BaseModel):
    pass


class TaskRef(BaseModel):
    task: str = Field(default="", description="Task title, 'it' for the last task discussed, or id:<uuid>")


class SearchArgs(BaseModel):
    query: str | None = None
    status: Literal["open", "done", "archived", "all"] = "open"


class CreateTaskArgs(BaseModel):
    title: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=720)
    deadline: str | None = Field(default=None, description="ISO local datetime YYYY-MM-DDTHH:MM")
    fixed_start: str | None = Field(default=None, description="ISO local datetime when the task is booked at a set time")
    priority: Literal["low", "medium", "high"] = "medium"
    project: str | None = None
    description: str = ""


class TaskChanges(BaseModel):
    title: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=720)
    deadline: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    earliest_start: str | None = None
    project: str | None = None


class UpdateTaskArgs(TaskRef):
    changes: TaskChanges = Field(default_factory=TaskChanges)


class CreateProjectArgs(BaseModel):
    name: str | None = None
    description: str = ""
    target_date: str | None = None


class ProjectChanges(BaseModel):
    name: str | None = None
    target_date: str | None = None
    status: Literal["active", "completed", "archived"] | None = None


class UpdateProjectArgs(BaseModel):
    project: str = ""
    changes: ProjectChanges = Field(default_factory=ProjectChanges)


class DayArgs(BaseModel):
    day: str = Field(default="today", description="today, tomorrow or YYYY-MM-DD")


class SlotArgs(BaseModel):
    minutes: int | None = Field(default=None, ge=5, le=720)
    day: str = "today"


class AssessArgs(BaseModel):
    target: str | None = None


class ShortenRef(BaseModel):
    task: str
    minutes: int | None = Field(default=None, ge=5, le=720)


class RecoverArgs(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=720)
    reason: str = "Unexpected disruption"
    target: str | None = Field(default=None, description="Task whose deadline must be protected")
    protect: list[str] = Field(default_factory=list)
    shorten: list[ShortenRef] = Field(default_factory=list)
    defer: list[str] = Field(default_factory=list)


class ApplyArgs(BaseModel):
    option: int | None = Field(default=None, description="0-based index of the presented options")


class InsightArgs(BaseModel):
    days: int = Field(default=7, ge=1, le=90)


class PreferenceChanges(BaseModel):
    day_start: str | None = None
    day_end: str | None = None
    break_minutes: int | None = Field(default=None, ge=0, le=120)
    default_buffer_minutes: int | None = Field(default=None, ge=0, le=180)
    planning_style: Literal["realistic", "balanced", "ambitious"] | None = None
    voice_output: bool | None = None


class PreferenceArgs(BaseModel):
    changes: PreferenceChanges = Field(default_factory=PreferenceChanges)


class UndoArgs(BaseModel):
    action_id: str | None = None


class HistoryArgs(BaseModel):
    limit: int = Field(default=5, ge=1, le=20)


class NavigateArgs(BaseModel):
    target: str


# ---------- tasks ----------

def search_tasks(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    status = args.get("status") or "open"
    tasks = ctx.services.tasks(include_archived=True)
    if status != "all":
        tasks = [t for t in tasks if t["status"] == status]
    query = (args.get("query") or "").strip()
    if query:
        from .resolver import score
        tasks = sorted((t for t in tasks if score(query, t["title"]) >= 0.3 or query.lower() in " ".join(t.get("tags") or [])),
                       key=lambda t: -score(query, t["title"]))
    names = [t["title"] for t in tasks[:5]]
    label = f"{status} tasks" if status != "all" else "tasks"
    if not tasks:
        say = f"I found no {label}{f' matching {query}' if query else ''}."
    else:
        say = f"I found {len(tasks)} {label}{f' matching {query}' if query else ''}: {', '.join(names)}."
    focus = {"task": tasks[0]["id"]} if len(tasks) == 1 else {}
    return Outcome(say=say, data=tasks, focus=focus, ui=[{"type": "navigate", "target": "tasks"}])


def prepare_create_task(args: dict[str, Any], ctx: ExecContext):
    if not args.get("title"):
        raise NeedsInfo("What task should I create?", "title", "text")
    if not args.get("duration_minutes"):
        raise NeedsInfo(f"How long should {args['title']} take?", "duration_minutes", "duration")
    project_id = None
    if args.get("project"):
        project_id = ctx.resolver.project(args["project"])["id"]
    normalized = {
        "title": args["title"].strip()[:160],
        "duration_minutes": int(args["duration_minutes"]),
        "deadline": args.get("deadline"),
        "fixed_start": args.get("fixed_start"),
        "priority": args.get("priority") or "medium",
        "description": args.get("description") or "",
        "project": args.get("project"),
        "project_id": project_id,
    }
    when = f", booked {_when(normalized['fixed_start'], ctx.today)}" if normalized["fixed_start"] else ""
    due = f", due {_when(normalized['deadline'], ctx.today)}" if normalized["deadline"] else ""
    return normalized, f"Create {normalized['title']} for {normalized['duration_minutes']} minutes{when}{due}?"


def amend_create_task(args: dict[str, Any], text: str, ctx: ExecContext):
    changed = dict(args)
    minutes = duration_minutes(text)
    deadline = datetime_reference(text, ctx.today)
    lower = normalize(text)
    if minutes:
        changed["duration_minutes"] = minutes
    if deadline and re.search(r"\b(due|by|before)\b", lower):
        changed["deadline"] = deadline
    elif deadline and re.search(r"\b(at|from)\s+\d", lower):
        changed["fixed_start"] = deadline
    elif deadline and re.search(r"\b(tomorrow|today|tonight)\b", lower):
        changed["deadline"] = deadline
    for level in ("high", "low", "medium"):
        if f"{level} priority" in lower:
            changed["priority"] = level
    return changed if changed != args else None


def create_task(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    values = {k: v for k, v in args.items() if k != "project"}
    fixed = bool(values.get("fixed_start"))
    task = ctx.services.create_task({**values, "flexibility": "fixed" if fixed else "flexible",
                                     "splittable": not fixed, "tags": []})
    ctx.invalidate()
    verified = any(t["id"] == task["id"] and t["status"] == "open" for t in ctx.services.tasks())
    return Outcome(
        say=f"Created {task['title']}.",
        data=task,
        summary=f"Created task {task['title']}",
        before=None,
        after=_task_snapshot(task),
        inverse={"op": "task.patch", "task_id": task["id"], "fields": {"status": "archived"}},
        verified=verified,
        focus={"task": task["id"]},
        ui=[{"type": "navigate", "target": "tasks"}, {"type": "highlight", "target": "task", "id": task["id"]}, {"type": "close_modal"}],
    )


def _resolve_project_change(changes: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
    result = {k: v for k, v in changes.items() if v is not None and k != "project"}
    if changes.get("project"):
        result["project_id"] = ctx.resolver.project(changes["project"])["id"]
    return result


def describe_changes(task: dict[str, Any], fields: dict[str, Any], today: date) -> str:
    parts = []
    for key, value in fields.items():
        if key == "duration_minutes":
            parts.append(f"{task['duration_minutes']} to {value} minutes")
        elif key == "deadline":
            parts.append(f"due {_when(value, today)}")
        elif key == "earliest_start":
            parts.append(f"start {_when(value, today)}")
        elif key == "title":
            parts.append(f"rename to {value}")
        elif key == "priority":
            parts.append(f"{value} priority")
        elif key == "project_id":
            parts.append("move to another project")
        elif key == "status":
            parts.append(f"mark {value}")
    return ", ".join(parts)


def prepare_update_task(args: dict[str, Any], ctx: ExecContext):
    task = ctx.resolver.task(args.get("task", ""))
    fields = _resolve_project_change(args.get("changes") or {}, ctx)
    fields = {k: v for k, v in fields.items() if task.get(k) != v}
    if not fields:
        raise NeedsInfo(f"What should I change about {task['title']}?", "changes", "task_changes")
    return {"task_id": task["id"], "fields": fields}, f"Update {task['title']}: {describe_changes(task, fields, ctx.today)}?"


def _patch(task_id: str, fields: dict[str, Any], ctx: ExecContext, summary: str, say: str) -> Outcome:
    before_task = next(t for t in ctx.services.tasks(include_archived=True) if t["id"] == task_id)
    before = {key: before_task.get(key) for key in fields}
    after_task = ctx.services.patch_task(task_id, fields)
    ctx.invalidate()
    verified = all(after_task.get(key) == value for key, value in fields.items())
    return Outcome(
        say=say,
        data=after_task,
        summary=summary,
        before=before,
        after={key: after_task.get(key) for key in fields},
        inverse={"op": "task.patch", "task_id": task_id, "fields": before},
        verified=verified,
        focus={"task": task_id},
        ui=[{"type": "highlight", "target": "task", "id": task_id}],
    )


def update_task(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    task = next(t for t in ctx.services.tasks(include_archived=True) if t["id"] == args["task_id"])
    detail = describe_changes(task, args["fields"], ctx.today)
    return _patch(args["task_id"], args["fields"], ctx, f"Updated {task['title']}: {detail}", f"Updated {task['title']}: {detail}.")


def prepare_status(target_status: str, from_statuses: set[str], verb: str):
    def prepare(args: dict[str, Any], ctx: ExecContext):
        task = ctx.resolver.task(args.get("task", ""), statuses=from_statuses)
        return {"task_id": task["id"], "title": task["title"], "status": target_status}, f"{verb} {task['title']}?"
    return prepare


def status_executor(past: str):
    def execute(args: dict[str, Any], ctx: ExecContext) -> Outcome:
        return _patch(args["task_id"], {"status": args["status"]}, ctx, f"{past} {args['title']}", f"{past} {args['title']}.")
    return execute


# ---------- projects ----------

def prepare_create_project(args: dict[str, Any], ctx: ExecContext):
    if not args.get("name"):
        raise NeedsInfo("What should I call the project?", "name", "text")
    name = args["name"].strip()[:100]
    return {"name": name, "description": args.get("description") or "", "color": "#657c9a",
            "target_date": args.get("target_date")}, f"Create a project called {name}?"


def create_project(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    project = ctx.services.create_project(args)
    ctx.invalidate()
    return Outcome(
        say=f"Created the {project['name']} project.",
        data=project,
        summary=f"Created project {project['name']}",
        after={"id": project["id"], "name": project["name"]},
        inverse={"op": "project.patch", "project_id": project["id"], "fields": {"status": "archived"}},
        verified=any(p["id"] == project["id"] for p in ctx.services.projects()),
        focus={"project": project["id"]},
        ui=[{"type": "navigate", "target": "tasks"}, {"type": "highlight", "target": "project", "id": project["id"]}],
    )


def prepare_update_project(args: dict[str, Any], ctx: ExecContext):
    project = ctx.resolver.project(args.get("project", ""))
    fields = {k: v for k, v in (args.get("changes") or {}).items() if v is not None and project.get(k) != v}
    if not fields:
        raise NeedsInfo(f"What should I change about {project['name']}?", "changes", "text")
    words = ", ".join(f"{k.replace('_', ' ')} to {v}" for k, v in fields.items())
    return {"project_id": project["id"], "name": project["name"], "fields": fields}, f"Change {project['name']}: {words}?"


def update_project(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    project = next(p for p in ctx.services.projects(include_archived=True) if p["id"] == args["project_id"])
    before = {k: project.get(k) for k in args["fields"]}
    after = ctx.services.patch_project(args["project_id"], args["fields"])
    ctx.invalidate()
    return Outcome(
        say=f"Updated {args['name']}.",
        data=after,
        summary=f"Updated project {args['name']}",
        before=before,
        after={k: after.get(k) for k in args["fields"]},
        inverse={"op": "project.patch", "project_id": args["project_id"], "fields": before},
        verified=all(after.get(k) == v for k, v in args["fields"].items()),
        focus={"project": args["project_id"]},
    )


# ---------- calendar & schedule ----------

def _day_arg(value: str | None, today: date) -> date:
    if not value or value == "today":
        return today
    if value == "tomorrow":
        return today + timedelta(days=1)
    try:
        return date.fromisoformat(value)
    except ValueError:
        return today


def inspect_calendar(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    day = _day_arg(args.get("day"), ctx.today)
    schedule = ctx.services.day(None if day == ctx.today else day)
    work = [b for b in schedule["blocks"] if b.get("task_id")]
    label = "today" if day == ctx.today else ("tomorrow" if day == ctx.today + timedelta(days=1) else day.isoformat())
    if not work:
        say = f"Nothing is scheduled {label}."
    else:
        first = work[0]
        say = (f"{label.capitalize()} has {len(work)} blocks, starting with {first['title']} at {first['start']}. "
               f"{schedule['metrics']['free_buffer_minutes']} minutes stay free.")
        if schedule["risks"]:
            say += f" One concern: {describe_risk(schedule['risks'][0])}"
    return Outcome(say=say, data=schedule, ui=[{"type": "navigate", "target": "dashboard" if day == ctx.today else "calendar"}],
                   evidence=[f"{b['start']}–{b['end']} {b['title']}" for b in work[:6]])


def find_slot(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    minutes = args.get("minutes")
    if not minutes:
        raise NeedsInfo("How many minutes do you need?", "minutes", "duration")
    day = _day_arg(args.get("day"), ctx.today)
    schedule = ctx.services.day(None if day == ctx.today else day)
    prefs = ctx.services.preferences()
    buffer = schedule["metrics"].get("applied_buffer_minutes", 0)
    start = datetime.fromisoformat(f"{day.isoformat()}T{prefs['day_start']}")
    end = datetime.fromisoformat(f"{day.isoformat()}T{prefs['day_end']}")
    now = ctx.services.now()
    cursor = max(start, now) if now and now.date() == day else start
    for block in sorted(schedule["blocks"], key=lambda b: b["start_iso"]):
        block_start = datetime.fromisoformat(block["start_iso"])
        if (block_start - cursor).total_seconds() / 60 >= minutes + buffer:
            break
        cursor = max(cursor, datetime.fromisoformat(block["end_iso"]) + timedelta(minutes=buffer))
    if cursor + timedelta(minutes=minutes) > end:
        return Outcome(say=f"There is no free {minutes}-minute gap left on that day inside your working hours.", data=None)
    iso = cursor.isoformat(timespec="minutes")
    return Outcome(say=f"You have a free {minutes}-minute gap {_when(iso, ctx.today)}.", data={"start": iso, "minutes": minutes},
                   ui=[{"type": "navigate", "target": "calendar"}])


def describe_risk(risk: dict[str, Any]) -> str:
    slack = risk["slack_minutes"]
    if not risk.get("task_id"):
        return risk["reason"]
    if slack < 0:
        return f"{risk['task']} would finish {-slack} minutes after its deadline."
    return f"{risk['task']} is tight: only {slack} minutes of slack before its deadline."


def assess_schedule(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    schedule = ctx.services.day()
    risks = schedule["risks"]
    target = None
    if args.get("target"):
        target = ctx.resolver.task(args["target"])
        risks = [r for r in risks if r["task_id"] == target["id"]] or []
    if target and not risks:
        block = next((b for b in schedule["blocks"] if b.get("task_id") == target["id"]), None)
        say = (f"{target['title']} is on track: it's planned {block['start']}–{block['end']}."
               if block else f"{target['title']} isn't on today's plan.")
    elif risks:
        say = describe_risk(risks[0])
        if len(risks) > 1:
            say += f" {len(risks) - 1} more item{'s' if len(risks) > 2 else ''} also need attention."
    else:
        say = "You're on track. Nothing on today's plan is at risk."
    return Outcome(say=say, data={"status": schedule["status"], "risks": risks},
                   evidence=[describe_risk(r) for r in risks[:4]], focus={"task": target["id"]} if target else {})


def recover_schedule(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    if not args.get("minutes"):
        raise NeedsInfo("How many minutes did you lose?", "minutes", "duration")
    resolver = ctx.resolver
    timeline = [_step("Reading today's calendar")]
    target = resolver.task(args["target"]) if args.get("target") else None
    protect = [resolver.task(ref) for ref in args.get("protect") or []]
    shorten = {}
    for item in args.get("shorten") or []:
        task = resolver.task(item["task"])
        shorten[task["id"]] = item.get("minutes") or 0
    defer = [resolver.task(ref)["id"] for ref in args.get("defer") or []]
    recovery = ctx.services.recover(
        minutes=int(args["minutes"]), reason=args.get("reason") or "Unexpected disruption",
        target_task_id=target["id"] if target else None,
        protect_ids=[t["id"] for t in protect], shorten=shorten, defer_ids=defer,
    )
    constraints = recovery["constraints"]
    evidence = recovery["evidence"]
    target_info = constraints.get("target")
    timeline.append(_step("Finding work affected by the delay", f"{args['minutes']} minutes lost"))
    if target_info:
        deadline = f" by {_clock(target_info['deadline'])}" if target_info.get("deadline") else ""
        timeline.append(_step(f"Protecting {target_info['title']}{deadline}"))
    for item in protect:
        timeline.append(_step(f"Keeping {item['title']} in place", "you asked"))
    timeline.append(_step("Checking options against deadlines and fixed events", f"{evidence['options_checked']} options"))
    safe = [o for o in recovery["options"] if o["feasible"]]
    timeline.append(_step(f"{len(safe)} safe option{'s' if len(safe) != 1 else ''} found", status="done" if safe else "failed"))
    for option in safe:
        block = next((b for b in option["revised_blocks"] if target_info and b.get("task_id") == target_info["id"]), None)
        option["target_end"] = block["end"] if block else None
        option["target_slack"] = (
            int((datetime.fromisoformat(target_info["deadline"][:16]) - datetime.fromisoformat(block["end_iso"][:16])).total_seconds() / 60)
            if block and target_info and target_info.get("deadline") else None
        )

    ctx.memory["recovery"] = {
        "plan_id": recovery["plan_id"],
        "minutes": int(args["minutes"]),
        "reason": args.get("reason"),
        "target": f"id:{target['id']}" if target else (f"id:{target_info['id']}" if target_info else None),
        "protect": [f"id:{t['id']}" for t in protect],
        "shorten": [{"task": f"id:{k}", "minutes": v or None} for k, v in shorten.items()],
        "defer": [f"id:{i}" for i in defer],
        "options": [{"id": o["id"], "title": o["title"], "feasible": o["feasible"], "tradeoff": o["tradeoff"],
                     "target_end": o.get("target_end"), "target_slack": o.get("target_slack")} for o in safe],
        "evidence": evidence,
        "constraints": constraints,
        "applied": False,
    }
    if target_info:
        ctx.memory.setdefault("focus", {})["task"] = target_info["id"]

    lead = ""
    critical = evidence["critical_risks"]
    if critical:
        first = critical[0]
        lead = f"With that delay, {first['task']} would run {-first['slack_minutes']} minutes past its deadline. "
    elif not recovery["options"] or recovery["options"][0]["strategy"] == "absorb":
        lead = "Good news: everything still fits after that delay. "
    if not safe:
        say = lead + "I couldn't find a change that keeps every deadline. You could extend a deadline or tell me what can move."
    else:
        listed = " ".join(f"Option {i + 1}: {o['title']}." for i, o in enumerate(safe[:2]))
        say = lead + listed + (" Say apply it, or tell me what to change." if len(safe) else "")
    return Outcome(
        say=say,
        data=recovery,
        recovery=recovery,
        timeline=timeline,
        evidence=[o["tradeoff"] for o in safe[:2]],
        ui=[{"type": "navigate", "target": "recovery"}],
    )


def _selected_option(args: dict[str, Any], ctx: ExecContext) -> dict[str, Any]:
    recovery = ctx.memory.get("recovery")
    if not recovery or recovery.get("applied"):
        raise Refused("There's no recovery plan waiting to apply. Tell me what changed first.")
    options = recovery["options"]
    if not options:
        raise Refused("None of the options keep every deadline, so I won't apply one.")
    index = args.get("option")
    if index is None:
        return options[0]
    if index == -1:
        index = len(options) - 1
    if index >= len(options):
        raise Refused(f"There are only {len(options)} safe options.")
    return options[index]


def prepare_apply(args: dict[str, Any], ctx: ExecContext):
    option = _selected_option(args, ctx)
    return {"proposal_id": option["id"], "title": option["title"]}, f"Apply \"{option['title']}\"?"


def _applied_phrase(change: dict[str, Any]) -> str:
    if change["kind"] == "shorten":
        return f"{change['title']} is now {change['values']['duration_minutes']} minutes"
    if change["kind"] == "defer":
        return f"{change['title']} moved to tomorrow"
    return change["summary"]


def _reverted_phrase(change: dict[str, Any]) -> str:
    if change["kind"] == "shorten":
        return f"{change['title']} is back to {change['before']['duration_minutes']} minutes"
    if change["kind"] == "defer":
        return f"{change['title']} is back on today"
    return f"{change['title']} is back as it was"


def apply_schedule(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    result = ctx.services.apply_proposal(args["proposal_id"])
    ctx.invalidate()
    day = ctx.services.day()
    verified = day.get("schedule_source") == "approved_plan" and day.get("active_plan_id") == result["plan_id"]
    recovery = ctx.memory.get("recovery") or {}
    recovery["applied"] = True
    ctx.memory["recovery"] = recovery
    say = f"Done. {'. '.join(_applied_phrase(c) for c in result['changes']) or result['title']}."
    target = (recovery.get("constraints") or {}).get("target")
    if target:
        block = next((b for b in day["blocks"] if b.get("task_id") == target["id"]), None)
        if block:
            say += f" {target['title']} now ends at {block['end']}."
    say += " Say undo to put everything back."
    return Outcome(
        say=say,
        data=result,
        summary=f"Applied recovery: {result['title']}",
        before={"blocks": result["before"].get("blocks", []), "tasks": result["task_restores"]},
        after={"blocks": day["blocks"], "changes": result["changes"]},
        inverse={"op": "plan.revert", "plan_id": result["plan_id"], "task_restores": result["task_restores"]},
        verified=verified,
        timeline=[_step("Applying the approved option"), _step("Verifying the new calendar", status="done" if verified else "failed")],
        ui=[{"type": "navigate", "target": "calendar"}],
    )


def explain_plan(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    recovery = ctx.memory.get("recovery")
    if not recovery:
        return Outcome(say="I haven't built a recovery plan in this conversation yet, so there's nothing to explain.")
    evidence = recovery["evidence"]
    constraints = recovery.get("constraints") or {}
    parts = []
    target = constraints.get("target")
    if evidence["critical_risks"]:
        risk = evidence["critical_risks"][0]
        parts.append(f"After the {recovery['minutes']}-minute delay, {risk['task']} would have ended {-risk['slack_minutes']} minutes late.")
    if target:
        parts.append(f"I treated the {target['title']} deadline as fixed.")
    kept = [p["title"] for p in constraints.get("protected", []) if not target or p["id"] != target["id"]]
    if kept:
        parts.append(f"I kept {', '.join(kept)} in place because you asked.")
    parts.append(f"I checked {evidence['options_checked']} options with the scheduler; {evidence['feasible_options']} kept every deadline and fixed event.")
    best = (recovery.get("options") or [None])[0]
    if best and best.get("target_end") and target:
        slack = best.get("target_slack")
        margin = f", {slack} minutes before its deadline" if slack is not None else ""
        parts.append(f"With \"{best['title']}\", {target['title']} ends at {best['target_end']}{margin}. Trade-off: {best['tradeoff']}")
    return Outcome(say=" ".join(parts), evidence=parts)


def explain_insights(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    data = ctx.services.patterns(args.get("days") or 7)
    summary = data.get("summary") or {}
    pieces = [data.get("history_note") or ""]
    if summary:
        pieces.insert(0, " ".join(f"{k.replace('_', ' ')}: {v}." for k, v in list(summary.items())[:3]))
    say = " ".join(p for p in pieces if p).strip() or "There isn't enough completed work yet to show patterns."
    return Outcome(say=say, data=data, ui=[{"type": "navigate", "target": "patterns"}])


# ---------- preferences ----------

def prepare_preferences(args: dict[str, Any], ctx: ExecContext):
    current = ctx.services.preferences()
    fields = {k: v for k, v in (args.get("changes") or {}).items() if v is not None and current.get(k) != v}
    if not fields:
        raise NeedsInfo("Which setting should I change?", "changes", "text")
    words = ", ".join(f"{k.replace('_', ' ')} to {v}" for k, v in fields.items())
    return {"fields": fields}, f"Change {words}?"


def update_preferences(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    current = ctx.services.preferences()
    before = {k: current.get(k) for k in args["fields"]}
    saved = ctx.services.save_preferences({**current, **args["fields"]})
    words = ", ".join(f"{k.replace('_', ' ')} is now {v}" for k, v in args["fields"].items())
    return Outcome(
        say=f"Saved. Your {words}.",
        data=saved,
        summary=f"Updated settings: {words}",
        before=before,
        after={k: saved.get(k) for k in args["fields"]},
        inverse={"op": "preferences.patch", "fields": before},
        verified=all(saved.get(k) == v for k, v in args["fields"].items()),
    )


# ---------- actions ----------

def run_inverse(inverse: dict[str, Any], services: Any) -> None:
    op = inverse["op"]
    if op == "task.patch":
        services.patch_task(inverse["task_id"], inverse["fields"])
    elif op == "project.patch":
        services.patch_project(inverse["project_id"], inverse["fields"])
    elif op == "preferences.patch":
        services.save_preferences({**services.preferences(), **inverse["fields"]})
    elif op == "plan.revert":
        services.revert_plan(inverse["plan_id"], inverse["task_restores"])
    else:
        raise Refused(f"I don't know how to reverse {op}.")


def undo_action(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    action = ctx.ledger.get(args["action_id"]) if args.get("action_id") else ctx.ledger.latest_undoable()
    if not action or not action["reversible"]:
        raise Refused("There's nothing I can undo right now.")
    run_inverse(action["inverse"], ctx.services)
    ctx.ledger.mark_undone(action["id"])
    ctx.invalidate()
    if action["capability"] == "schedule.apply":
        recovery = ctx.memory.get("recovery")
        if recovery:
            recovery["applied"] = True
    if action["inverse"]["op"] == "plan.revert":
        changes = (action.get("after") or {}).get("changes") or []
        details = ". ".join(_reverted_phrase(c) for c in changes)
        say = "Undone. Your schedule is back to how it was" + (f". {details}." if details else ".")
    else:
        summary = action["summary"][0].lower() + action["summary"][1:]
        say = f"Undone. I reversed: {summary}."
    return Outcome(say=say, data=action, summary=f"Undid: {action['summary']}", verified=True,
                   ui=[{"type": "navigate", "target": "calendar"}] if action["inverse"]["op"] == "plan.revert" else [])


def action_history(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    actions = ctx.ledger.recent(args.get("limit") or 5)
    if not actions:
        return Outcome(say="I haven't changed anything yet.")
    lines = [f"{a['summary']}{' (undone)' if a['status'] == 'undone' else ''}" for a in actions]
    return Outcome(say="Most recent first: " + "; ".join(lines) + ".", data=actions, evidence=lines)


def navigate(args: dict[str, Any], ctx: ExecContext) -> Outcome:
    target = args["target"]
    if target not in PAGES:
        raise NotFound("I couldn't find that page.")
    return Outcome(say=f"Opening {PAGES[target]}.", ui=[{"type": "navigate", "target": target}])


def build_registry() -> CapabilityRegistry:
    return CapabilityRegistry([
        Capability("tasks.search", "Find tasks by name, tag or status", SearchArgs,
                   ["what tasks do I have", "find tasks about the pitch"], "read", "none", False, "Searching your tasks", search_tasks),
        Capability("tasks.create", "Create a task (not scheduled until the plan rebuilds)", CreateTaskArgs,
                   ["add a task to call the bank for 15 minutes", "remind me to send slides tomorrow at 10 am"],
                   "write", "required", True, "Creating the task", create_task, prepare_create_task, amend_create_task),
        Capability("tasks.update", "Change a task's title, duration, deadline, priority, start or project", UpdateTaskArgs,
                   ["make the report review 30 minutes", "move lecture notes to tomorrow", "rename it to pitch deck"],
                   "write", "required", True, "Updating the task", update_task, prepare_update_task, required_context=["task"]),
        Capability("tasks.complete", "Mark a task done", TaskRef, ["mark the report review done", "I finished it"],
                   "write", "none", True, "Marking the task done", status_executor("Marked done:"),
                   prepare_status("done", {"open"}, "Mark done:"), required_context=["task"]),
        Capability("tasks.archive", "Archive a task (Plan B never deletes)", TaskRef, ["delete the parcel task", "archive inbox cleanup"],
                   "write", "required", True, "Archiving the task", status_executor("Archived"),
                   prepare_status("archived", {"open", "done"}, "Archive"), required_context=["task"]),
        Capability("tasks.restore", "Bring an archived task back", TaskRef, ["restore the parcel task"],
                   "write", "none", True, "Restoring the task", status_executor("Restored"),
                   prepare_status("open", {"archived"}, "Restore"), required_context=["task"]),
        Capability("projects.create", "Create a project", CreateProjectArgs, ["create a project called hackathon"],
                   "write", "required", True, "Creating the project", create_project, prepare_create_project),
        Capability("projects.update", "Rename, re-date, complete or archive a project", UpdateProjectArgs,
                   ["rename project study sprint to exams", "archive the personal admin project"],
                   "write", "required", True, "Updating the project", update_project, prepare_update_project),
        Capability("calendar.inspect", "Read the schedule for a day", DayArgs, ["what's my day look like", "what's on tomorrow"],
                   "read", "none", False, "Reading the calendar", inspect_calendar),
        Capability("calendar.find_slot", "Find the next free gap of a given length", SlotArgs, ["when can I fit 45 minutes"],
                   "read", "none", False, "Looking for a free gap", find_slot),
        Capability("schedule.assess", "Check deadline and capacity risk", AssessArgs, ["what's at risk", "can I still finish the pitch"],
                   "read", "none", False, "Checking deadlines", assess_schedule),
        Capability("schedule.recover", "Build validated recovery options after a disruption, honouring protections and corrections",
                   RecoverArgs, ["my meeting ran 45 minutes late and I still need to finish the pitch before 6",
                                 "don't move lecture notes, shorten the report review instead"],
                   "read", "none", False, "Building recovery options", recover_schedule, required_context=["calendar"]),
        Capability("schedule.apply", "Apply one of the presented recovery options", ApplyArgs, ["apply it", "go with the second one"],
                   "write", "required", True, "Applying the plan", apply_schedule, prepare_apply, required_context=["recovery"]),
        Capability("schedule.explain", "Explain why the current recovery plan was suggested", NoArgs, ["why this plan?"],
                   "read", "none", False, "Explaining the plan", explain_plan, required_context=["recovery"]),
        Capability("insights.explain", "Summarise completion and focus patterns", InsightArgs, ["how have I been doing this week"],
                   "read", "none", False, "Reading your patterns", explain_insights),
        Capability("preferences.update", "Change planning preferences", PreferenceArgs,
                   ["set my buffer to 20 minutes", "end my day at 8 pm", "turn on voice replies"],
                   "write", "required", True, "Saving your settings", update_preferences, prepare_preferences),
        Capability("actions.undo", "Undo the most recent change", UndoArgs, ["undo that", "put it back"],
                   "write", "none", False, "Undoing the last change", undo_action),
        Capability("actions.history", "List recent changes Plan B made", HistoryArgs, ["what did you change"],
                   "read", "none", False, "Reading recent changes", action_history),
        Capability("app.navigate", "Open a page", NavigateArgs, ["open calendar", "go to settings"],
                   "ui", "none", False, "Opening the page", navigate),
    ])
