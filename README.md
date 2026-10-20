# Plan B Agent

Plan B is a schedule-recovery workspace built for students and young professionals. It detects schedule risk, proposes validated alternatives, and never changes a plan until the user approves it.

## Features

- Dashboard, projects, tasks, calendar and proactive schedule predictions.
- Clickable calendar days and events with time breakdowns.
- AI assistant with controlled planning tools and browser voice input.
- Recovery options, approval gates, plan history and restore.
- Time trends, goals, focus, balance and estimate analytics.
- Python MCP server with ten allowlisted planning tools.

## Tech stack

- Frontend: React, Vite and Tailwind CSS.
- Backend: FastAPI and SQLite.
- Agent/MCP: deterministic planning engine, provider-ready adapter and Python MCP SDK.

## Run locally

### Prerequisites

- Node.js 20 or later
- Python 3.11 or later
- npm and pip

### 1. Clone the repository

```powershell
git clone https://github.com/Koushikroyal2005/Plan-b-agent.git
cd Plan-b-agent
```

### 2. Configure and start the backend

Open a PowerShell terminal in the project root:

```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn main:app --reload --port 8000
```

If PowerShell blocks activation, run this once for the current terminal and retry:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
```

### 3. Start the frontend

Open a second terminal in the project root:

```powershell
cd frontend
npm install
npm run dev
```

Open [http://localhost:5173](http://localhost:5173).

The frontend proxies `/api` requests to `http://localhost:8000`.

## Optional provider configuration

The application works without API keys using its deterministic planner. To connect an OpenAI-compatible model later, set these server-side values in `backend/.env`:

```env
LLM_PROVIDER=your-provider
LLM_MODEL=your-model-id
LLM_BASE_URL=https://your-provider.example/v1
LLM_API_KEY=your-server-only-key
```

Never put API keys in the React app or commit `.env` files.

## Optional MCP server

With the backend environment active:

```powershell
cd backend
python mcp_server.py
```

The UI also exposes an MCP tool playground at `/api/mcp/tools` and `/api/mcp/call`.

## Project layout

```text
frontend/   React user interface
backend/    FastAPI, SQLite planner and MCP server
docs/       Architecture and demo notes
images/     Local visual references (intentionally not versioned)
```

See [docs/architecture.md](docs/architecture.md) for the system design and API surface.
