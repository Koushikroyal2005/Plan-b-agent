from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable


def _dicts(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes, dict)):
        return []
    return [item for item in value if isinstance(item, dict)]


def _is_open(task: dict[str, Any]) -> bool:
    return str(task.get("status", "todo")).lower() not in {"done", "completed", "cancelled"}


def _priority(task: dict[str, Any]) -> int:
    return {"urgent": 4, "high": 3, "medium": 2, "low": 1}.get(
        str(task.get("priority", "medium")).lower(), 2
    )


def _time_label(value: Any) -> str | None:
    if not value:
        return None
    raw = str(value)
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%I:%M %p").lstrip("0")
    except ValueError:
        return raw[:5] if len(raw) >= 5 else raw


def build_briefing(
    *,
    day: dict[str, Any] | None,
    tasks: list[dict[str, Any]] | None,
    projects: list[dict[str, Any]] | None,
    preferences: dict[str, Any] | None,
) -> dict[str, Any]:
    """Create an explainable briefing from the user's live workspace data."""
    day, tasks, projects, preferences = day or {}, tasks or [], projects or [], preferences or {}
    open_tasks = sorted(
        (task for task in tasks if _is_open(task)),
        key=lambda task: (-_priority(task), str(task.get("deadline") or "9999")),
    )
    completed = [task for task in tasks if not _is_open(task)]
    active_projects = [project for project in projects if str(project.get("status", "active")) == "active"]
    blocks = _dicts(day.get("blocks"))
    work_blocks = [block for block in blocks if str(block.get("kind", "task")) not in {"break", "buffer"}]
    risks = _dicts(day.get("risks"))
    planned_minutes = sum(int(block.get("duration_minutes") or 0) for block in work_blocks)
    focus_minutes = sum(
        int(block.get("duration_minutes") or 0)
        for block in work_blocks
        if str(block.get("kind", "task")) in {"task", "focus"}
    )
    capacity = int(day.get("capacity_minutes") or preferences.get("daily_capacity_minutes") or 480)
    utilization = round(planned_minutes / capacity * 100) if capacity else 0

    suggestions: list[dict[str, Any]] = []
    if risks:
        risk = risks[0]
        suggestions.append({
            "id": "protect-plan", "title": "Protect today’s plan",
            "detail": str(risk.get("message") or risk.get("title") or "Your plan has a scheduling risk."),
            "action": "Open today and help me resolve the highest scheduling risk",
            "priority": "high", "confidence": 0.92,
        })
    if utilization > 90:
        suggestions.append({
            "id": "rebalance-day", "title": "Rebalance the workload",
            "detail": f"Today is at {utilization}% of your configured capacity.",
            "action": "Rebalance today and move flexible work to the best available time",
            "priority": "high", "confidence": 0.90,
        })
    if open_tasks and not work_blocks:
        suggestions.append({
            "id": "build-plan", "title": "Turn tasks into a plan",
            "detail": f"You have {len(open_tasks)} open task{'s' if len(open_tasks) != 1 else ''} and no focus block yet.",
            "action": "Plan my day using my priorities and available capacity",
            "priority": "medium", "confidence": 0.88,
        })
    if active_projects and not open_tasks:
        suggestions.append({
            "id": "project-next-step", "title": "Define the next project action",
            "detail": f"{len(active_projects)} active project{'s need' if len(active_projects) != 1 else ' needs'} a concrete next task.",
            "action": "Review my active projects and suggest the best next task",
            "priority": "medium", "confidence": 0.78,
        })
    if not suggestions:
        suggestions.append({
            "id": "focus-next", "title": "Start with the highest-impact work",
            "detail": "Your plan looks balanced. Keep the next action small and explicit.",
            "action": "What should I focus on next?", "priority": "low", "confidence": 0.75,
        })

    next_block = work_blocks[0] if work_blocks else None
    if next_block:
        title = str(next_block.get("title") or next_block.get("task_title") or "your next focus block")
        at = _time_label(next_block.get("start") or next_block.get("start_iso"))
        next_action = f"{title}{f' at {at}' if at else ''}"
    elif open_tasks:
        next_action = str(open_tasks[0].get("title") or "Choose your first task")
    else:
        next_action = "Capture the next thing you want to accomplish"

    hour = datetime.now().hour
    greeting = "Good morning" if hour < 12 else "Good afternoon" if hour < 18 else "Good evening"
    if risks:
        headline = "Your day needs one decision"
        summary = f"I found {len(risks)} planning risk{'s' if len(risks) != 1 else ''}. I can help resolve the highest-impact one."
    elif work_blocks:
        headline = "Your day is ready"
        summary = f"You have {len(work_blocks)} planned block{'s' if len(work_blocks) != 1 else ''} and {focus_minutes // 60}h {focus_minutes % 60}m of focus time."
    elif open_tasks:
        headline = "Let’s shape today"
        summary = f"You have {len(open_tasks)} open task{'s' if len(open_tasks) != 1 else ''}. I can turn them into a realistic plan."
    else:
        headline, summary = "You have room to plan intentionally", "There are no open tasks competing for your attention right now."

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "greeting": greeting, "headline": headline, "summary": summary,
        "next_action": next_action, "suggestions": suggestions[:3],
        "metrics": {
            "open_tasks": len(open_tasks), "completed_tasks": len(completed),
            "active_projects": len(active_projects), "planned_minutes": planned_minutes,
            "focus_minutes": focus_minutes, "capacity_utilization": utilization,
            "risk_count": len(risks),
        },
    }
