from __future__ import annotations

import json
import os
import re
import sqlite3
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from app.config import settings
from app.briefing import build_briefing
from app.engine import LEDGER_SCHEMA, MEMORY_SCHEMA, AssistantEngine
from app.providers import CircuitBreaker, NVIDIAProvider, ProviderError

DB_PATH = settings.database_path
DEMO_ANCHOR = date(2026, 10, 19)


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Plan B API",
    version="2.2.0",
    description="Deterministic planning, recovery, approval, history and provider-ready agent API",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class TaskCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(default="", max_length=1200)
    duration_minutes: int = Field(ge=5, le=720)
    deadline: str | None = None
    earliest_start: str | None = None
    fixed_start: str | None = None
    priority: Literal["low", "medium", "high"] = "medium"
    flexibility: Literal["flexible", "fixed", "buffer"] = "flexible"
    splittable: bool = True
    tags: list[str] = []
    project_id: str | None = None


class TaskPatch(BaseModel):
    title: str | None = None
    description: str | None = None
    duration_minutes: int | None = Field(default=None, ge=5, le=720)
    actual_minutes: int | None = Field(default=None, ge=0, le=1440)
    deadline: str | None = None
    earliest_start: str | None = None
    fixed_start: str | None = None
    priority: Literal["low", "medium", "high"] | None = None
    flexibility: Literal["flexible", "fixed", "buffer"] | None = None
    splittable: bool | None = None
    status: Literal["open", "done", "archived"] | None = None
    tags: list[str] | None = None
    project_id: str | None = None


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    color: str = Field(default="#e4794c", pattern=r"^#[0-9a-fA-F]{6}$")
    target_date: str | None = None


class ProjectPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    description: str | None = Field(default=None, max_length=500)
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    target_date: str | None = None
    status: Literal["active", "completed", "archived"] | None = None


class PreferencesIn(BaseModel):
    display_name: str = Field(default="Koushik", min_length=1, max_length=80)
    day_start: str = "09:00"
    day_end: str = "21:00"
    break_minutes: int = Field(default=10, ge=0, le=120)
    default_buffer_minutes: int = Field(default=15, ge=0, le=180)
    planning_style: Literal["realistic", "balanced", "ambitious"] = "realistic"
    timezone: str = "Asia/Calcutta"
    voice_input: bool = True
    voice_output: bool = False
    language: str = "en-IN"
    onboarding_complete: bool = True


class DisruptionIn(BaseModel):
    disruption_minutes: int = Field(ge=1, le=720)
    reason: str = Field(default="Unexpected disruption", max_length=500)
    task_id: str | None = None
    target_task_id: str | None = None
    protect_task_ids: list[str] = []
    defer_task_ids: list[str] = []
    shorten: dict[str, int] = {}


class AssistantIn(BaseModel):
    message: str | None = Field(default=None, min_length=1, max_length=2000)
    utterance: str | None = Field(default=None, min_length=1, max_length=2000)
    session_id: str = Field(default="default", min_length=1, max_length=120)
    channel: Literal["voice", "text"] = "text"
    current_view: str | None = None
    context: dict[str, Any] = {}
    client_capabilities: list[str] = []
    idempotency_key: str | None = None


class OpportunityResponse(BaseModel):
    accepted: bool


class ProviderModelIn(BaseModel):
    model: str = Field(min_length=3, max_length=200)


def db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def utcnow() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def uid() -> str:
    return str(uuid.uuid4())


def parse_clock(value: str | None, fallback: time) -> time:
    if not value:
        return fallback
    try:
        return time.fromisoformat(value[-5:])
    except ValueError:
        return fallback


def parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def clock(value: datetime) -> str:
    hour = value.hour % 12 or 12
    return f"{hour}:{value.minute:02d} {'AM' if value.hour < 12 else 'PM'}"


def planning_day() -> date:
    return date.today()


def get_setting(key: str, default: str | None = None) -> str | None:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key=?", (key,)
            ).fetchone()
    except sqlite3.OperationalError:
        return default
    return row["value"] if row and row["value"] != "" else default


def set_setting(key: str, value: str | None) -> None:
    with db() as conn:
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
            (key, value or "", utcnow()),
        )


def planning_now() -> datetime | None:
    """Scheduling starts from here today. Only the judge demo pins a clock;
    normal mode plans the whole working day."""
    demo_clock = get_setting("demo_clock")
    if not demo_clock:
        return None
    return datetime.combine(planning_day(), parse_clock(demo_clock, time(9)))


def align_demo_dates(conn: sqlite3.Connection) -> None:
    """Move the original demo dates onto the current day without touching edited dates."""
    today = planning_day()
    if today == DEMO_ANCHOR:
        return
    demo_tasks = {
        "Prepare project report": {"deadline": "T12:00"},
        "Parcel collection": {"deadline": "T17:00", "fixed_start": "T16:15"},
        "Team meeting": {"fixed_start": "T14:00"},
        "Finish assignment": {"deadline": "T18:00"},
    }
    for title, fields in demo_tasks.items():
        row = conn.execute(
            "SELECT deadline, fixed_start FROM tasks WHERE title=?", (title,)
        ).fetchone()
        if not row:
            continue
        updates: dict[str, str] = {}
        for column, suffix in fields.items():
            current = row[column] or ""
            if current.startswith(DEMO_ANCHOR.isoformat()):
                updates[column] = f"{today.isoformat()}{suffix}"
        if updates:
            assignments = ", ".join(f"{column}=?" for column in updates)
            conn.execute(
                f"UPDATE tasks SET {assignments}, updated_at=? WHERE title=?",
                (*updates.values(), utcnow(), title),
            )
    project_shifts = {
        "Product launch": (4, "2026-10-23"),
        "Study sprint": (2, "2026-10-21"),
    }
    for name, (offset, original) in project_shifts.items():
        conn.execute(
            "UPDATE projects SET target_date=? WHERE name=? AND target_date=?",
            ((today + timedelta(days=offset)).isoformat(), name, original),
        )


def init_db() -> None:
    with db() as conn:
        existing = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'"
        ).fetchone()
        migrated_legacy = False
        if existing:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
            if "description" not in columns:
                conn.execute("PRAGMA foreign_keys = OFF")
                for table in ("proposals", "plans", "events", "tasks"):
                    if conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone():
                        legacy = f"{table}_legacy_v1"
                        if not conn.execute(
                            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                            (legacy,),
                        ).fetchone():
                            conn.execute(f"ALTER TABLE {table} RENAME TO {legacy}")
                migrated_legacy = True
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS tasks (
              id TEXT PRIMARY KEY, title TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              duration_minutes INTEGER NOT NULL, actual_minutes INTEGER, deadline TEXT,
              earliest_start TEXT, fixed_start TEXT, priority TEXT NOT NULL,
              flexibility TEXT NOT NULL, splittable INTEGER NOT NULL DEFAULT 1,
              tags_json TEXT NOT NULL DEFAULT '[]', status TEXT NOT NULL DEFAULT 'open',
              created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS projects (
              id TEXT PRIMARY KEY, name TEXT NOT NULL, description TEXT NOT NULL DEFAULT '',
              color TEXT NOT NULL DEFAULT '#e4794c', target_date TEXT,
              status TEXT NOT NULL DEFAULT 'active', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS preferences (
              id INTEGER PRIMARY KEY CHECK (id=1), display_name TEXT NOT NULL,
              day_start TEXT NOT NULL, day_end TEXT NOT NULL, break_minutes INTEGER NOT NULL,
              default_buffer_minutes INTEGER NOT NULL, planning_style TEXT NOT NULL,
              timezone TEXT NOT NULL, voice_input INTEGER NOT NULL, voice_output INTEGER NOT NULL,
              language TEXT NOT NULL, onboarding_complete INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS plans (
              id TEXT PRIMARY KEY, version INTEGER NOT NULL, status TEXT NOT NULL,
              reason TEXT NOT NULL, before_json TEXT NOT NULL, after_json TEXT NOT NULL,
              selected_proposal_id TEXT, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS proposals (
              id TEXT PRIMARY KEY, plan_id TEXT NOT NULL, title TEXT NOT NULL,
              description TEXT NOT NULL, tradeoff TEXT NOT NULL, feasible INTEGER NOT NULL,
              validation_json TEXT NOT NULL, revised_json TEXT NOT NULL,
              approved INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
              FOREIGN KEY(plan_id) REFERENCES plans(id)
            );
            CREATE TABLE IF NOT EXISTS events (
              id TEXT PRIMARY KEY, event_type TEXT NOT NULL, detail TEXT NOT NULL,
              metadata_json TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_sessions (
              id TEXT PRIMARY KEY, state_json TEXT NOT NULL DEFAULT '{}',
              last_response_json TEXT NOT NULL DEFAULT '{}', updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assistant_turns (
              id TEXT PRIMARY KEY, session_id TEXT NOT NULL, utterance TEXT NOT NULL,
              response_json TEXT NOT NULL, created_at TEXT NOT NULL,
              FOREIGN KEY(session_id) REFERENCES assistant_sessions(id)
            );
            CREATE TABLE IF NOT EXISTS assistant_idempotency (
              key TEXT PRIMARY KEY, session_id TEXT NOT NULL,
              response_json TEXT NOT NULL, created_at TEXT NOT NULL
            );
            """
            + LEDGER_SCHEMA
            + MEMORY_SCHEMA
        )
        columns = {row[1] for row in conn.execute("PRAGMA table_info(tasks)")}
        if "project_id" not in columns:
            conn.execute("ALTER TABLE tasks ADD COLUMN project_id TEXT")
        if migrated_legacy:
            conn.execute(
                """INSERT OR IGNORE INTO tasks
                (id,title,description,duration_minutes,actual_minutes,deadline,earliest_start,fixed_start,priority,flexibility,splittable,tags_json,status,created_at,updated_at)
                SELECT id,title,'',duration_minutes,NULL,deadline,NULL,NULL,priority,flexibility,splittable,'[]',status,created_at,created_at
                FROM tasks_legacy_v1"""
            )
            conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            """INSERT OR IGNORE INTO preferences VALUES
            (1,'Koushik','09:00','21:00',10,15,'realistic','Asia/Calcutta',1,0,'en-IN',1)"""
        )
        conn.execute(
            "INSERT OR IGNORE INTO app_settings VALUES (?,?,?)",
            ("active_llm_model", settings.llm_model, utcnow()),
        )
        align_demo_dates(conn)
        if os.getenv("PLANB_SEED", "1") == "1":
            today_iso = planning_day().isoformat()
            seed = [
                (
                    "Prepare project report",
                    "Finalize the project narrative and evidence.",
                    60,
                    None,
                    f"{today_iso}T12:00",
                    None,
                    "high",
                    "flexible",
                    0,
                    ["work"],
                ),
                (
                    "Review lecture notes",
                    "Review chapter 4 notes.",
                    45,
                    None,
                    None,
                    None,
                    "medium",
                    "flexible",
                    1,
                    ["study"],
                ),
                (
                    "Parcel collection",
                    "Collect parcel before the office closes.",
                    30,
                    None,
                    f"{today_iso}T17:00",
                    f"{today_iso}T16:15",
                    "medium",
                    "fixed",
                    0,
                    ["errand"],
                ),
                (
                    "Team meeting",
                    "Project sync with the team.",
                    60,
                    None,
                    None,
                    f"{today_iso}T14:00",
                    "high",
                    "fixed",
                    0,
                    ["work"],
                ),
                (
                    "Finish assignment",
                    "Complete and upload the final assignment.",
                    120,
                    None,
                    f"{today_iso}T18:00",
                    None,
                    "high",
                    "flexible",
                    1,
                    ["study"],
                ),
            ]
            for (
                title,
                description,
                duration,
                actual,
                deadline,
                fixed_start,
                priority,
                flexibility,
                splittable,
                tags,
            ) in seed:
                if conn.execute(
                    "SELECT 1 FROM tasks WHERE title=?", (title,)
                ).fetchone():
                    continue
                stamp = utcnow()
                conn.execute(
                    """INSERT INTO tasks
                    (id,title,description,duration_minutes,actual_minutes,deadline,earliest_start,fixed_start,priority,flexibility,splittable,tags_json,status,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        uid(),
                        title,
                        description,
                        duration,
                        actual,
                        deadline,
                        None,
                        fixed_start,
                        priority,
                        flexibility,
                        splittable,
                        json.dumps(tags),
                        "open",
                        stamp,
                        stamp,
                    ),
                )
        project_seed = [
            (
                "Product launch",
                "Report, launch and team delivery work",
                "#e4794c",
                (planning_day() + timedelta(days=4)).isoformat(),
            ),
            (
                "Study sprint",
                "Lectures and assignment completion",
                "#657c9a",
                (planning_day() + timedelta(days=2)).isoformat(),
            ),
            ("Personal admin", "Errands and personal commitments", "#71886b", None),
        ]
        for name, description, color, target_date in project_seed:
            if not conn.execute(
                "SELECT 1 FROM projects WHERE name=?", (name,)
            ).fetchone():
                stamp = utcnow()
                conn.execute(
                    "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)",
                    (
                        uid(),
                        name,
                        description,
                        color,
                        target_date,
                        "active",
                        stamp,
                        stamp,
                    ),
                )
        project_ids = {
            row["name"]: row["id"]
            for row in conn.execute("SELECT id,name FROM projects")
        }
        conn.execute(
            "UPDATE tasks SET project_id=? WHERE project_id IS NULL AND tags_json LIKE '%study%'",
            (project_ids.get("Study sprint"),),
        )
        conn.execute(
            "UPDATE tasks SET project_id=? WHERE project_id IS NULL AND tags_json LIKE '%errand%'",
            (project_ids.get("Personal admin"),),
        )
        conn.execute(
            "UPDATE tasks SET project_id=? WHERE project_id IS NULL",
            (project_ids.get("Product launch"),),
        )


def task_from_row(row: sqlite3.Row) -> dict[str, Any]:
    result = dict(row)
    result["splittable"] = bool(result["splittable"])
    result["tags"] = json.loads(result.pop("tags_json") or "[]")
    return result


def get_tasks(include_archived: bool = False) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE status != 'archived'"
    with db() as conn:
        return [
            task_from_row(row)
            for row in conn.execute(f"SELECT * FROM tasks {where} ORDER BY created_at")
        ]


def get_projects(include_archived: bool = False) -> list[dict[str, Any]]:
    where = "" if include_archived else "WHERE p.status != 'archived'"
    with db() as conn:
        rows = conn.execute(
            f"""SELECT p.*,
            COUNT(t.id) AS task_count,
            SUM(CASE WHEN t.status='done' THEN 1 ELSE 0 END) AS completed_count,
            COALESCE(SUM(CASE WHEN t.status!='archived' THEN t.duration_minutes ELSE 0 END),0) AS planned_minutes
            FROM projects p LEFT JOIN tasks t ON t.project_id=p.id {where}
            GROUP BY p.id ORDER BY p.created_at"""
        ).fetchall()
    projects = []
    for row in rows:
        item = dict(row)
        item["progress"] = (
            round(item["completed_count"] / item["task_count"] * 100)
            if item["task_count"]
            else 0
        )
        projects.append(item)
    return projects


def get_preferences() -> dict[str, Any]:
    with db() as conn:
        row = conn.execute("SELECT * FROM preferences WHERE id=1").fetchone()
    result = dict(row)
    result["voice_input"] = bool(result["voice_input"])
    result["voice_output"] = bool(result["voice_output"])
    result["onboarding_complete"] = bool(result["onboarding_complete"])
    return result


def priority_rank(value: str) -> int:
    return {"high": 0, "medium": 1, "low": 2}.get(value, 1)


def schedule_tasks(
    tasks: list[dict[str, Any]],
    deferred_ids: set[str] | None = None,
    day_end_extension: int = 0,
    disruption: dict[str, Any] | None = None,
    on: date | None = None,
    duration_overrides: dict[str, int] | None = None,
) -> dict[str, Any]:
    prefs = get_preferences()
    day = on or planning_day()
    start = datetime.combine(day, parse_clock(prefs["day_start"], time(9)))
    now = planning_now()
    if duration_overrides:
        tasks = [
            {**t, "duration_minutes": duration_overrides[t["id"]]}
            if t["id"] in duration_overrides
            else t
            for t in tasks
        ]
    day_end = datetime.combine(
        day, parse_clock(prefs["day_end"], time(21))
    ) + timedelta(minutes=day_end_extension)
    style_adjustment = {"realistic": 5, "balanced": 0, "ambitious": -5}.get(
        prefs.get("planning_style"), 0
    )
    buffer_minutes = max(0, int(prefs["default_buffer_minutes"]) + style_adjustment)
    break_minutes = int(prefs.get("break_minutes") or 0)
    deferred_ids = deferred_ids or set()

    def scheduled_on_another_day(task: dict[str, Any]) -> bool:
        fixed = parse_dt(task.get("fixed_start"))
        if fixed:
            return fixed.date() != day
        earliest = parse_dt(task.get("earliest_start"))
        return bool(earliest and earliest.date() > day)

    open_tasks = [
        t
        for t in tasks
        if t["status"] == "open"
        and t["id"] not in deferred_ids
        and not scheduled_on_another_day(t)
    ]
    fixed = sorted(
        [t for t in open_tasks if t["flexibility"] == "fixed" and t.get("fixed_start")],
        key=lambda t: t["fixed_start"],
    )
    flexible = sorted(
        [t for t in open_tasks if t not in fixed],
        key=lambda t: (
            parse_dt(t.get("deadline")) or datetime.max,
            priority_rank(t["priority"]),
            t["created_at"],
        ),
    )
    fixed_slots: list[tuple[datetime, datetime, dict[str, Any]]] = []
    disrupted_id = disruption.get("task_id") if disruption else None
    for task in fixed:
        fixed_start = parse_dt(task["fixed_start"]) or start
        extra = (
            disruption["minutes"]
            if disruption
            and (
                task["id"] == disrupted_id
                or (not disrupted_id and "meeting" in task["title"].lower())
            )
            else 0
        )
        fixed_slots.append(
            (
                fixed_start,
                fixed_start + timedelta(minutes=task["duration_minutes"] + extra),
                task,
            )
        )
    blocks: list[dict[str, Any]] = []
    cursor = max(start, now) if now and now.date() == day else start
    focus_since_break = 0

    def park(after: datetime, focused_minutes: int) -> datetime:
        nonlocal focus_since_break
        focus_since_break += focused_minutes
        nxt = after + timedelta(minutes=buffer_minutes)
        if break_minutes and focus_since_break >= 90 and nxt < day_end:
            break_end = nxt + timedelta(minutes=break_minutes)
            blocks.append(
                {
                    "task_id": None,
                    "title": "Recovery break",
                    "start_iso": nxt.isoformat(),
                    "end_iso": break_end.isoformat(),
                    "start": clock(nxt),
                    "end": clock(break_end),
                    "minutes": break_minutes,
                    "kind": "break",
                    "label": "Break",
                    "detail": f"{break_minutes} minute break from your settings",
                    "deadline": None,
                }
            )
            focus_since_break = 0
            return break_end
        return nxt

    def add_block(
        task: dict[str, Any],
        block_start: datetime,
        block_end: datetime,
        kind: str,
        detail: str | None = None,
    ):
        deadline = parse_dt(task.get("deadline"))
        late = bool(deadline and block_end > deadline)
        blocks.append(
            {
                "task_id": task["id"],
                "title": task["title"],
                "start_iso": block_start.isoformat(),
                "end_iso": block_end.isoformat(),
                "start": clock(block_start),
                "end": clock(block_end),
                "minutes": int((block_end - block_start).total_seconds() / 60),
                "kind": "risk" if late else kind,
                "label": (
                    "Misses deadline"
                    if late
                    else ("Fixed" if kind == "fixed" else "Scheduled")
                ),
                "detail": detail
                or f"{task['priority'].title()} priority · {task['duration_minutes']} min",
                "deadline": task.get("deadline"),
            }
        )

    remaining = flexible.copy()
    for fixed_start, fixed_end, fixed_task in fixed_slots:
        while remaining:
            task = remaining[0]
            earliest = max(cursor, parse_dt(task.get("earliest_start")) or cursor)
            needed = timedelta(minutes=task["duration_minutes"])
            if earliest + needed <= fixed_start:
                add_block(task, earliest, earliest + needed, "focus")
                cursor = park(earliest + needed, task["duration_minutes"])
                remaining.pop(0)
            else:
                break
        if cursor < fixed_start:
            cursor = fixed_start
        detail = "Fixed commitment"
        if disruption and (
            fixed_task["id"] == disrupted_id
            or (not disrupted_id and "meeting" in fixed_task["title"].lower())
        ):
            detail = f"Fixed · overran by {disruption['minutes']} min"
        add_block(fixed_task, fixed_start, fixed_end, "fixed", detail)
        cursor = max(cursor, fixed_end + timedelta(minutes=buffer_minutes))
    for task in remaining:
        earliest = max(cursor, parse_dt(task.get("earliest_start")) or cursor)
        end = earliest + timedelta(minutes=task["duration_minutes"])
        add_block(task, earliest, end, "focus")
        cursor = park(end, task["duration_minutes"])

    blocks.sort(key=lambda b: b["start_iso"])
    risks = []
    for block in blocks:
        deadline = parse_dt(block.get("deadline"))
        if deadline:
            end = parse_dt(block["end_iso"])
            slack = int((deadline - end).total_seconds() / 60)
            if slack < 0:
                risks.append(
                    {
                        "task_id": block["task_id"],
                        "task": block["title"],
                        "severity": "critical",
                        "slack_minutes": slack,
                        "reason": f"The scheduled block ends {-slack} minutes after its deadline.",
                    }
                )
            elif slack < max(45, buffer_minutes * 2):
                risks.append(
                    {
                        "task_id": block["task_id"],
                        "task": block["title"],
                        "severity": "high",
                        "slack_minutes": slack,
                        "reason": f"Only {slack} minutes of safe time remain before the deadline.",
                    }
                )
    scheduled_minutes = sum(b["minutes"] for b in blocks)
    capacity = int((day_end - start).total_seconds() / 60)
    overrun = max(
        0,
        int(
            (cursor - timedelta(minutes=buffer_minutes) - day_end).total_seconds() / 60
        ),
    )
    if overrun:
        risks.append(
            {
                "task_id": None,
                "task": "Daily capacity",
                "severity": "critical",
                "slack_minutes": -overrun,
                "reason": f"The plan exceeds working hours by {overrun} minutes.",
            }
        )
    free = max(
        0, capacity - scheduled_minutes - max(0, len(blocks) - 1) * buffer_minutes
    )
    confidence = max(24, min(96, 94 - len(risks) * 14 - (12 if free < 30 else 0)))
    return {
        "date": day.isoformat(),
        "status": "at_risk" if risks else "on_track",
        "blocks": blocks,
        "risks": risks,
        "metrics": {
            "scheduled_minutes": scheduled_minutes,
            "scheduled_hours": round(scheduled_minutes / 60, 1),
            "free_buffer_minutes": free,
            "deadlines_today": sum(
                1
                for t in open_tasks
                if parse_dt(t.get("deadline"))
                and parse_dt(t["deadline"]).date() == day
            ),
            "risky_tasks": len(risks),
            "confidence": confidence,
            "applied_buffer_minutes": buffer_minutes,
            "applied_break_minutes": break_minutes,
            "planning_style": prefs.get("planning_style"),
        },
        "deferred_task_ids": list(deferred_ids),
        "duration_overrides": duration_overrides or {},
        "valid": not any(r["severity"] == "critical" for r in risks),
    }


def latest_relevant_plan() -> dict[str, Any] | None:
    with db() as conn:
        row = conn.execute(
            """SELECT * FROM plans
            WHERE status IN ('applied','restored','outdated')
            ORDER BY created_at DESC, version DESC LIMIT 1"""
        ).fetchone()
    return dict(row) if row else None


def current_day(on: date | None = None) -> dict[str, Any]:
    day = on or planning_day()
    tasks = get_tasks()
    plan = latest_relevant_plan()
    if plan and plan["status"] in {"applied", "restored"} and day == planning_day():
        payload = json.loads(plan["after_json"])
        if payload.get("date") == day.isoformat():
            payload["active_plan_id"] = plan["id"]
            payload["plan_version"] = plan["version"]
            payload["plan_stale"] = False
            payload["schedule_source"] = "approved_plan"
            return payload
    payload = schedule_tasks(tasks, on=day)
    payload["plan_version"] = plan["version"] if plan else 1
    payload["plan_stale"] = bool(plan and plan["status"] == "outdated")
    payload["schedule_source"] = "live"
    if plan and plan["status"] in {"applied", "restored"}:
        payload["active_plan_id"] = plan["id"]
    return payload


def validate_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    critical = [r for r in candidate["risks"] if r["severity"] == "critical"]
    return {
        "feasible": len(critical) == 0,
        "checked": [
            "durations",
            "deadlines",
            "fixed commitments",
            "working hours",
            "buffers",
        ],
        "violations": critical,
        "checked_at": utcnow(),
    }


def tomorrow_values(task: dict[str, Any], prefs: dict[str, Any]) -> dict[str, Any]:
    tomorrow = planning_day() + timedelta(days=1)
    start_clock = parse_clock(prefs["day_start"], time(9)).strftime("%H:%M")
    values: dict[str, Any] = {"earliest_start": f"{tomorrow.isoformat()}T{start_clock}"}
    deadline = parse_dt(task.get("deadline"))
    if deadline and deadline.date() <= planning_day():
        values["deadline"] = f"{tomorrow.isoformat()}T{deadline.strftime('%H:%M')}"
    return values


def shortened_minutes(task: dict[str, Any], deficit: int) -> int:
    """Cut enough to cover the deficit plus a 15 minute cushion, never more than half."""
    duration = int(task["duration_minutes"])
    wanted = max(15, -(-max(deficit, 0) // 5) * 5 + 15)
    return max(10, duration - min(wanted, duration // 2))


def task_change(task: dict[str, Any], kind: str, values: dict[str, Any], summary: str) -> dict[str, Any]:
    return {
        "task_id": task["id"],
        "title": task["title"],
        "kind": kind,
        "values": values,
        "before": {key: task.get(key) for key in values},
        "summary": summary,
    }


def generate_recovery(payload: DisruptionIn) -> dict[str, Any]:
    tasks = get_tasks()
    by_id = {t["id"]: t for t in tasks}
    prefs = get_preferences()
    original = current_day()
    disruption = {"minutes": payload.disruption_minutes, "task_id": payload.task_id}
    affected = schedule_tasks(tasks, disruption=disruption)
    critical = [r for r in affected["risks"] if r["severity"] == "critical"]
    target_id = payload.target_task_id if payload.target_task_id in by_id else None
    target_id = target_id or next((r["task_id"] for r in critical if r["task_id"]), None)
    protected = {i for i in payload.protect_task_ids if i in by_id}
    if target_id:
        protected.add(target_id)
    deficit = max((-r["slack_minutes"] for r in critical), default=0)
    scheduled_ids = {b["task_id"] for b in affected["blocks"] if b["task_id"]}
    requested_shorten = {k: v for k, v in payload.shorten.items() if k in by_id}
    requested_defer = {k for k in payload.defer_task_ids if k in by_id} - protected
    used = set(requested_shorten) | requested_defer

    def adjustable(task: dict[str, Any]) -> bool:
        return (
            task["status"] == "open"
            and task["flexibility"] == "flexible"
            and task["id"] in scheduled_ids
            and task["id"] not in protected
            and task["id"] not in used
        )

    candidates: list[dict[str, Any]] = []
    if requested_shorten or requested_defer:
        overrides: dict[str, int] = {}
        changes = []
        for task_id, minutes in requested_shorten.items():
            task = by_id[task_id]
            minutes = int(minutes) if minutes else shortened_minutes(task, deficit)
            overrides[task_id] = minutes
            changes.append(task_change(task, "shorten", {"duration_minutes": minutes},
                f"{task['title']} shortens from {task['duration_minutes']} to {minutes} min"))
        for task_id in requested_defer:
            task = by_id[task_id]
            changes.append(task_change(task, "defer", tomorrow_values(task, prefs), f"{task['title']} moves to tomorrow"))
        candidates.append({
            "strategy": "requested",
            "title": "; ".join(c["summary"] for c in changes),
            "description": "The change you asked for. " + " ".join(f"{c['summary']}." for c in changes),
            "tradeoff": "Shortened work gets less time, so start with the essential part."
            if requested_shorten else "Moved work waits until tomorrow.",
            "day": schedule_tasks(tasks, deferred_ids=requested_defer, disruption=disruption, duration_overrides=overrides),
            "changes": changes,
        })

    if affected["valid"]:
        candidates.append({
            "strategy": "absorb",
            "title": "Absorb the delay",
            "description": "Everything still fits after the shift, so only start times move.",
            "tradeoff": "You keep every task but lose some free buffer today.",
            "day": affected,
            "changes": [],
        })
    else:
        deferred_choice = None
        defer_pool = sorted(
            (t for t in tasks if adjustable(t)),
            key=lambda t: (t.get("deadline") is not None, -priority_rank(t["priority"]), t["duration_minutes"]),
        )
        for task in defer_pool[:6]:
            day = schedule_tasks(tasks, deferred_ids={task["id"]}, disruption=disruption)
            if validate_candidate(day)["feasible"]:
                values = tomorrow_values(task, prefs)
                moved_deadline = " Its deadline moves to tomorrow too." if "deadline" in values else ""
                candidates.append({
                    "strategy": "defer",
                    "title": f"Move {task['title']} to tomorrow",
                    "description": f"{task['title']} starts tomorrow instead.{moved_deadline} Everything else stays today.",
                    "tradeoff": f"{task['title']} waits a day.",
                    "day": day,
                    "changes": [task_change(task, "defer", values, f"{task['title']} moves to tomorrow")],
                })
                deferred_choice = task["id"]
                break
        shorten_pool = sorted(
            (t for t in tasks if adjustable(t) and t["id"] != deferred_choice and t["splittable"] and t["duration_minutes"] >= 30),
            key=lambda t: (-priority_rank(t["priority"]), -t["duration_minutes"]),
        )
        for task in shorten_pool[:6]:
            minutes = shortened_minutes(task, deficit)
            day = schedule_tasks(tasks, disruption=disruption, duration_overrides={task["id"]: minutes})
            if validate_candidate(day)["feasible"]:
                candidates.append({
                    "strategy": "shorten",
                    "title": f"Shorten {task['title']} to {minutes} min",
                    "description": f"Give {task['title']} {minutes} minutes instead of {task['duration_minutes']}. Nothing leaves today.",
                    "tradeoff": f"{task['title']} gets {task['duration_minutes'] - minutes} fewer minutes, so do the essential part first.",
                    "day": day,
                    "changes": [task_change(task, "shorten", {"duration_minutes": minutes},
                        f"{task['title']} shortens from {task['duration_minutes']} to {minutes} min")],
                })
                break
        candidates.append({
            "strategy": "extend",
            "title": "Keep every task, extend the day",
            "description": "Keep today's workload and use up to one additional hour after normal working time.",
            "tradeoff": "Nothing moves, but the day gets longer and deadlines inside the day do not move.",
            "day": schedule_tasks(tasks, day_end_extension=60, disruption=disruption),
            "changes": [],
        })
        candidates.append({
            "strategy": "renegotiate",
            "title": "Keep the disrupted plan",
            "description": "Keep every task where it lands and ask to change a deadline or fixed time instead.",
            "tradeoff": "No message is sent automatically, and the other party may not agree.",
            "day": affected,
            "changes": [],
        })

    validations = [validate_candidate(c["day"]) for c in candidates]
    first_feasible = next((c for c, v in zip(candidates, validations) if v["feasible"]), candidates[0])
    plan_id = uid()
    with db() as conn:
        version = conn.execute("SELECT COALESCE(MAX(version),1)+1 FROM plans").fetchone()[0]
        conn.execute(
            "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)",
            (plan_id, version, "awaiting_approval", payload.reason, json.dumps(original),
             json.dumps(first_feasible["day"]), None, utcnow()),
        )
        options = []
        for candidate, validation in zip(candidates, validations):
            proposal_id = uid()
            revised = {**candidate["day"], "changes": candidate["changes"]}
            conn.execute(
                "INSERT INTO proposals VALUES (?,?,?,?,?,?,?,?,?,?)",
                (proposal_id, plan_id, candidate["title"], candidate["description"], candidate["tradeoff"],
                 int(validation["feasible"]), json.dumps(validation), json.dumps(revised), 0, utcnow()),
            )
            options.append({
                "id": proposal_id,
                "strategy": candidate["strategy"],
                "title": candidate["title"],
                "description": candidate["description"],
                "tradeoff": candidate["tradeoff"],
                "feasible": validation["feasible"],
                "validation": validation,
                "changes": candidate["changes"],
                "revised_blocks": candidate["day"]["blocks"],
                "metrics": candidate["day"]["metrics"],
            })
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (uid(), "recovery_generated", payload.reason,
             json.dumps({"minutes": payload.disruption_minutes}), utcnow()),
        )
    recommended = next((o["id"] for o in options if o["feasible"]), options[0]["id"])
    target = by_id.get(target_id) if target_id else None
    return {
        "plan_id": plan_id,
        "reason": payload.reason,
        "disruption_minutes": payload.disruption_minutes,
        "affected_tasks": [r["task"] for r in affected["risks"]]
        or [b["title"] for b in affected["blocks"][-2:]],
        "original_blocks": original["blocks"],
        "disrupted_blocks": affected["blocks"],
        "options": options,
        "recommended_option_id": recommended,
        "validated": all("validation" in o for o in options),
        "constraints": {
            "target": {"id": target["id"], "title": target["title"], "deadline": target.get("deadline")} if target else None,
            "protected": [{"id": i, "title": by_id[i]["title"]} for i in sorted(protected)],
            "shorten": {k: v for k, v in requested_shorten.items()},
            "defer": sorted(requested_defer),
        },
        "evidence": {
            "deficit_minutes": deficit,
            "critical_risks": critical,
            "free_buffer_before": original["metrics"]["free_buffer_minutes"],
            "free_buffer_after_delay": affected["metrics"]["free_buffer_minutes"],
            "options_checked": len(options),
            "feasible_options": sum(1 for o in options if o["feasible"]),
        },
    }


def apply_proposal(proposal_id: str) -> dict[str, Any]:
    """Apply a validated proposal and return what is needed to undo it."""
    with db() as conn:
        proposal = conn.execute("SELECT * FROM proposals WHERE id=?", (proposal_id,)).fetchone()
        if not proposal:
            raise HTTPException(404, "Proposal not found")
        validation = json.loads(proposal["validation_json"])
        if not validation["feasible"]:
            raise HTTPException(409, "This option is not feasible. Change a constraint before applying it.")
        plan = conn.execute("SELECT * FROM plans WHERE id=?", (proposal["plan_id"],)).fetchone()
        if plan["status"] != "awaiting_approval":
            raise HTTPException(409, "This proposal is stale or already resolved")
        revised = json.loads(proposal["revised_json"])
        restores = []
        for change in revised.get("changes", []):
            row = conn.execute("SELECT * FROM tasks WHERE id=?", (change["task_id"],)).fetchone()
            if not row:
                continue
            values = change["values"]
            restores.append({"task_id": change["task_id"], "fields": {k: row[k] for k in values}})
            conn.execute(
                f"UPDATE tasks SET {', '.join(f'{k}=?' for k in values)}, updated_at=? WHERE id=?",
                (*values.values(), utcnow(), change["task_id"]),
            )
        conn.execute("UPDATE proposals SET approved=1 WHERE id=?", (proposal_id,))
        conn.execute(
            "UPDATE plans SET status='applied',selected_proposal_id=?,after_json=? WHERE id=?",
            (proposal_id, proposal["revised_json"], proposal["plan_id"]),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (uid(), "plan_applied", proposal["title"], json.dumps({"proposal_id": proposal_id}), utcnow()),
        )
    return {
        "status": "applied",
        "plan_id": proposal["plan_id"],
        "proposal_id": proposal_id,
        "title": proposal["title"],
        "changes": revised.get("changes", []),
        "task_restores": restores,
        "before": json.loads(plan["before_json"]),
        "day": revised,
    }


def revert_applied_plan(plan_id: str, task_restores: list[dict[str, Any]]) -> dict[str, Any]:
    with db() as conn:
        plan = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not plan:
            raise HTTPException(404, "Plan not found")
        for restore in task_restores:
            fields = restore["fields"]
            conn.execute(
                f"UPDATE tasks SET {', '.join(f'{k}=?' for k in fields)}, updated_at=? WHERE id=?",
                (*fields.values(), utcnow(), restore["task_id"]),
            )
        conn.execute("UPDATE plans SET status='undone' WHERE id=?", (plan_id,))
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (uid(), "plan_undone", f"Undid plan v{plan['version']}", json.dumps({"plan_id": plan_id}), utcnow()),
        )
    return current_day()


CURATED_MODELS = [
    "openai/gpt-oss-20b",
    "openai/gpt-oss-120b",
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "meta/llama-3.3-70b-instruct",
    "qwen/qwen3-next-80b-a3b-instruct",
    "deepseek-ai/deepseek-v3.1-terminus",
]


def get_selected_model() -> str:
    try:
        with db() as conn:
            row = conn.execute(
                "SELECT value FROM app_settings WHERE key='active_llm_model'"
            ).fetchone()
        return row["value"] if row and row["value"] else settings.llm_model
    except sqlite3.OperationalError:
        return settings.llm_model


planner_breaker = CircuitBreaker(failure_threshold=2, cooldown_seconds=60)


def provider_client() -> NVIDIAProvider:
    return NVIDIAProvider(
        api_key=settings.llm_api_key,
        base_url=settings.llm_base_url,
        default_model=get_selected_model(),
        timeout_seconds=settings.llm_timeout_seconds,
    )


def provider_status() -> dict[str, Any]:
    configured = settings.provider_configured
    return {
        "provider": settings.llm_provider,
        "model": get_selected_model() or "not configured",
        "configured": configured,
        "mode": "provider" if configured else "deterministic fallback",
        "endpoint": settings.llm_base_url if configured else "not configured",
        "voice": {"asr": settings.asr_provider, "tts": settings.tts_provider},
        "planner": {
            "timeout_seconds": settings.llm_timeout_seconds,
            "circuit": planner_breaker.status(),
        },
        "mcp": {"status": "ready", "tools": 10},
        "catalog": CURATED_MODELS,
    }


def call_provider(message: str, model: str | None = None) -> str | None:
    if not settings.provider_configured:
        return None
    try:
        return provider_client().chat(message, model=model)
    except ProviderError:
        return None


def call_provider_structured(system: str, prompt: str) -> dict[str, Any] | None:
    if not planner_enabled():
        return None
    try:
        client = provider_client()
        structured = getattr(client, "structured", None)
        result = structured(system, prompt) if structured else None
    except (ProviderError, AttributeError, TypeError):
        planner_breaker.failure()
        return None
    planner_breaker.success()
    return result


def planner_enabled() -> bool:
    return settings.provider_configured and not planner_breaker.is_open


@app.get("/api/health")
def health():
    return {
        "ok": True,
        "service": "plan-b-api",
        "version": "2.2.0",
        "database": str(DB_PATH.name),
        "provider": provider_status(),
    }


@app.get("/api/preferences")
def read_preferences():
    return get_preferences()


@app.put("/api/preferences")
def save_preferences(payload: PreferencesIn):
    values = payload.model_dump()
    with db() as conn:
        conn.execute(
            """UPDATE preferences SET display_name=?,day_start=?,day_end=?,break_minutes=?,default_buffer_minutes=?,planning_style=?,timezone=?,voice_input=?,voice_output=?,language=?,onboarding_complete=? WHERE id=1""",
            (
                values["display_name"],
                values["day_start"],
                values["day_end"],
                values["break_minutes"],
                values["default_buffer_minutes"],
                values["planning_style"],
                values["timezone"],
                int(values["voice_input"]),
                int(values["voice_output"]),
                values["language"],
                int(values["onboarding_complete"]),
            ),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uid(),
                "preferences_updated",
                "Planning preferences saved",
                json.dumps(
                    {
                        "planning_style": values["planning_style"],
                        "break_minutes": values["break_minutes"],
                        "default_buffer_minutes": values["default_buffer_minutes"],
                    }
                ),
                utcnow(),
            ),
        )
        conn.execute(
            "UPDATE plans SET status='outdated' WHERE status IN ('applied','restored')"
        )
    return get_preferences()


@app.get("/api/briefing")
def get_briefing():
    """Return a live, explainable briefing for the dashboard and voice assistant."""
    return build_briefing(
        day=current_day(),
        tasks=get_tasks(),
        projects=get_projects(),
        preferences=get_preferences(),
    )


@app.get("/api/tasks")
def list_tasks(include_archived: bool = False):
    return get_tasks(include_archived)


@app.post("/api/tasks")
def create_task(payload: TaskCreate):
    stamp = utcnow()
    task_id = uid()
    values = payload.model_dump()
    with db() as conn:
        conn.execute(
            """INSERT INTO tasks
            (id,title,description,duration_minutes,actual_minutes,deadline,earliest_start,fixed_start,priority,flexibility,splittable,tags_json,status,created_at,updated_at,project_id)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                task_id,
                values["title"],
                values["description"],
                values["duration_minutes"],
                None,
                values["deadline"],
                values["earliest_start"],
                values["fixed_start"],
                values["priority"],
                values["flexibility"],
                int(values["splittable"]),
                json.dumps(values["tags"]),
                "open",
                stamp,
                stamp,
                values["project_id"],
            ),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uid(),
                "task_created",
                values["title"],
                json.dumps({"task_id": task_id}),
                stamp,
            ),
        )
        conn.execute(
            "UPDATE plans SET status='outdated' WHERE status IN ('applied','restored')"
        )
    return next(t for t in get_tasks(True) if t["id"] == task_id)


@app.patch("/api/tasks/{task_id}")
def update_task(task_id: str, payload: TaskPatch):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "No fields supplied")
    if "tags" in fields:
        fields["tags_json"] = json.dumps(fields.pop("tags"))
    fields["updated_at"] = utcnow()
    with db() as conn:
        if not conn.execute("SELECT id FROM tasks WHERE id=?", (task_id,)).fetchone():
            raise HTTPException(404, "Task not found")
        conn.execute(
            f"UPDATE tasks SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            (*fields.values(), task_id),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (uid(), "task_updated", task_id, json.dumps(fields), utcnow()),
        )
        conn.execute(
            "UPDATE plans SET status='outdated' WHERE status IN ('applied','restored')"
        )
    return next(t for t in get_tasks(True) if t["id"] == task_id)


@app.get("/api/projects")
def list_projects(include_archived: bool = False):
    return get_projects(include_archived)


@app.post("/api/projects")
def create_project(payload: ProjectCreate):
    values = payload.model_dump()
    project_id = uid()
    stamp = utcnow()
    with db() as conn:
        conn.execute(
            "INSERT INTO projects VALUES (?,?,?,?,?,?,?,?)",
            (
                project_id,
                values["name"],
                values["description"],
                values["color"],
                values["target_date"],
                "active",
                stamp,
                stamp,
            ),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uid(),
                "project_created",
                values["name"],
                json.dumps({"project_id": project_id}),
                stamp,
            ),
        )
    return next(
        project for project in get_projects(True) if project["id"] == project_id
    )


@app.patch("/api/projects/{project_id}")
def update_project(project_id: str, payload: ProjectPatch):
    fields = payload.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(400, "No fields supplied")
    fields["updated_at"] = utcnow()
    with db() as conn:
        if not conn.execute(
            "SELECT id FROM projects WHERE id=?", (project_id,)
        ).fetchone():
            raise HTTPException(404, "Project not found")
        conn.execute(
            f"UPDATE projects SET {', '.join(f'{key}=?' for key in fields)} WHERE id=?",
            (*fields.values(), project_id),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (uid(), "project_updated", project_id, json.dumps(fields), utcnow()),
        )
    return next(
        project for project in get_projects(True) if project["id"] == project_id
    )


@app.get("/api/day")
def get_day(day: str | None = None):
    chosen = None
    if day:
        try:
            chosen = date.fromisoformat(day)
        except ValueError as error:
            raise HTTPException(400, "Use an ISO date, for example 2026-10-21") from error
    return current_day(chosen)


@app.post("/api/day/generate")
def generate_day():
    return schedule_tasks(get_tasks())


@app.get("/api/risks")
def get_risks():
    day = current_day()
    return {
        "status": day["status"],
        "risks": day["risks"],
        "evidence": {
            "scheduled_minutes": day["metrics"]["scheduled_minutes"],
            "free_buffer_minutes": day["metrics"]["free_buffer_minutes"],
        },
    }


@app.post("/api/recovery/options")
def recovery_options(payload: DisruptionIn):
    return generate_recovery(payload)


@app.post("/api/recovery/{proposal_id}/approve")
def approve_recovery(proposal_id: str):
    result = apply_proposal(proposal_id)
    action_id = assistant_engine().record_external(
        capability="schedule.apply",
        arguments={"proposal_id": proposal_id},
        before={"blocks": result["before"].get("blocks", []), "tasks": result["task_restores"]},
        after={"changes": result["changes"]},
        inverse={"op": "plan.revert", "plan_id": result["plan_id"], "task_restores": result["task_restores"]},
        summary=f"Applied recovery: {result['title']}",
    )
    return {
        "status": "applied",
        "plan_id": result["plan_id"],
        "proposal_id": proposal_id,
        "action_id": action_id,
        "changes": result["changes"],
        "day": result["day"],
    }


@app.get("/api/recovery/history")
def plan_history():
    with db() as conn:
        rows = conn.execute(
            "SELECT * FROM plans ORDER BY created_at DESC LIMIT 30"
        ).fetchall()
    return [
        {
            "id": r["id"],
            "version": r["version"],
            "status": r["status"],
            "reason": r["reason"],
            "selected_proposal_id": r["selected_proposal_id"],
            "created_at": r["created_at"],
            "before": json.loads(r["before_json"]),
            "after": json.loads(r["after_json"]),
        }
        for r in rows
    ]


@app.post("/api/recovery/{plan_id}/restore")
def restore_plan(plan_id: str):
    with db() as conn:
        source = conn.execute("SELECT * FROM plans WHERE id=?", (plan_id,)).fetchone()
        if not source:
            raise HTTPException(404, "Plan not found")
        version = conn.execute(
            "SELECT COALESCE(MAX(version),1)+1 FROM plans"
        ).fetchone()[0]
        restored_id = uid()
        before = json.dumps(current_day())
        conn.execute(
            "INSERT INTO plans VALUES (?,?,?,?,?,?,?,?)",
            (
                restored_id,
                version,
                "restored",
                f"Restored plan v{source['version']}",
                before,
                source["before_json"],
                None,
                utcnow(),
            ),
        )
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uid(),
                "plan_restored",
                restored_id,
                json.dumps({"source_plan_id": plan_id}),
                utcnow(),
            ),
        )
    return {
        "status": "restored",
        "plan_id": restored_id,
        "day": json.loads(source["before_json"]),
    }


@app.get("/api/activity")
def list_activity(limit: int = 20):
    limit = max(1, min(limit, 50))
    with db() as conn:
        rows = conn.execute(
            """SELECT id, event_type, detail, metadata_json, created_at
            FROM events ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    return [
        {
            "id": row["id"],
            "type": row["event_type"],
            "detail": row["detail"],
            "metadata": json.loads(row["metadata_json"] or "{}"),
            "created_at": row["created_at"],
        }
        for row in rows
    ]


@app.get("/api/patterns")
def patterns(days: int = 7):
    days = max(1, min(days, 30))
    tasks = get_tasks(True)
    completed = [
        t
        for t in tasks
        if t["status"] == "done" and t.get("actual_minutes") is not None
    ]
    delta = (
        round(
            sum(t["actual_minutes"] - t["duration_minutes"] for t in completed)
            / len(completed)
        )
        if completed
        else 0
    )
    with db() as conn:
        recovered = conn.execute(
            "SELECT COUNT(*) FROM plans WHERE status IN ('applied','restored')"
        ).fetchone()[0]
    done_count = sum(1 for task in tasks if task["status"] == "done")
    active_count = sum(1 for task in tasks if task["status"] == "open")
    total = max(1, done_count + active_count)
    completion_rate = round(done_count / total * 100)
    scheduled = sum(
        task["duration_minutes"] for task in tasks if task["status"] != "archived"
    )
    focus_score = max(
        35, min(96, 82 - max(delta, 0) - active_count * 2 + recovered * 3)
    )
    project_data = get_projects()
    focus_minutes = sum(
        task["duration_minutes"]
        for task in tasks
        if task["status"] != "archived" and task["flexibility"] == "flexible"
    )
    fixed_minutes = sum(
        task["duration_minutes"]
        for task in tasks
        if task["status"] != "archived" and task["flexibility"] == "fixed"
    )
    admin_minutes = max(0, scheduled - focus_minutes - fixed_minutes)
    labels: list[str] = []
    activity: list[int] = []
    time_trend: list[float] = []
    focus_trend: list[int] = []
    today = planning_day()
    for offset in range(days - 1, -1, -1):
        point = today - timedelta(days=offset)
        labels.append(point.strftime("%a"))
        completed_minutes = sum(
            task.get("actual_minutes") or 0
            for task in completed
            if (task.get("updated_at") or "").startswith(point.isoformat())
        )
        time_trend.append(round(completed_minutes / 60, 1))
        activity.append(min(100, completed_minutes))
        focus_trend.append(focus_score if point == today else 0)
    groups: dict[str, list[int]] = {}
    for task in completed:
        name = (task.get("tags") or ["General"])[0].title()
        groups.setdefault(name, []).append(
            task["actual_minutes"] - task["duration_minutes"]
        )
    categories = [
        {"name": name, "delta": round(sum(values) / len(values))}
        for name, values in groups.items()
    ]
    return {
        "sample_size": len(completed),
        "average_estimate_delta": delta,
        "recovered_plans": recovered,
        "insufficient_data": len(completed) < 3,
        "completion_rate": completion_rate,
        "focus_score": focus_score,
        "balance_score": max(
            40, min(96, 100 - abs(focus_minutes - fixed_minutes) // 6)
        ),
        "scheduled_hours": round(scheduled / 60, 1),
        "activity": activity,
        "week_labels": labels,
        "time_trend": time_trend,
        "focus_trend": focus_trend,
        "range_days": days,
        "history_note": "Charts count recorded completion time. Days without completed tasks stay at zero.",
        "time_breakdown": [
            {"name": "Focus", "minutes": focus_minutes, "color": "#e4794c"},
            {"name": "Meetings", "minutes": fixed_minutes, "color": "#657c9a"},
            {"name": "Admin", "minutes": admin_minutes, "color": "#71886b"},
        ],
        "goals": [
            {
                "name": p["name"],
                "progress": p["progress"],
                "target_date": p["target_date"],
            }
            for p in project_data
        ],
        "categories": categories,
    }


@app.get("/api/opportunities")
def opportunities():
    day = current_day()
    tasks = get_tasks()
    first_risk = day["risks"][0] if day["risks"] else None
    flexible = next(
        (
            task
            for task in tasks
            if task["status"] == "open" and task["flexibility"] == "flexible"
        ),
        None,
    )
    suggestions = []
    if first_risk:
        suggestions.append(
            {
                "id": "protect-deadline",
                "kind": "alert",
                "title": f"Protect {first_risk['task']}",
                "description": first_risk["reason"],
                "confidence": day["metrics"]["confidence"],
                "evidence": f"{first_risk['slack_minutes']} minutes calculated slack",
                "action": "Open recovery workspace",
            }
        )
    else:
        suggestions.append(
            {
                "id": "plan-healthy",
                "kind": "prediction",
                "title": "Your day can absorb a small delay",
                "description": f"The current schedule has {day['metrics']['free_buffer_minutes']} minutes of unused capacity after protected buffers.",
                "confidence": day["metrics"]["confidence"],
                "evidence": "Validated against working hours and fixed commitments",
                "action": "Keep this plan",
            }
        )
    if flexible:
        suggestions.append(
            {
                "id": "focus-window",
                "kind": "suggestion",
                "title": f"Start with {flexible['title']}",
                "description": "It is flexible enough to move, but completing it early creates recovery room later in the day.",
                "confidence": max(50, day["metrics"]["confidence"] - 8),
                "evidence": f"{flexible['duration_minutes']} minute flexible block",
                "action": "View on calendar",
            }
        )
    suggestions.append(
        {
            "id": "buffer-rule",
            "kind": "automation",
            "title": "Keep a protected buffer after fixed events",
            "description": "Plan B has inserted your preferred recovery buffer so overruns do not silently cascade.",
            "confidence": 100,
            "evidence": f"{get_preferences()['default_buffer_minutes']} minute buffer rule",
            "action": "Review preference",
        }
    )
    return {"items": suggestions, "generated_at": utcnow(), "learned_from": len(tasks)}


@app.post("/api/opportunities/{opportunity_id}/respond")
def respond_to_opportunity(opportunity_id: str, payload: OpportunityResponse):
    with db() as conn:
        conn.execute(
            "INSERT INTO events VALUES (?,?,?,?,?)",
            (
                uid(),
                "opportunity_response",
                opportunity_id,
                json.dumps({"accepted": payload.accepted}),
                utcnow(),
            ),
        )
    return {
        "id": opportunity_id,
        "status": "accepted" if payload.accepted else "declined",
        "recorded": True,
    }


@app.get("/api/provider/status")
def get_provider_status():
    return provider_status()


@app.get("/api/provider/models")
def provider_models():
    if not settings.provider_configured:
        return {
            "items": CURATED_MODELS,
            "source": "curated",
            "active": get_selected_model(),
        }
    try:
        items = provider_client().list_models()
    except ProviderError as error:
        raise HTTPException(502, str(error)) from error
    return {"items": items, "source": "nvidia", "active": get_selected_model()}


@app.put("/api/provider/model")
def select_provider_model(payload: ProviderModelIn):
    if not settings.provider_configured:
        raise HTTPException(409, "Provider configuration is incomplete")
    try:
        available = provider_client().list_models()
        if payload.model not in available:
            raise HTTPException(
                400, "That model is not available for this NVIDIA account"
            )
        reply = provider_client().chat(
            "Reply with exactly: Plan B provider ready", model=payload.model
        )
    except ProviderError as error:
        raise HTTPException(502, str(error)) from error
    with db() as conn:
        conn.execute(
            "INSERT INTO app_settings(key,value,updated_at) VALUES (?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            ("active_llm_model", payload.model, utcnow()),
        )
    return {"ok": True, "model": payload.model, "reply": reply[:160]}


@app.post("/api/provider/test")
def test_provider():
    status = provider_status()
    if not status["configured"]:
        raise HTTPException(409, "Provider configuration is incomplete")
    reply = call_provider("Reply with exactly: Plan B provider ready")
    if not reply:
        raise HTTPException(502, "NVIDIA provider did not return a valid response")
    return {
        "ok": True,
        "provider": status["provider"],
        "model": status["model"],
        "reply": reply[:160],
    }


class Services:
    """The product API the assistant engine is allowed to use."""

    today = staticmethod(planning_day)
    now = staticmethod(planning_now)
    tasks = staticmethod(get_tasks)
    projects = staticmethod(get_projects)
    preferences = staticmethod(get_preferences)
    apply_proposal = staticmethod(apply_proposal)
    revert_plan = staticmethod(revert_applied_plan)

    @staticmethod
    def patterns(days: int = 7) -> dict[str, Any]:
        return patterns(days)

    @staticmethod
    def day(on: date | None = None) -> dict[str, Any]:
        return current_day(on)

    @staticmethod
    def create_task(values: dict[str, Any]) -> dict[str, Any]:
        return create_task(TaskCreate(**values))

    @staticmethod
    def patch_task(task_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return update_task(task_id, TaskPatch(**fields))

    @staticmethod
    def create_project(values: dict[str, Any]) -> dict[str, Any]:
        return create_project(ProjectCreate(**values))

    @staticmethod
    def patch_project(project_id: str, fields: dict[str, Any]) -> dict[str, Any]:
        return update_project(project_id, ProjectPatch(**fields))

    @staticmethod
    def save_preferences(values: dict[str, Any]) -> dict[str, Any]:
        return save_preferences(PreferencesIn(**{k: v for k, v in values.items() if k in PreferencesIn.model_fields}))

    @staticmethod
    def recover(*, minutes: int, reason: str, target_task_id: str | None, protect_ids: list[str],
                shorten: dict[str, int], defer_ids: list[str]) -> dict[str, Any]:
        return generate_recovery(DisruptionIn(
            disruption_minutes=minutes, reason=reason[:500], target_task_id=target_task_id,
            protect_task_ids=protect_ids, shorten=shorten, defer_task_ids=defer_ids,
        ))


def assistant_engine() -> AssistantEngine:
    return AssistantEngine(
        db=db,
        services=Services,
        structured_provider=call_provider_structured,
        model_enabled=planner_enabled,
    )


@app.get("/api/assistant/history")
def assistant_history(session_id: str = "default", limit: int = 80):
    return assistant_engine().store.history(session_id, limit)


@app.get("/api/assistant/capabilities")
def assistant_capabilities():
    return {"capabilities": assistant_engine().registry.catalog()}


@app.post("/api/assistant")
def assistant(payload: AssistantIn):
    if not (payload.message or payload.utterance):
        raise HTTPException(422, "message or utterance is required")
    return assistant_engine().turn(payload.model_dump())


@app.get("/api/actions")
def list_actions(limit: int = 20):
    return {"items": assistant_engine().ledger.recent(min(100, max(1, limit)))}


@app.post("/api/actions/undo")
def undo_latest_action():
    return assistant_engine().undo(None)


@app.post("/api/actions/{action_id}/undo")
def undo_action(action_id: str):
    engine = assistant_engine()
    if not engine.ledger.get(action_id):
        raise HTTPException(404, "Action not found")
    return engine.undo(action_id)


DEMO_TASKS = [
    ("Morning lectures", "Seminar block", 180, None, "09:30", "medium", "fixed", ["study"]),
    ("Team meeting", "Weekly product sync", 60, None, "13:30", "high", "fixed", ["work"]),
    ("Review lecture notes", "Before the 4:30 tutorial", 30, "16:30", None, "medium", "flexible", ["study"]),
    ("Report review", "Read and comment on the quarterly report", 60, "17:45", None, "medium", "flexible", ["work"]),
    ("Finish the pitch", "Final pitch deck for the judges", 60, "18:00", None, "high", "flexible", ["work"]),
    ("Inbox cleanup", "Clear the backlog", 30, None, None, "low", "flexible", ["admin"]),
]
DEMO_PREFERENCES = {"day_start": "09:00", "day_end": "21:00", "break_minutes": 0,
                    "default_buffer_minutes": 10, "planning_style": "balanced"}
DEMO_CLOCK = "13:30"


@app.get("/api/demo")
def demo_status():
    return {"active": bool(get_setting("demo_clock")), "clock": get_setting("demo_clock")}


@app.post("/api/demo")
def start_demo():
    """Seed the judge scenario: a 45 minute overrun puts the 6 PM pitch at risk."""
    if get_setting("demo_clock"):
        return demo_status() | {"tasks": get_tasks()}
    today = planning_day().isoformat()
    previous_open = [t["id"] for t in get_tasks() if t["status"] == "open"]
    previous_prefs = get_preferences()
    created = []
    with db() as conn:
        stamp = utcnow()
        for task_id in previous_open:
            conn.execute("UPDATE tasks SET status='archived', updated_at=? WHERE id=?", (stamp, task_id))
        for title, description, minutes, deadline, fixed, priority, flexibility, tags in DEMO_TASKS:
            task_id = uid()
            created.append(task_id)
            conn.execute(
                """INSERT INTO tasks
                (id,title,description,duration_minutes,actual_minutes,deadline,earliest_start,fixed_start,priority,flexibility,splittable,tags_json,status,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (task_id, title, description, minutes, None,
                 f"{today}T{deadline}" if deadline else None, None,
                 f"{today}T{fixed}" if fixed else None, priority, flexibility, 1, json.dumps(tags + ["demo"]),
                 "open", stamp, stamp),
            )
        conn.execute("UPDATE plans SET status='outdated' WHERE status IN ('applied','restored')")
        conn.execute("INSERT INTO events VALUES (?,?,?,?,?)",
                     (uid(), "demo_started", "Judge demo scenario loaded", "{}", stamp))
    save_preferences(PreferencesIn(**{**previous_prefs, **DEMO_PREFERENCES}))
    set_setting("demo_backup", json.dumps({"archived": previous_open, "created": created, "preferences": previous_prefs}))
    set_setting("demo_clock", DEMO_CLOCK)
    return demo_status() | {"tasks": get_tasks()}


@app.delete("/api/demo")
def stop_demo():
    backup = json.loads(get_setting("demo_backup") or "{}")
    with db() as conn:
        stamp = utcnow()
        for task_id in backup.get("created", []):
            conn.execute("UPDATE tasks SET status='archived', updated_at=? WHERE id=?", (stamp, task_id))
        for task_id in backup.get("archived", []):
            conn.execute("UPDATE tasks SET status='open', updated_at=? WHERE id=?", (stamp, task_id))
        conn.execute("UPDATE plans SET status='outdated' WHERE status IN ('applied','restored')")
    if backup.get("preferences"):
        save_preferences(PreferencesIn(**backup["preferences"]))
    set_setting("demo_clock", None)
    set_setting("demo_backup", None)
    return demo_status()


MCP_TOOLS = [
    {
        "name": "get_day_schedule",
        "description": "Read the current schedule, task states and constraints",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "create_task",
        "description": "Create a task without silently scheduling it",
        "inputSchema": TaskCreate.model_json_schema(),
    },
    {
        "name": "update_task",
        "description": "Update an owned task and trigger re-evaluation",
        "inputSchema": {
            "type": "object",
            "required": ["task_id"],
            "properties": {
                "task_id": {"type": "string"},
                "changes": {"type": "object"},
            },
        },
    },
    {
        "name": "generate_daily_plan",
        "description": "Generate a candidate plan",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "check_deadline_risks",
        "description": "Calculate deadline and capacity risks",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "find_affected_tasks",
        "description": "Calculate the downstream impact of a disruption",
        "inputSchema": {
            "type": "object",
            "required": ["disruption_minutes"],
            "properties": {
                "disruption_minutes": {"type": "integer"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "generate_recovery_options",
        "description": "Generate validated recovery candidates",
        "inputSchema": {
            "type": "object",
            "required": ["disruption_minutes"],
            "properties": {
                "disruption_minutes": {"type": "integer"},
                "reason": {"type": "string"},
            },
        },
    },
    {
        "name": "validate_schedule",
        "description": "Validate durations, deadlines, fixed events and hours",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "apply_approved_plan",
        "description": "Apply a feasible proposal after explicit approval",
        "inputSchema": {
            "type": "object",
            "required": ["proposal_id"],
            "properties": {"proposal_id": {"type": "string"}},
        },
    },
    {
        "name": "get_plan_history",
        "description": "Read plan versions and recovery history",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


@app.get("/api/mcp/tools")
def mcp_tools():
    return {
        "protocol": "2025-03-26",
        "transport": "streamable-http",
        "tools": MCP_TOOLS,
    }


@app.post("/api/mcp/call")
def mcp_call(payload: dict[str, Any]):
    name = payload.get("name")
    args = payload.get("arguments", {})
    result: Any
    if name == "get_day_schedule":
        result = current_day()
    elif name == "create_task":
        result = create_task(TaskCreate(**args))
    elif name == "update_task":
        result = update_task(args["task_id"], TaskPatch(**args.get("changes", {})))
    elif name == "generate_daily_plan":
        result = schedule_tasks(get_tasks())
    elif name == "check_deadline_risks":
        result = get_risks()
    elif name in {"find_affected_tasks", "generate_recovery_options"}:
        result = generate_recovery(
            DisruptionIn(
                disruption_minutes=args.get("disruption_minutes", 60),
                reason=args.get("reason", "MCP disruption"),
            )
        )
    elif name == "validate_schedule":
        result = validate_candidate(schedule_tasks(get_tasks()))
    elif name == "apply_approved_plan":
        result = approve_recovery(args["proposal_id"])
    elif name == "get_plan_history":
        result = plan_history()
    else:
        raise HTTPException(404, "Unknown or unauthorized MCP tool")
    return {"content": [{"type": "text", "text": json.dumps(result)}], "isError": False}
