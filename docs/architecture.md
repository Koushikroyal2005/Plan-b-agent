# Plan B architecture

## Product boundary

The React application is a decision workspace, not the source of truth. It renders onboarding, tasks, calendars, predictions, evidence, candidate plans, analytics and approvals. FastAPI owns scheduling rules, persistence, provider secrets, versioning and MCP authorization.

## Controlled agent loop

```text
Understand -> Inspect -> Plan -> Validate -> Explain -> Wait -> Commit
```

The model may interpret intent, but it cannot bypass deterministic scheduling rules or approve its own proposal. A candidate is feasible only after duration, deadline, fixed-commitment, working-hours and buffer checks complete.

## Runtime components

- `frontend/`: React, Vite and Tailwind responsive decision workspace.
- `backend/main.py`: FastAPI routes, provider adapter, persistence and deterministic planning engine.
- `backend/mcp_server.py`: Python MCP SDK server exposing ten tools over Streamable HTTP.
- `backend/planb.sqlite3`: tasks, preferences, plan versions, recovery proposals and audit events.

## Implemented product areas

- Five-step onboarding with persisted workday, planning style and buffer rules.
- Dashboard with four live metrics, project progress, activity feed, mini calendar, upcoming work and an AI suggestion.
- My Day timeline, filterable risk evidence, metrics and actionable proactive predictions.
- Day/week calendar with clickable day breakdowns, event detail dialogs, risk states and an assistant-led recovery preview.
- Searchable, sortable task and project manager with numbering, project filters, list/Kanban layouts, editing, completion and archive.
- Tool-backed text and browser voice assistant with visible agent activity.
- Recovery option comparison, before/after timelines, validation, approval and restoration.
- Time trends, task progress, goals, activity, progress/focus, balance, workload and estimate analytics.
- AI provider, voice and connection settings without browser-side secrets.
- MCP registry and interactive tool inspector.

## API contract

- My Day: `GET /api/day` and `GET /api/risks`
- Tasks: `GET/POST/PATCH /api/tasks`
- Projects: `GET/POST/PATCH /api/projects`
- Predictions: `GET /api/opportunities` and `POST /api/opportunities/{id}/respond`
- Assistant: `POST /api/assistant`
- Recovery: `POST /api/recovery/options`
- Approval: `POST /api/recovery/{proposal_id}/approve`
- History: `GET /api/recovery/history` and `POST /api/recovery/{plan_id}/restore`
- Settings: `GET/PUT /api/preferences`
- Patterns: `GET /api/patterns`
- Provider health: `GET /api/provider/status`
- MCP inspection: `GET /api/mcp/tools` and `POST /api/mcp/call`

## Approval and version safety

Each recovery option stores its own revised timeline and validation evidence. Application requires a feasible proposal in `awaiting_approval` state. Applying it saves the selected proposal and retains the previous plan. Restore creates another version instead of deleting history.

## Provider design

`/api/assistant` uses an OpenAI-compatible server adapter when `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` are configured. Without keys it uses the same deterministic tools and honest fallback responses. Browser speech works now; Wispr Flow can be attached through the existing voice/MCP adapter boundary when credentials arrive.

No provider key is inserted into the browser bundle or returned in a browser response.
