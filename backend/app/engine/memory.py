"""Session memory.

- turn memory: assistant_turns (what was said)
- working memory: assistant_sessions.state_json (pending plan, active recovery, focused entities)
- episodic memory: assistant_episodes (one line per finished goal) plus the action ledger
- semantic memory: user preferences, read through the services layer
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_episodes (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL, summary TEXT NOT NULL,
  created_at TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class SessionStore:
    def __init__(self, db: Callable[[], Any]):
        self.db = db

    def load(self, session_id: str) -> dict[str, Any]:
        with self.db() as conn:
            row = conn.execute(
                "SELECT state_json FROM assistant_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return json.loads(row[0]) if row else {}

    def last_response(self, session_id: str) -> dict[str, Any] | None:
        with self.db() as conn:
            row = conn.execute(
                "SELECT last_response_json FROM assistant_sessions WHERE id=?", (session_id,)
            ).fetchone()
        return json.loads(row[0]) if row and row[0] not in (None, "{}") else None

    def cached(self, session_id: str, key: str | None) -> dict[str, Any] | None:
        if not key:
            return None
        with self.db() as conn:
            row = conn.execute(
                "SELECT response_json FROM assistant_idempotency WHERE key=? AND session_id=?",
                (key, session_id),
            ).fetchone()
        return json.loads(row[0]) if row else None

    def recent_turns(self, session_id: str, limit: int = 8) -> list[dict[str, str]]:
        with self.db() as conn:
            rows = conn.execute(
                "SELECT utterance,response_json FROM assistant_turns WHERE session_id=? "
                "ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [
            {"user": row[0], "assistant": json.loads(row[1]).get("say", "")}
            for row in reversed(rows)
        ]

    def save(self, session_id: str, state: dict[str, Any], utterance: str,
             response: dict[str, Any], idempotency_key: str | None) -> None:
        stamp = _now()
        with self.db() as conn:
            conn.execute(
                "INSERT INTO assistant_sessions(id,state_json,last_response_json,updated_at) VALUES(?,?,?,?) "
                "ON CONFLICT(id) DO UPDATE SET state_json=excluded.state_json,"
                "last_response_json=excluded.last_response_json,updated_at=excluded.updated_at",
                (session_id, json.dumps(state, default=str), json.dumps(response, default=str), stamp),
            )
            conn.execute(
                "INSERT INTO assistant_turns(id,session_id,utterance,response_json,created_at) VALUES(?,?,?,?,?)",
                (str(uuid.uuid4()), session_id, utterance, json.dumps(response, default=str), stamp),
            )
            if idempotency_key:
                conn.execute(
                    "INSERT OR REPLACE INTO assistant_idempotency(key,session_id,response_json,created_at) VALUES(?,?,?,?)",
                    (idempotency_key, session_id, json.dumps(response, default=str), stamp),
                )

    def history(self, session_id: str, limit: int = 80) -> dict[str, Any]:
        safe_limit = min(200, max(1, limit))
        with self.db() as conn:
            rows = conn.execute(
                "SELECT id,utterance,response_json,created_at FROM assistant_turns "
                "WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT ?",
                (session_id, safe_limit),
            ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in reversed(rows):
            response = json.loads(row[2])
            messages.extend([
                {"id": f"{row[0]}-user", "role": "user", "text": row[1], "status": "Sent", "created_at": row[3]},
                {"id": f"{row[0]}-assistant", "role": "assistant", "text": response.get("say", ""),
                 "meta": {"understood": response.get("understood"), "planner": response.get("planner"),
                          "capabilities": [t["tool"] for t in response.get("tools", [])]},
                 "tools": response.get("tools", []), "steps": response.get("steps", []),
                 "evidence": response.get("evidence", []), "created_at": row[3]},
            ])
        return {"session_id": session_id, "messages": messages}

    def add_episode(self, session_id: str, summary: str) -> None:
        with self.db() as conn:
            conn.execute(
                "INSERT INTO assistant_episodes(id,session_id,summary,created_at) VALUES(?,?,?,?)",
                (str(uuid.uuid4()), session_id, summary, _now()),
            )

    def episodes(self, session_id: str, limit: int = 5) -> list[str]:
        with self.db() as conn:
            rows = conn.execute(
                "SELECT summary FROM assistant_episodes WHERE session_id=? ORDER BY seq DESC LIMIT ?",
                (session_id, limit),
            ).fetchall()
        return [row[0] for row in reversed(rows)]
