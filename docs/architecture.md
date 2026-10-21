# Plan B architecture

## Product boundary

The React application is a decision workspace, not the source of truth. It renders onboarding, tasks, calendars, predictions, evidence, candidate plans, analytics and approvals. FastAPI owns scheduling rules, persistence, provider secrets, versioning and MCP authorization.

## Controlled agent loop

```text
Understand -> Inspect -> Plan -> Validate -> Explain -> Wait -> Commit
```

The model may interpret intent, but it cannot bypass deterministic scheduling rules or approve its own proposal. A candidate is feasible only after duration, deadline, fixed-commitment, working-hours and buffer checks complete.

## Runtime components

- `frontend/src/core/`: API gateway and navigation configuration.
- `frontend/src/components/`: reusable application-shell components, including global search and notifications.
- `frontend/src/features/`: domain-owned UI such as provider/model settings.
- `frontend/src/hooks/`: browser capability adapters such as speech recognition.
- `frontend/src/main.jsx`: application composition and product views.
- `backend/app/config.py`: typed environment configuration and secret boundary.
- `backend/app/providers/`: replaceable model-provider adapters; NVIDIA NIM is implemented.
- `backend/main.py`: FastAPI routes, SQLite repositories and deterministic planning domain service.
- `backend/mcp_server.py`: Python MCP SDK server exposing ten tools over Streamable HTTP.
- `backend/planb.sqlite3`: tasks, projects, preferences, provider selection, plan versions, recovery proposals and audit events.

## Applied design patterns

- **Adapter:** NVIDIA and browser speech are isolated behind small interfaces.
- **Service layer:** schedule generation, validation and recovery are deterministic functions used by HTTP and MCP transports.
- **Repository boundary:** SQLite access is server-only and returns normalized domain dictionaries.
- **Command/approval:** agent write operations produce proposals; a separate explicit command applies them.
- **Strategy:** each recovery option is a scheduling strategy evaluated by the same validator.
- **Gateway:** all frontend HTTP calls use one error-normalizing API client.
- **Feature composition:** shared shell, hooks and domain components have independent test seams.

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
- Provider health: `GET /api/provider/status` and `POST /api/provider/test`
- Provider models: `GET /api/provider/models` and `PUT /api/provider/model`
- MCP inspection: `GET /api/mcp/tools` and `POST /api/mcp/call`

## Approval and version safety

Each recovery option stores its own revised timeline and validation evidence. Application requires a feasible proposal in `awaiting_approval` state. Applying it saves the selected proposal and retains the previous plan. Restore creates another version instead of deleting history.

## Provider design

`/api/assistant` uses NVIDIA NIM's OpenAI-compatible endpoint when `LLM_API_KEY`, `LLM_BASE_URL` and `LLM_MODEL` are configured. The model selector reads the models enabled for the account, performs a live compatibility test, and persists the selected model in SQLite. `POST /api/provider/test` performs a minimal server-side connectivity check without returning the key. Without a working provider, the product keeps its deterministic planning and recovery behavior. Browser speech works now; Wispr Flow can be attached through the existing voice/MCP adapter boundary when credentials arrive.

No provider key is inserted into the browser bundle or returned in a browser response.
# Voice agent runtime

Plan B uses a bounded, model-first agent runtime inspired by the useful control patterns in PentAGI while remaining focused on personal planning.

1. The planner converts natural language into a validated `AgentDecision`.
2. The orchestrator resolves that decision against the current conversation state.
3. A typed `ToolRegistry` exposes only approved planning operations.
4. Read actions run immediately; writes create a pending action and require confirmation.
5. Tool results, assistant turns and pending state are persisted in SQLite.
6. Every client turn carries an idempotency key so retries cannot duplicate writes.
7. Invalid model JSON or provider outages activate a deterministic fallback router.

The runtime deliberately does not send the full task or project database to the model. The model sees the utterance, current page, pending action and tool schemas. Exact records are matched and executed inside the server.

The model interprets intent; deterministic application services remain the source of truth for scheduling, validation, recovery and writes.

Key modules:

- `app/agents/contracts.py` — structured decisions and tool arguments.
- `app/agents/planner.py` — NVIDIA structured planning plus fallback/reflection.
- `app/agents/tools.py` — allowlisted tool registry and schema validation.
- `app/assistant_service.py` — dialogue state, confirmation policy and execution.
- `app/providers/nvidia.py` — replaceable NVIDIA NIM adapter.

