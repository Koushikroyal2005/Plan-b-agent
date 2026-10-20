# Plan B Agent

Plan B is a schedule-recovery workspace built for students and young professionals. It detects schedule risk, proposes validated alternatives, and never changes a plan until the user approves it.

> React + FastAPI + SQLite + NVIDIA NIM + MCP

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

## NVIDIA model configuration

The deterministic planner works without an API key. For AI explanations and conversation, add an NVIDIA API key to `backend/.env`:

```env
LLM_PROVIDER=nvidia-nim
LLM_MODEL=openai/gpt-oss-20b
LLM_BASE_URL=https://integrate.api.nvidia.com/v1
LLM_API_KEY=your-server-only-key
```

The Settings → AI & Models screen includes a live provider test. Model calls use NVIDIA's OpenAI-compatible chat-completions endpoint. Never put API keys in the React app or commit `.env` files.

The same screen can load all models enabled for the NVIDIA account, test a chosen model, and persist it as the active model. A failed model is never activated.

## Test and verify

Run the backend API, agent, recovery and MCP tests:

```powershell
cd backend
python -m pytest
```

Run frontend interaction tests, the production build and dependency audit:

```powershell
cd frontend
npm test
npm run build
npm audit
```

## Optional MCP server

With the backend environment active:

```powershell
cd backend
python mcp_server.py
```

The UI also exposes an MCP tool playground at `/api/mcp/tools` and `/api/mcp/call`.

## Project layout

```text
frontend/   React UI, feature components, shared hooks and tests
backend/    FastAPI, deterministic planner, provider adapters, MCP and tests
docs/       Architecture and demo notes
images/     Local visual references (intentionally not versioned)
```

See [docs/architecture.md](docs/architecture.md) for the system design and API surface.
