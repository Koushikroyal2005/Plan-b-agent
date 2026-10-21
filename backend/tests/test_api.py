from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import main


class FakeProvider:
    def list_models(self):
        return ["openai/gpt-oss-20b", "meta/llama-3.3-70b-instruct"]

    def chat(self, message, *, model=None):
        return "Plan B provider ready"


@pytest.fixture()
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(main, "DB_PATH", tmp_path / "planb-test.sqlite3")
    monkeypatch.setattr(main, "provider_client", lambda: FakeProvider())
    main.init_db()
    with TestClient(main.app) as test_client:
        yield test_client


def test_workspace_read_endpoints(client: TestClient):
    for route in (
        "/api/health",
        "/api/preferences",
        "/api/tasks",
        "/api/projects",
        "/api/day",
        "/api/risks",
        "/api/recovery/history",
        "/api/patterns",
        "/api/opportunities",
        "/api/provider/status",
        "/api/mcp/tools",
    ):
        response = client.get(route)
        assert response.status_code == 200, (route, response.text)


def test_task_and_project_lifecycle(client: TestClient):
    project = client.post(
        "/api/projects",
        json={
            "name": "Hackathon",
            "description": "Ship Plan B",
            "color": "#657c9a",
        },
    )
    assert project.status_code == 200
    project_id = project.json()["id"]

    task = client.post(
        "/api/tasks",
        json={
            "title": "Polish pitch",
            "duration_minutes": 45,
            "priority": "high",
            "flexibility": "flexible",
            "project_id": project_id,
        },
    )
    assert task.status_code == 200
    task_id = task.json()["id"]

    completed = client.patch(
        f"/api/tasks/{task_id}",
        json={
            "status": "done",
            "actual_minutes": 40,
        },
    )
    assert completed.status_code == 200
    assert completed.json()["status"] == "done"


def test_recovery_requires_and_records_approval(client: TestClient):
    recovery = client.post(
        "/api/recovery/options",
        json={
            "disruption_minutes": 30,
            "reason": "Judge briefing overran",
        },
    )
    assert recovery.status_code == 200
    data = recovery.json()
    feasible = next(option for option in data["options"] if option["feasible"])

    approved = client.post(f"/api/recovery/{feasible['id']}/approve")
    assert approved.status_code == 200
    assert approved.json()["status"] == "applied"
    assert client.get("/api/recovery/history").json()[0]["status"] == "applied"


def test_agent_and_mcp_use_controlled_tools(client: TestClient):
    response = client.post("/api/assistant", json={"message": "I am 45 minutes late"})
    assert response.status_code == 200
    assert response.json()["recovery"]["disruption_minutes"] == 45
    assert any(item["tool"] == "validate_schedule" for item in response.json()["tools"])

    tool = client.post(
        "/api/mcp/call",
        json={
            "name": "check_deadline_risks",
            "arguments": {},
        },
    )
    assert tool.status_code == 200
    assert tool.json()["isError"] is False

    denied = client.post(
        "/api/mcp/call", json={"name": "delete_everything", "arguments": {}}
    )
    assert denied.status_code == 404


def test_assistant_navigates_with_typed_ui_command(client: TestClient):
    response = client.post(
        "/api/assistant",
        json={"utterance": "Move to my settings page", "session_id": "navigation-test", "channel": "voice"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["ui_commands"] == [{"type": "navigate", "target": "settings"}]
    assert body["requires_confirmation"] is False


def test_assistant_collects_task_slots_and_confirms_before_write(client: TestClient):
    session = "task-dialogue-test"
    first = client.post("/api/assistant", json={"message": "Create a task", "session_id": session})
    assert first.status_code == 200
    assert first.json()["state"] == "asking"
    assert first.json()["pending_action"]["intent"] == "task.create"

    second = client.post("/api/assistant", json={"message": "Prepare the demo", "session_id": session})
    assert second.json()["state"] == "asking"
    assert "How long" in second.json()["say"]

    third = client.post("/api/assistant", json={"message": "90 minutes tomorrow at 10 am", "session_id": session})
    assert third.json()["state"] == "confirming"
    assert third.json()["requires_confirmation"] is True
    assert not any(task["title"] == "Prepare the demo" for task in client.get("/api/tasks").json())

    final = client.post("/api/assistant", json={"message": "yes", "session_id": session})
    assert final.json()["state"] == "completed"
    assert any(item["tool"] == "create_task" for item in final.json()["tools"])
    assert any(task["title"] == "Prepare the demo" for task in client.get("/api/tasks").json())


def test_assistant_can_cancel_pending_write(client: TestClient):
    session = "cancel-test"
    client.post("/api/assistant", json={"message": "Create task called Dangerous duplicate for 20 minutes", "session_id": session})
    cancelled = client.post("/api/assistant", json={"message": "cancel", "session_id": session})
    assert cancelled.json()["state"] == "completed"
    assert "did not change" in cancelled.json()["say"]
    assert not any(task["title"] == "Dangerous duplicate" for task in client.get("/api/tasks").json())


def test_assistant_uses_structured_model_decision_not_phrase_matching(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setattr(
        main,
        "call_provider_structured",
        lambda system, prompt: {
            "intent": "navigate",
            "confidence": 0.97,
            "slots": {"target": "calendar"},
            "response": None,
            "reasoning_summary": "The user wants the calendar workspace",
        },
    )
    response = client.post(
        "/api/assistant",
        json={"message": "Beam me into the time grid", "session_id": "model-routing"},
    )
    assert response.status_code == 200
    assert response.json()["ui_commands"] == [{"type": "navigate", "target": "calendar"}]
    assert response.json()["agent"] == {
        "role": "planner",
        "intent": "navigate",
        "confidence": 0.97,
        "source": "model",
        "max_steps": 6,
    }


def test_assistant_risk_tool_handles_grounded_api_shape(client: TestClient):
    response = client.post(
        "/api/assistant", json={"message": "What is at risk?", "session_id": "risk-test"}
    )
    assert response.status_code == 200
    assert response.json()["tools"] == [
        {"tool": "check_deadline_risks", "status": "complete"}
    ]


def test_model_catalog_and_persistent_selection(client: TestClient, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        main.settings.__class__,
        "provider_configured",
        property(lambda self: True),
    )
    models = client.get("/api/provider/models")
    assert models.status_code == 200
    assert "openai/gpt-oss-20b" in models.json()["items"]

    changed = client.put(
        "/api/provider/model", json={"model": "meta/llama-3.3-70b-instruct"}
    )
    assert changed.status_code == 200
    assert changed.json()["model"] == "meta/llama-3.3-70b-instruct"
    assert main.get_selected_model() == "meta/llama-3.3-70b-instruct"

    unavailable = client.put("/api/provider/model", json={"model": "missing/model"})
    assert unavailable.status_code == 400


def test_schedule_uses_today_and_rebuilds_after_edits(client: TestClient):
    from datetime import date

    day = client.get("/api/day").json()
    assert day["date"] == date.today().isoformat()
    assert day["schedule_source"] == "live"
    assert day["plan_stale"] is False

    recovery = client.post(
        "/api/recovery/options",
        json={"disruption_minutes": 20, "reason": "Standup ran long"},
    )
    feasible = next(option for option in recovery.json()["options"] if option["feasible"])
    assert client.post(f"/api/recovery/{feasible['id']}/approve").status_code == 200
    approved = client.get("/api/day").json()
    assert approved["schedule_source"] == "approved_plan"

    task = next(item for item in client.get("/api/tasks").json() if item["title"] == "Finish assignment")
    changed = client.patch(
        f"/api/tasks/{task['id']}",
        json={"duration_minutes": 90},
    )
    assert changed.status_code == 200
    refreshed = client.get("/api/day").json()
    assert refreshed["plan_stale"] is True
    assert refreshed["schedule_source"] == "live"
    assert any(
        block["task_id"] == task["id"] and block["minutes"] == 90
        for block in refreshed["blocks"]
    )


def test_preferences_change_breaks_and_activity_is_real(client: TestClient):
    prefs = client.get("/api/preferences").json()
    prefs["break_minutes"] = 0
    assert client.put("/api/preferences", json=prefs).status_code == 200
    without_breaks = client.get("/api/day").json()
    assert all(block["kind"] != "break" for block in without_breaks["blocks"])

    prefs["break_minutes"] = 15
    prefs["planning_style"] = "realistic"
    assert client.put("/api/preferences", json=prefs).status_code == 200
    with_breaks = client.get("/api/day").json()
    assert any(block["kind"] == "break" for block in with_breaks["blocks"])
    assert with_breaks["metrics"]["applied_break_minutes"] == 15
    assert with_breaks["metrics"]["applied_buffer_minutes"] == prefs["default_buffer_minutes"] + 5

    project = client.get("/api/projects").json()[0]
    renamed = client.patch(
        f"/api/projects/{project['id']}",
        json={"name": "Renamed workspace"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Renamed workspace"
    archived = client.patch(
        f"/api/projects/{project['id']}",
        json={"status": "archived"},
    )
    assert archived.status_code == 200
    assert all(item["id"] != project["id"] for item in client.get("/api/projects").json())

    activity = client.get("/api/activity").json()
    assert any(item["type"] == "project_updated" for item in activity)
    assert any(item["type"] == "preferences_updated" for item in activity)

    patterns = client.get("/api/patterns?days=7").json()
    assert patterns["time_trend"] != [3.2, 4.1, 3.6, 5.4, 4.7, 2.8, 3.9]
    assert patterns["categories"] == []
    assert "recorded completion time" in patterns["history_note"]
    assert len(patterns["week_labels"]) == 7
