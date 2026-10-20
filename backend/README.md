# Plan B backend

FastAPI service with SQLite persistence and deterministic schedule/recovery logic.

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

API endpoints include `/api/tasks`, `/api/day`, `/api/risks`, `/api/recovery/options`, `/api/recovery/{proposal_id}/approve`, `/api/assistant`, `/api/mcp/tools`, and `/api/mcp/call`.
