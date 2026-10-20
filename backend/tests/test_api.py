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


def test_model_catalog_and_persistent_selection(client: TestClient):
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
