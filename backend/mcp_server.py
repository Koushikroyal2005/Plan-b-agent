"""Plan B MCP server using the official Python SDK.

Run separately with: python mcp_server.py
The default transport is Streamable HTTP on http://localhost:8011/mcp.
"""

import json
import os

os.environ.setdefault(
    "PLANB_DB", os.path.join(os.path.dirname(__file__), "planb.sqlite3")
)

from mcp.server.mcpserver import MCPServer

from main import (
    DisruptionIn,
    TaskCreate,
    TaskPatch,
    approve_recovery,
    create_task as api_create_task,
    current_day,
    generate_recovery,
    get_risks,
    get_tasks,
    init_db,
    plan_history,
    schedule_tasks,
    update_task as api_update_task,
    validate_candidate,
)

init_db()
mcp = MCPServer(
    "Plan B",
    instructions="A deterministic schedule recovery service. Read and validate before applying any plan.",
)


@mcp.tool()
def get_day_schedule() -> str:
    """Read the current schedule, task states, deadlines and free buffer."""
    return json.dumps(current_day())


@mcp.tool()
def create_task(
    title: str,
    duration_minutes: int,
    priority: str = "medium",
    flexibility: str = "flexible",
    deadline: str | None = None,
    splittable: bool = True,
) -> str:
    """Create a task. This does not silently commit a schedule change."""
    task = api_create_task(
        TaskCreate(
            title=title,
            duration_minutes=duration_minutes,
            priority=priority,
            flexibility=flexibility,
            deadline=deadline,
            splittable=splittable,
        )
    )
    return json.dumps(task)


@mcp.tool()
def update_task(task_id: str, changes: dict) -> str:
    """Update a task and trigger schedule re-evaluation."""
    return json.dumps(api_update_task(task_id, TaskPatch(**changes)))


@mcp.tool()
def generate_daily_plan() -> str:
    """Generate a candidate schedule from current constraints."""
    return json.dumps(schedule_tasks(get_tasks()))


@mcp.tool()
def check_deadline_risks() -> str:
    """Calculate deadline, buffer and daily-capacity risks."""
    return json.dumps(get_risks())


@mcp.tool()
def find_affected_tasks(
    disruption_minutes: int, reason: str = "External disruption"
) -> str:
    """Calculate which tasks are affected by a disruption."""
    result = generate_recovery(
        DisruptionIn(disruption_minutes=disruption_minutes, reason=reason)
    )
    return json.dumps(
        {"affected_tasks": result["affected_tasks"], "plan_id": result["plan_id"]}
    )


@mcp.tool()
def generate_recovery_options(
    disruption_minutes: int, reason: str = "External disruption"
) -> str:
    """Generate alternatives; every option includes deterministic validation."""
    return json.dumps(
        generate_recovery(
            DisruptionIn(disruption_minutes=disruption_minutes, reason=reason)
        )
    )


@mcp.tool()
def validate_schedule() -> str:
    """Validate durations, deadlines, fixed commitments, working hours and buffers."""
    return json.dumps(validate_candidate(schedule_tasks(get_tasks())))


@mcp.tool()
def apply_approved_plan(proposal_id: str, user_approved: bool) -> str:
    """Apply a feasible proposal only after explicit user approval."""
    if not user_approved:
        return json.dumps(
            {"status": "not_applied", "reason": "Explicit approval is required"}
        )
    return json.dumps(approve_recovery(proposal_id))


@mcp.tool()
def get_plan_history() -> str:
    """Read proposal, approval and restore history."""
    return json.dumps(plan_history())


if __name__ == "__main__":
    mcp.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=int(os.getenv("MCP_PORT", "8011")),
        stateless_http=True,
        json_response=True,
    )
