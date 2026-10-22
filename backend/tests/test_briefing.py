from app.briefing import build_briefing


def test_briefing_prioritizes_live_work_and_explains_capacity():
    result = build_briefing(
        day={
            "capacity_minutes": 120,
            "blocks": [
                {"title": "Deep work", "kind": "focus", "duration_minutes": 90, "start": "2026-10-22T09:00:00"},
                {"title": "Review", "kind": "task", "duration_minutes": 45, "start": "2026-10-22T11:00:00"},
            ],
            "risks": [],
        },
        tasks=[{"title": "Ship release", "priority": "high", "status": "todo"}],
        projects=[{"title": "Launch", "status": "active"}],
        preferences={"daily_capacity_minutes": 480},
    )

    assert result["next_action"].startswith("Deep work")
    assert result["metrics"]["capacity_utilization"] == 112
    assert result["suggestions"][0]["id"] == "rebalance-day"


def test_briefing_recommends_planning_when_open_tasks_are_unscheduled():
    result = build_briefing(
        day={"blocks": [], "risks": []},
        tasks=[{"title": "Prepare demo", "priority": "urgent", "status": "todo"}],
        projects=[],
        preferences={},
    )

    assert result["headline"] == "Let’s shape today"
    assert result["next_action"] == "Prepare demo"
    assert result["suggestions"][0]["id"] == "build-plan"


def test_briefing_surfaces_plan_risks_before_generic_advice():
    result = build_briefing(
        day={"blocks": [], "risks": [{"message": "Two deadlines compete for the same hour."}]},
        tasks=[],
        projects=[],
        preferences={},
    )

    assert result["headline"] == "Your day needs one decision"
    assert result["suggestions"][0]["priority"] == "high"
    assert "deadlines" in result["suggestions"][0]["detail"]
