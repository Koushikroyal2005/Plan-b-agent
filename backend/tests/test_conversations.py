"""Transcript-driven evaluation of the assistant engine against the seeded judge scenario."""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main
from app.providers import CircuitBreaker, ProviderError

CORPUS = json.loads((Path(__file__).parent / "evals" / "conversations.json").read_text())


@pytest.fixture()
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "planb-eval.sqlite3")
    monkeypatch.setattr(main, "planner_enabled", lambda: False)
    main.init_db()
    with TestClient(main.app) as test_client:
        assert test_client.post("/api/demo").json()["active"] is True
        yield test_client


def say(client: TestClient, text: str, session: str) -> dict:
    response = client.post("/api/assistant", json={"message": text, "session_id": session})
    assert response.status_code == 200, response.text
    return response.json()


def task(client: TestClient, title: str) -> dict:
    tasks = client.get("/api/tasks?include_archived=true").json()
    return next(t for t in reversed(tasks) if t["title"].lower() == title.lower())


def matches(actual, expected) -> bool:
    if isinstance(expected, str) and expected.startswith("suffix:"):
        return isinstance(actual, str) and actual.endswith(expected[7:])
    return actual == expected


@pytest.mark.parametrize("case", CORPUS, ids=[c["name"] for c in CORPUS])
def test_conversation_corpus(demo: TestClient, case: dict):
    session = f"eval-{case['name']}"
    for turn in case["turns"]:
        body = say(demo, turn["say"], session)
        context = f"{case['name']} :: {turn['say']} -> {body['say']}"
        if "capabilities" in turn:
            assert [t["tool"] for t in body["tools"]] == turn["capabilities"], context
        if "state" in turn:
            assert body["state"] == turn["state"], context
        if "contains" in turn:
            assert turn["contains"].lower() in body["say"].lower(), context
        if "not_contains" in turn:
            assert turn["not_contains"].lower() not in body["say"].lower(), context
        assert body["metrics"]["total_ms"] < 1500, context
    check = case.get("check", {})
    for title, fields in check.get("tasks", {}).items():
        current = task(demo, title)
        for field, expected in fields.items():
            assert matches(current[field], expected), (case["name"], title, field, current[field])
    for field, expected in check.get("prefs", {}).items():
        assert demo.get("/api/preferences").json()[field] == expected
    if "schedule_source" in check:
        assert demo.get("/api/day").json()["schedule_source"] == check["schedule_source"]


def test_corpus_is_large_enough():
    assert len(CORPUS) >= 100


def test_demo_story_restores_exact_schedule(demo: TestClient):
    original = demo.get("/api/day").json()["blocks"]
    session = "story"
    first = say(demo, "My meeting ran 45 minutes late and I still need to finish the pitch before 6", session)
    assert first["acknowledgement"].startswith("Got it")
    assert [c["label"] for c in first["choices"]][:2] == ["Apply option 1", "Apply option 2"]
    assert [s["label"] for s in first["steps"]][1] == "Reading today's calendar"
    say(demo, "Don't move lecture notes. Shorten the report review instead", session)
    applied = say(demo, "Apply it", session)
    assert applied["undo"]["action_id"]
    changed = demo.get("/api/day").json()
    assert changed["schedule_source"] == "approved_plan"
    pitch = next(b for b in changed["blocks"] if b["title"] == "Finish the pitch")
    assert pitch["end"] == "5:45 PM" and pitch["kind"] == "focus"
    lecture = next(b for b in changed["blocks"] if b["title"] == "Review lecture notes")
    assert lecture["minutes"] == 30
    say(demo, "Undo that", session)
    restored = demo.get("/api/day").json()["blocks"]
    assert [(b["title"], b["start"], b["end"]) for b in restored] == [(b["title"], b["start"], b["end"]) for b in original]


def test_ui_approval_is_recorded_and_undoable(demo: TestClient):
    recovery = demo.post("/api/recovery/options", json={"disruption_minutes": 45, "reason": "Overrun"}).json()
    option = next(o for o in recovery["options"] if o["feasible"])
    approved = demo.post(f"/api/recovery/{option['id']}/approve").json()
    assert approved["action_id"]
    actions = demo.get("/api/actions").json()["items"]
    assert actions[0]["capability"] == "schedule.apply" and actions[0]["requested_by"] == "ui"
    undone = demo.post(f"/api/actions/{approved['action_id']}/undo").json()
    assert "back to how it was" in undone["say"]
    assert demo.get("/api/actions").json()["items"][1]["status"] == "undone"
    assert demo.get("/api/day").json()["schedule_source"] == "live"


def test_ledger_records_before_after_and_inverse(demo: TestClient):
    session = "ledger"
    say(demo, "make the report review 45 minutes", session)
    say(demo, "yes", session)
    entry = demo.get("/api/actions").json()["items"][0]
    assert entry["capability"] == "tasks.update"
    assert entry["before"] == {"duration_minutes": 60}
    assert entry["after"] == {"duration_minutes": 45}
    assert entry["inverse"]["op"] == "task.patch"
    assert entry["validation"] == {"verified": True}
    assert entry["confirmed"] is True


def test_infeasible_recovery_never_applies(demo: TestClient):
    session = "infeasible"
    body = say(demo, "my meeting ran 6 hours late", session)
    assert "couldn't find a change" in body["say"]
    blocked = say(demo, "apply it", session)
    assert blocked["state"] == "failed"
    assert demo.get("/api/day").json()["schedule_source"] == "live"


def test_exit_demo_restores_workspace(demo: TestClient):
    assert demo.delete("/api/demo").json()["active"] is False
    titles = {t["title"] for t in demo.get("/api/tasks").json()}
    assert "Finish the pitch" not in titles and "Finish assignment" in titles


def test_capability_catalog_is_typed(demo: TestClient):
    catalog = demo.get("/api/assistant/capabilities").json()["capabilities"]
    names = {c["name"] for c in catalog}
    assert {"tasks.archive", "tasks.restore", "schedule.recover", "schedule.apply", "actions.undo"} <= names
    for item in catalog:
        assert item["input_schema"]["type"] == "object"
        assert item["mode"] in {"read", "write", "ui"}
        assert item["examples"]


def test_slow_provider_is_bounded_and_circuit_opens(demo: TestClient, monkeypatch: pytest.MonkeyPatch):
    calls = []

    class SlowProvider:
        def structured(self, system, prompt):
            calls.append(1)
            raise ProviderError("timed out")

    monkeypatch.setattr(main.settings.__class__, "provider_configured", property(lambda self: True))
    monkeypatch.setattr(main, "provider_client", lambda: SlowProvider())
    monkeypatch.setattr(main, "planner_breaker", CircuitBreaker(failure_threshold=2, cooldown_seconds=60))
    monkeypatch.setattr(main, "planner_enabled", lambda: not main.planner_breaker.is_open)
    for index in range(4):
        body = say(demo, "help me reason about the competing tradeoffs", f"slow-{index}")
        assert body["tools"] == []
        assert body["planner"] == "rules"
    assert len(calls) == 2
    assert main.provider_status()["planner"]["circuit"] == "open"


def test_universal_commands_skip_the_model(demo: TestClient, monkeypatch: pytest.MonkeyPatch):
    def never(system, prompt):
        raise AssertionError("model should not be called")

    monkeypatch.setattr(main, "planner_enabled", lambda: True)
    monkeypatch.setattr(main, "call_provider_structured", never)
    for text in ("undo that", "open calendar", "cancel", "yes"):
        say(demo, text, "fast-path")


def test_provider_timeout_defaults_to_five_seconds():
    assert main.settings.llm_timeout_seconds <= 6
    assert main.provider_client().timeout_seconds == main.settings.llm_timeout_seconds


def test_breaker_recovers_after_cooldown():
    breaker = CircuitBreaker(failure_threshold=1, cooldown_seconds=0.05)
    breaker.failure()
    assert breaker.is_open
    time.sleep(0.06)
    assert not breaker.is_open


def test_idempotent_turns_do_not_double_write(demo: TestClient):
    payload = {"message": "mark inbox cleanup done", "session_id": "idem", "idempotency_key": "same-key"}
    first = demo.post("/api/assistant", json=payload).json()
    second = demo.post("/api/assistant", json=payload).json()
    assert first["turn_id"] == second["turn_id"]
    assert len([a for a in demo.get("/api/actions").json()["items"] if a["capability"] == "tasks.complete"]) == 1


def test_response_hides_internal_debug_fields(demo: TestClient):
    body = say(demo, "what's at risk", "debug")
    text = json.dumps(body)
    for leaked in ("max_steps", "bounded orchestrator", "allowlisted", "converse"):
        assert leaked not in text
