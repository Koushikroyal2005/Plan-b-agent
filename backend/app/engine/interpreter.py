"""Offline interpreter: maps an utterance to the same typed Plan the model planner produces.

Used when no model is configured, the model times out, or the circuit breaker is open.
Universal commands (confirm, cancel, undo, navigation) are always handled here first.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, time, timedelta
from typing import Any

from .catalog import PAGES
from .language import (
    clock_time, datetime_reference, day_reference, duration_minutes, normalize, ordinal, strip_filler, task_details,
)
from .plans import Plan, PlanStep

CONFIRM = {
    "yes", "yeah", "yep", "yup", "sure", "confirm", "confirmed", "do it", "go ahead", "ok", "okay",
    "okay do it", "yes please", "please do", "correct", "that's right", "sounds good", "create it",
    "haan", "ha", "theek hai", "yes do it", "go for it", "apply", "make it so",
}
CANCEL = {
    "no", "nope", "cancel", "cancel that", "stop", "never mind", "nevermind", "forget it", "don't",
    "do not", "leave it", "not now", "no thanks", "abort", "nahi", "skip it",
}
REPEAT = {"repeat", "repeat that", "say that again", "what did you say", "come again", "pardon"}
RESUME = {"continue", "resume", "go on", "carry on", "where were we", "back to that", "continue the draft"}
BACK = {"back", "go back", "previous page"}
HELP = {"help", "what can you do", "what can i say", "how do i use this", "commands"}

PAGE_WORDS = {
    "dashboard": ("today", "home", "dashboard", "my day page"),
    "calendar": ("calendar", "calender", "time grid", "week"),
    "tasks": ("tasks", "task list", "projects", "todo", "to do", "to-do"),
    "assistant": ("assistant", "chat"),
    "recovery": ("recovery", "options page"),
    "patterns": ("patterns", "analytics", "insights", "stats"),
    "mcp": ("mcp", "tools page"),
    "settings": ("settings", "preferences", "setup"),
}
DISRUPTION = re.compile(
    r"\b(late|overran|over ran|ran over|ran long|running behind|behind schedule|delayed|took longer|"
    r"overrun|lost (?:an? |\d+)|fix my day|rebuild my day|re-?plan|rescue my day|something came up|"
    r"got pulled into|stuck in|ran \d+ minutes|went over|\d+ (?:minutes?|mins?|hours?|hrs?) behind)\b"
)
APPLY = re.compile(
    r"^(?:(?:ok(?:ay)?|yes|great|perfect|cool)[, ]+)?(?:please )?(?:apply|go with|use|choose|pick|take|accept|approve|do)"
    r"\b(?:\s+(?:it|that|this|that one|this one|the plan|plan|option\s*\w+|the (?:first|second|third|last)(?: one| option)?|"
    r"(?:the )?(?:first|second|third|last)|one|two|three|[123]))?(?: one| option| plan)?(?: please)?$"
)


@dataclass
class InterpretContext:
    today: date
    memory: dict[str, Any]
    current_view: str | None = None


def universal(text: str) -> str | None:
    lower = normalize(text)
    if lower in CONFIRM:
        return "confirm"
    if lower in CANCEL:
        return "cancel"
    if lower in REPEAT:
        return "repeat"
    if lower in RESUME:
        return "resume"
    if lower in BACK:
        return "back"
    if lower in HELP:
        return "help"
    return None


def _plan(goal: str, *steps: PlanStep, ack: str | None = None, confidence: float = 0.85) -> Plan:
    return Plan(goal=goal, steps=list(steps), acknowledgement=ack, confidence=confidence, source="rules")


def _clauses(text: str) -> list[str]:
    parts = re.split(r"[.;!?]+|\bbut\b|\band then\b|, and\b|\binstead,", text)
    return [p.strip(" ,") for p in parts if p.strip(" ,")]


def _ref(phrase: str) -> str:
    return strip_filler(re.split(r"\b(?:to|by|for|until|because|so that|since)\b", phrase, maxsplit=1)[0]) or phrase


def corrections(text: str) -> dict[str, list[Any]]:
    """Find 'don't move X', 'keep X', 'shorten Y (to N)', 'move Z to tomorrow' clauses."""
    found: dict[str, list[Any]] = {"protect": [], "shorten": [], "defer": []}
    for clause in _clauses(normalize(text)):
        negated = re.search(r"\b(?:don'?t|do not|dont|never|no need to)\s+(?:move|touch|shift|defer|postpone|push|change|drop|cut|shorten)\s+(.+)", clause)
        keep = re.search(r"\b(?:keep|leave|protect)\s+(.+?)(?:\s+(?:where it is|as it is|as is|in place|alone|untouched|today|fixed))?$", clause)
        shorten = re.search(r"\b(?:shorten|trim|cut(?: down)?|reduce|compress|squeeze)\s+(.+?)(?:\s+(?:to|down to)\s+(.+))?$", clause)
        defer = re.search(r"\b(?:move|defer|postpone|push|shift|bump)\s+(.+?)\s+(?:to tomorrow|till tomorrow|tomorrow|to later|later|instead)", clause)
        if negated:
            found["protect"].append(_ref(negated.group(1)))
        elif shorten:
            minutes = duration_minutes(shorten.group(2)) if shorten.group(2) else None
            found["shorten"].append({"task": _ref(shorten.group(1)), "minutes": minutes})
        elif defer:
            found["defer"].append(_ref(defer.group(1)))
        elif keep and not re.search(r"\bkeep (?:going|it up)\b", clause):
            found["protect"].append(_ref(keep.group(1)))
    return found


def _target(text: str) -> str | None:
    match = re.search(
        r"\b(?:finish|complete|submit|ship|wrap up|get done with|deliver|do)\s+(?:the |my |our )?(.+?)(?:\s+(?:before|by|until|till|today|tonight|on time)\b|$)",
        normalize(text),
    )
    if not match:
        return None
    phrase = strip_filler(match.group(1))
    return phrase if phrase and phrase not in {"it", "everything", "all", "work", "this", "that"} else None


def _page(lower: str) -> str | None:
    for page, words in PAGE_WORDS.items():
        if any(re.search(rf"\b{re.escape(w)}\b", lower) for w in words):
            return page
    return None


def _preferences(lower: str) -> dict[str, Any]:
    changes: dict[str, Any] = {}
    numbers = re.findall(r"(\d+)\s*(?:minutes?|mins?|min)?", lower)
    if re.search(r"\bbuffers?\b", lower) and numbers:
        changes["default_buffer_minutes"] = int(numbers[0])
    if re.search(r"\bno breaks\b|\bturn off breaks\b|\bdisable breaks\b", lower):
        changes["break_minutes"] = 0
    elif re.search(r"\bbreaks?\b", lower) and numbers:
        changes["break_minutes"] = int(numbers[0])
    moment = clock_time(lower)
    ends = r"\b(?:day|work|working)\b.*\b(?:ends?|finish|stop)|\b(?:end|finish|stop)\s+(?:my\s+)?(?:work\s*|working\s+)?day\b"
    starts = r"\b(?:day|work|working)\b.*\b(?:starts?|begin)|\b(?:start|begin)\s+(?:my\s+)?(?:work\s*|working\s+)?day\b"
    if moment and re.search(ends, lower):
        changes["day_end"] = f"{moment.hour:02d}:{moment.minute:02d}"
    elif moment and re.search(starts, lower):
        hour = moment.hour - 12 if moment.hour >= 13 and not re.search(r"pm", lower) else moment.hour
        changes["day_start"] = f"{hour:02d}:{moment.minute:02d}"
    style = re.search(r"\b(realistic|balanced|ambitious)\b", lower)
    if style:
        changes["planning_style"] = style.group(1)
    voice = re.search(r"\b(?:turn|switch)\s+(on|off)\s+(?:the\s+)?(?:voice|spoken|audio)\s*(?:replies|output|responses|answers)?\b", lower)
    if voice:
        changes["voice_output"] = voice.group(1) == "on"
    return changes


def interpret(text: str, ctx: InterpretContext) -> Plan:
    raw = text.strip()
    lower = normalize(raw)
    memory = ctx.memory
    recovery = memory.get("recovery") if memory.get("recovery") and not memory["recovery"].get("applied") else None

    if not lower:
        return Plan(reply="I didn't catch anything. Try again?", source="rules")

    if re.fullmatch(r"(?:hi|hello|hey|hey there|good morning|good afternoon|good evening)(?: plan b)?", lower):
        return Plan(
            reply="Hi. Tell me what changed, or ask me to plan, move, create, or check something.",
            confidence=0.95,
            source="rules",
        )

    if re.fullmatch(r"(?:thanks|thank you|thankyou|great thanks|okay thanks|got it thanks)", lower):
        return Plan(reply="You're welcome. I'm ready when your plan changes.", confidence=0.95, source="rules")

    if re.search(r"\b(undo|revert|roll ?back|put (it|that|everything) back|take that back|reverse that)\b", lower):
        return _plan("Undo the last change", PlanStep(capability="actions.undo"), confidence=0.95)

    if re.search(r"\bwhat (did|have) (you|we) (change|changed|do|done)\b|\bwhat changed\b|\brecent changes\b|\bshow (me )?(the )?(history|changes)\b", lower):
        return _plan("List recent changes", PlanStep(capability="actions.history"))

    if recovery and re.search(r"\bwhy\b|\bexplain (this|that|the) (plan|option)|\bhow did you (decide|choose)\b", lower):
        return _plan("Explain the plan", PlanStep(capability="schedule.explain"))

    if (APPLY.match(lower) and (recovery or re.search(r"\b(apply|option|plan)\b", lower))) or re.search(
            r"\b(apply|go with|let'?s do) (it|that|this|the (first|second|third|last)|option)\b", lower):
        option = ordinal(lower.replace("apply", "")) if re.search(r"first|second|third|last|option|one|two|three|\b[123]\b", lower) else None
        return _plan("Apply the recovery plan", PlanStep(capability="schedule.apply", arguments={"option": option}, confirmed=True),
                     confidence=0.95)

    fixes = corrections(raw)
    has_fix = any(fixes.values())
    if DISRUPTION.search(lower):
        minutes = duration_minutes(lower)
        target = _target(raw)
        args: dict[str, Any] = {"minutes": minutes, "reason": raw[:300], "target": target, **fixes}
        ack = f"Got it — let me protect the {target} deadline." if target else "Got it — let me look at what that delay breaks."
        return _plan("Recover today's schedule", PlanStep(capability="schedule.recover", arguments=args), ack=ack, confidence=0.9)

    if recovery and has_fix:
        args = {
            "minutes": recovery["minutes"],
            "reason": recovery.get("reason") or "Correction",
            "target": recovery.get("target"),
            "protect": list(dict.fromkeys([*recovery.get("protect", []), *fixes["protect"]])),
            "shorten": [*[s for s in recovery.get("shorten", [])], *fixes["shorten"]],
            "defer": [*[d for d in recovery.get("defer", []) if d not in fixes["protect"]], *fixes["defer"]],
        }
        return _plan("Revise the recovery plan", PlanStep(capability="schedule.recover", arguments=args),
                     ack="Okay, adjusting the plan.", confidence=0.9)

    if re.search(r"\b(open|show|go|take me|navigate|switch|bring up|jump|move to|head to|visit)\b", lower) and len(lower.split()) <= 7:
        page = _page(lower)
        if page and not re.search(r"\b(about|tagged|matching|related to|due)\b", lower):
            if page == "tasks" and re.search(r"\b(done|completed|archived)\b", lower):
                status = re.search(r"\b(done|completed|archived)\b", lower).group(1)
                return _plan("Find tasks", PlanStep(capability="tasks.search", arguments={"status": "done" if status == "completed" else status}))
            return _plan(f"Open {PAGES[page]}", PlanStep(capability="app.navigate", arguments={"target": page}), confidence=0.95)

    if re.search(r"\b(create|add|make|start|new)\b.*\bproject\b", lower):
        match = re.search(r"project\s+(?:called|named|for)?\s*(.+)", raw, re.I)
        name = match.group(1).strip(" .") if match and match.group(1).strip(" .") else None
        return _plan("Create a project", PlanStep(capability="projects.create", arguments={"name": name}))

    if (re.search(r"\b(create|add|make|new|put|schedule)\b.*\btask\b|^task\b|\bremind me to\b|\bi need to\b|\badd\b .+ \bto my (list|tasks|day|calendar)\b", lower)
            or re.search(r"\b(create|add|make|book|block)\b.*\b(schedule|block|slot|session|event|time)\b.*\b(from|at)\s+\d", lower)):
        details = task_details(raw, ctx.today)
        priority = next((p for p in ("high", "low") if f"{p} priority" in lower or (p == "high" and "urgent" in lower)), "medium")
        return _plan("Create a task", PlanStep(capability="tasks.create", arguments={**details, "priority": priority}))

    archive = re.search(r"\b(?:archive|delete|remove|get rid of|trash|drop)\s+(?:the |my )?(.+)", lower)
    if archive:
        phrase = archive.group(1)
        if re.search(r"\bproject\b", phrase):
            name = strip_filler(re.sub(r"\bproject\b", "", phrase))
            return _plan("Archive a project", PlanStep(capability="projects.update", arguments={"project": name, "changes": {"status": "archived"}}))
        return _plan("Archive a task", PlanStep(capability="tasks.archive", arguments={"task": strip_filler(re.sub(r"\btask\b", "", phrase))}))

    restore = re.search(r"\b(?:restore|unarchive|bring back|undelete)\s+(?:the |my )?(.+)", lower)
    if restore:
        return _plan("Restore a task", PlanStep(capability="tasks.restore", arguments={"task": strip_filler(re.sub(r"\btask\b", "", restore.group(1)))}))

    done = (re.search(r"\b(?:mark|set)\s+(.+?)\s+(?:as\s+)?(?:done|complete|completed|finished)\b", lower)
            or re.search(r"\bi(?:'ve| have)?\s+(?:just\s+)?(?:finished|completed|done with)\s+(.+)", lower)
            or re.search(r"^(?:complete|finished|done with)\s+(.+)", lower))
    if done and not re.search(r"\b(before|by|until)\b", lower):
        return _plan("Complete a task", PlanStep(capability="tasks.complete", arguments={"task": strip_filler(done.group(1))}))

    rename = re.search(r"\brename\s+(?:the\s+)?(project\s+)?(.+?)\s+(?:to|as)\s+(.+)", raw, re.I)
    if rename:
        if rename.group(1):
            return _plan("Rename a project", PlanStep(capability="projects.update", arguments={"project": strip_filler(rename.group(2)), "changes": {"name": rename.group(3).strip(" .")}}))
        return _plan("Rename a task", PlanStep(capability="tasks.update", arguments={"task": strip_filler(rename.group(2)), "changes": {"title": rename.group(3).strip(" .")}}))

    priority = (re.search(r"\b(?:make|set|mark)\s+(.+?)\s+(?:as\s+)?(high|low|medium)\s+priority", lower)
                or re.search(r"\b(?:set|change)\s+(?:the\s+)?priority of\s+(.+?)\s+to\s+(high|low|medium)", lower))
    if priority:
        return _plan("Change priority", PlanStep(capability="tasks.update", arguments={"task": strip_filler(priority.group(1)), "changes": {"priority": priority.group(2)}}))
    if re.search(r"^prioriti[sz]e\s+(.+)", lower):
        return _plan("Change priority", PlanStep(capability="tasks.update", arguments={"task": strip_filler(lower.split(" ", 1)[1]), "changes": {"priority": "high"}}))

    deadline = re.search(r"\b(?:move|change|set|push|extend)\s+(?:the\s+)?deadline\s+(?:of|for)\s+(.+?)\s+to\s+(.+)", lower)
    if deadline:
        return _plan("Change a deadline", PlanStep(capability="tasks.update", arguments={"task": strip_filler(deadline.group(1)), "changes": {"deadline": datetime_reference(deadline.group(2), ctx.today)}}))

    move_day = re.search(r"\b(?:move|push|defer|postpone|shift|bump|reschedule)\s+(.+?)\s+to\s+(tomorrow|day after tomorrow|monday|tuesday|wednesday|thursday|friday|saturday|sunday|\d{4}-\d{2}-\d{2})(.*)$", lower)
    if move_day:
        day = day_reference(move_day.group(2), ctx.today) or ctx.today + timedelta(days=1)
        moment = clock_time(move_day.group(3)) or time(9)
        return _plan("Move a task", PlanStep(capability="tasks.update", arguments={
            "task": strip_filler(move_day.group(1)), "changes": {"earliest_start": f"{day.isoformat()}T{moment.hour:02d}:{moment.minute:02d}"}}))

    move_project = re.search(r"\bmove\s+(.+?)\s+(?:in)?to\s+(?:the\s+)?(.+?)\s+project\b", lower)
    if move_project:
        return _plan("Move to project", PlanStep(capability="tasks.update", arguments={"task": strip_filler(move_project.group(1)), "changes": {"project": move_project.group(2)}}))

    resize = re.search(r"\b(?:change|set|make|update|give)\s+(.+?)\s+(?:to\s+|take\s+|only\s+|just\s+)*(\d+.*?(?:min|minutes|hours?|hrs?)|an hour|half an hour)\b", lower)
    if resize and duration_minutes(resize.group(2)) and not re.search(r"\bbuffer|break", lower):
        return _plan("Change duration", PlanStep(capability="tasks.update", arguments={"task": strip_filler(resize.group(1)), "changes": {"duration_minutes": duration_minutes(resize.group(2))}}))

    if has_fix and (fixes["shorten"] or fixes["defer"]):
        if fixes["shorten"] and fixes["shorten"][0].get("minutes"):
            item = fixes["shorten"][0]
            return _plan("Change duration", PlanStep(capability="tasks.update", arguments={"task": item["task"], "changes": {"duration_minutes": item["minutes"]}}))

    if re.search(r"\b(find|is there|do i have|where can i|when can i)\b.*\b(slot|time|gap|room|fit|free|window|space)\b", lower):
        return _plan("Find a free slot", PlanStep(capability="calendar.find_slot", arguments={
            "minutes": duration_minutes(lower), "day": "tomorrow" if "tomorrow" in lower else "today"}))

    if re.search(r"\b(set|change|make|use|switch|turn|i want|i prefer|prefer|update|end|start)\b", lower):
        changes = _preferences(lower)
        if changes:
            return _plan("Update preferences", PlanStep(capability="preferences.update", arguments={"changes": changes}))

    if re.search(r"\b(find|search|look for|look up|which|what|list|show)\b.*\btasks?\b|\bwhat(?:'s| is) (?:still )?open\b", lower):
        query = re.search(r"\b(?:about|for|tagged|matching|related to|called|named)\s+(.+)", lower)
        status = "done" if re.search(r"\b(done|completed|finished)\b", lower) else ("archived" if "archived" in lower else "open")
        return _plan("Find tasks", PlanStep(capability="tasks.search", arguments={"query": strip_filler(query.group(1)) if query else None, "status": status}))

    if re.search(r"\b(risk|at risk|on track|deadlines?|can i (?:still )?(?:make|finish|do|get)|will i (?:make|finish)|am i behind|behind|going to make it)\b", lower):
        target = _target(raw)
        return _plan("Check risks", PlanStep(capability="schedule.assess", arguments={"target": target}))

    if re.search(r"\b(schedule|my day|what'?s next|what is next|agenda|plan for (today|tomorrow)|what'?s on|what do i have|day look)\b", lower):
        return _plan("Read the schedule", PlanStep(capability="calendar.inspect", arguments={"day": "tomorrow" if "tomorrow" in lower else "today"}))

    if re.search(r"\b(patterns?|how (am i|have i been) doing|productivity|focus score|insights?|streak|this week)\b", lower):
        return _plan("Explain patterns", PlanStep(capability="insights.explain"))

    if re.search(r"\b(open|show|go to|take me)\b", lower):
        page = _page(lower)
        if page:
            return _plan(f"Open {PAGES[page]}", PlanStep(capability="app.navigate", arguments={"target": page}))

    return Plan(
        reply=(
            "I didn't find an action in that. You can tell me what changed in your day, ask what's at risk, "
            "or say things like \"move lecture notes to tomorrow\", \"add a task\", or \"undo that\"."
        ),
        confidence=0.3,
        source="rules",
    )
