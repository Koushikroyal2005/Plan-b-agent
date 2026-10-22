"""Transactional action ledger: every write records before/after state and its inverse."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any, Callable

SCHEMA = """
CREATE TABLE IF NOT EXISTS assistant_actions (
  seq INTEGER PRIMARY KEY AUTOINCREMENT,
  id TEXT UNIQUE NOT NULL, session_id TEXT NOT NULL, requested_by TEXT NOT NULL,
  capability TEXT NOT NULL, arguments_json TEXT NOT NULL, before_json TEXT NOT NULL,
  after_json TEXT NOT NULL, validation_json TEXT NOT NULL, confirmed INTEGER NOT NULL,
  inverse_json TEXT, summary TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'applied',
  created_at TEXT NOT NULL, undone_at TEXT
);
"""


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class ActionLedger:
    def __init__(self, db: Callable[[], Any]):
        self.db = db

    def record(
        self,
        *,
        session_id: str,
        requested_by: str,
        capability: str,
        arguments: dict[str, Any],
        before: Any,
        after: Any,
        validation: dict[str, Any],
        confirmed: bool,
        inverse: dict[str, Any] | None,
        summary: str,
    ) -> str:
        action_id = str(uuid.uuid4())
        with self.db() as conn:
            conn.execute(
                """INSERT INTO assistant_actions
                (id,session_id,requested_by,capability,arguments_json,before_json,after_json,
                 validation_json,confirmed,inverse_json,summary,status,created_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,'applied',?)""",
                (
                    action_id, session_id, requested_by, capability,
                    json.dumps(arguments, default=str), json.dumps(before, default=str),
                    json.dumps(after, default=str), json.dumps(validation, default=str),
                    int(confirmed), json.dumps(inverse, default=str) if inverse else None,
                    summary, _now(),
                ),
            )
        return action_id

    @staticmethod
    def _row(row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "session_id": row["session_id"],
            "requested_by": row["requested_by"],
            "capability": row["capability"],
            "arguments": json.loads(row["arguments_json"]),
            "before": json.loads(row["before_json"]),
            "after": json.loads(row["after_json"]),
            "validation": json.loads(row["validation_json"]),
            "confirmed": bool(row["confirmed"]),
            "inverse": json.loads(row["inverse_json"]) if row["inverse_json"] else None,
            "summary": row["summary"],
            "status": row["status"],
            "created_at": row["created_at"],
            "undone_at": row["undone_at"],
            "reversible": bool(row["inverse_json"]) and row["status"] == "applied",
        }

    def get(self, action_id: str) -> dict[str, Any] | None:
        with self.db() as conn:
            row = conn.execute("SELECT * FROM assistant_actions WHERE id=?", (action_id,)).fetchone()
        return self._row(row) if row else None

    def latest_undoable(self) -> dict[str, Any] | None:
        with self.db() as conn:
            row = conn.execute(
                """SELECT * FROM assistant_actions
                WHERE status='applied' AND inverse_json IS NOT NULL
                ORDER BY seq DESC LIMIT 1"""
            ).fetchone()
        return self._row(row) if row else None

    def mark_undone(self, action_id: str) -> None:
        with self.db() as conn:
            conn.execute(
                "UPDATE assistant_actions SET status='undone', undone_at=? WHERE id=?",
                (_now(), action_id),
            )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        with self.db() as conn:
            rows = conn.execute(
                "SELECT * FROM assistant_actions ORDER BY seq DESC LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(row) for row in rows]
