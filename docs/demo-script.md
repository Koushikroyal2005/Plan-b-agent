# Plan B three-minute hackathon demo

## 0:00 — The promise

Open **My Day**. Explain that Plan B is a recovery agent, not another task list: the timeline is calculated from durations, deadlines, fixed commitments, working hours and protected buffers.

Point to the risk evidence and confidence score. The warning names the affected task and its exact remaining slack.

## 0:35 — The disruption

Open **AI Assistant** and say or type:

> My meeting is running 45 minutes late.

Show the tool sequence: read schedule, check risks, find affected tasks, generate recovery options and validate schedules.

## 1:10 — The decision workspace

Open **Recovery plans**. Compare the options and click between them. Every option has its own revised timeline, trade-off and validation result.

Select the recommended feasible option and approve it. An infeasible option remains visibly blocked.

## 2:00 — Trust and recovery

Show the updated My Day timeline, then plan history. Explain that the old schedule was retained and use **Restore** to demonstrate reversibility.

## 2:25 — MCP and extensibility

Run `python backend/mcp_server.py`. Show discovery for the ten typed tools and call `check_deadline_risks` or `get_day_schedule` from an MCP client.

Finish on **Settings**: model and voice providers are server-side adapters. API keys can be added later without weakening validation or approval rules.
