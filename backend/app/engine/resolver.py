"""Resolve spoken references ("the report review", "it", "id:...") to real tasks and projects."""

from __future__ import annotations

import re
from typing import Any

from .errors import Ambiguous, NotFound

STOPWORDS = {
    "the", "a", "an", "my", "our", "to", "for", "of", "on", "in", "and", "task", "tasks",
    "called", "named", "please", "instead", "today", "block", "session", "project", "one",
}
PRONOUNS = {"it", "that", "this", "that one", "this one", "the same one", "same one", "that task", "this task"}


def tokens(text: str) -> set[str]:
    words = re.findall(r"[a-z0-9]+", text.lower())
    result = set()
    for word in words:
        if word in STOPWORDS:
            continue
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        result.add(word)
    return result


def score(reference: str, title: str) -> float:
    ref, target = tokens(reference), tokens(title)
    if not ref or not target:
        return 0.0
    if " ".join(sorted(ref)) == " ".join(sorted(target)):
        return 1.0
    overlap = len(ref & target)
    return overlap / len(target) * 0.6 + overlap / len(ref) * 0.4


class Resolver:
    def __init__(self, tasks: list[dict[str, Any]], projects: list[dict[str, Any]], focus: dict[str, Any]):
        self.tasks = tasks
        self.projects = projects
        self.focus = focus

    def _pick(self, reference: str, items: list[dict[str, Any]], key: str, kind: str) -> dict[str, Any]:
        ref = (reference or "").strip()
        if ref.startswith("id:"):
            found = next((item for item in items if item["id"] == ref[3:]), None)
            if found:
                return found
            raise NotFound(f"That {kind} no longer exists.")
        if ref.lower().strip(" .") in PRONOUNS or not ref:
            focus_id = self.focus.get(kind)
            found = next((item for item in items if item["id"] == focus_id), None)
            if found:
                return found
            raise NotFound(f"I'm not sure which {kind} you mean. Say its name.")
        ranked = sorted(((score(ref, item[key]), item) for item in items), key=lambda pair: -pair[0])
        if not ranked or ranked[0][0] < 0.45:
            raise NotFound(f"I couldn't find a {kind} called \"{ref}\".")
        best_score, best = ranked[0]
        close = [item for value, item in ranked[1:4] if value >= 0.45 and value >= best_score * 0.85]
        if close and best_score < 1.0:
            raise Ambiguous(ref, kind, [best, *close])
        return best

    def task(self, reference: str, statuses: set[str] | None = None) -> dict[str, Any]:
        statuses = statuses or {"open"}
        return self._pick(reference, [t for t in self.tasks if t["status"] in statuses], "title", "task")

    def project(self, reference: str) -> dict[str, Any]:
        return self._pick(reference, [p for p in self.projects if p["status"] != "archived"], "name", "project")

    def mentions(self, text: str, statuses: set[str] | None = None) -> list[dict[str, Any]]:
        """Tasks clearly named inside free text, best match first."""
        statuses = statuses or {"open"}
        found = []
        for task in self.tasks:
            if task["status"] not in statuses:
                continue
            title = tokens(task["title"])
            if title and len(title & tokens(text)) / len(title) >= 0.6:
                found.append(task)
        return sorted(found, key=lambda t: -score(text, t["title"]))
