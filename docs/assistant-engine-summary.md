# Plan B assistant rebuild — plain-English summary

## 1. What the request asked for

The goal was to turn Plan B's assistant from a "chatbot that guesses one intent" into the **product's operating system**: one assistant that can do everything the app can do, by voice or text, safely, and in a way you can always undo.

The request had four phases:

| Phase | In short |
| --- | --- |
| 1. Fix the foundation | One voice system shared by every page, clear microphone errors, no 25-second waits, no debug labels in the UI, and a list of every action the assistant may perform. |
| 2. Make it think in plans | Multi-step plans, "which task did you mean?" questions, memory of the conversation, corrections ("no, shorten it instead"), safety checks, and a record of every change that can be undone. |
| 3. Make it feel good | Show the steps as they happen, natural replies, interrupt it while it speaks, a "Why this plan?" answer, one-click undo, and a ready-made demo for judges. |
| 4. Prove it works | About 100 recorded test conversations, voice tests, speed measurements, and failure tests. |

The demo story it had to support:

1. *"My meeting ran 45 minutes late and I still need to finish the pitch before 6."* → Plan B offers two safe options.
2. *"Don't move lecture notes. Shorten the report review instead."* → Plan B revises the plan.
3. *"Apply it."* → the calendar changes.
4. *"Undo that."* → the original schedule comes back exactly.

## 2. How it works now (the simple picture)

```
You speak or type
      │
      ▼
Voice session (browser)  ── listens, notices when you pause, shows what it heard
      │
      ▼
Assistant engine (backend)
  1. Understand   → turns your words into a plan of steps
  2. Resolve      → finds the real tasks you mean ("the report" → "Report review")
  3. Check        → asks if something is missing or unclear
  4. Confirm      → asks "OK?" before changing anything important
  5. Do it        → runs each step using the app's real functions
  6. Verify       → checks the result really happened
  7. Record       → saves a before/after entry so it can be undone
      │
      ▼
Reply: what it said, the steps it took, buttons (Apply / Why / Undo)
```

## 3. What was built

### Backend — the "brain" (`backend/app/engine/`)

| Feature | What it means for the user |
| --- | --- |
| **Capability registry** (`catalog.py`) | A list of 19 actions Plan B can perform: search, create, edit, complete, archive and restore tasks; create and edit projects; inspect the calendar and find free time; check risk; recover the day; apply a plan; explain a plan; insights; preferences; undo; history; and navigation. Each action has rules: does it need your OK, can it be undone, and what inputs it needs. |
| **Plans with steps** (`plans.py`) | One sentence can become several steps, e.g. "create a task and open my calendar". |
| **Two ways to understand** (`interpreter.py`, `model_planner.py`) | A fast built-in rules reader handles common phrases instantly. If an AI model is configured, it can plan harder requests, but its plan is checked against the registry first; unknown actions are rejected. |
| **No more long waits** | The AI model has a 5-second limit. After 2 failures it is switched off for 60 seconds and the rules reader answers instead. Simple commands like "undo", "apply it", or "open calendar" never wait for the model. |
| **Understands which task you mean** (`resolver.py`) | "the report" finds "Report review". If two tasks match, Plan B asks you to choose instead of guessing. "it" and "that" refer to the last task you talked about. |
| **Memory** (`memory.py`) | Remembers the current conversation, what it is waiting for, half-finished drafts ("continue" resumes them), and a history of past turns. Sending the same message twice does not run it twice. |
| **Corrections** | "Don't move lecture notes", "shorten the report review instead", "make it 30 minutes" all change the plan that is already on the table. |
| **Safety checks** | Plans that would miss a deadline or overlap fixed events are never offered or applied. After applying, Plan B checks the calendar really changed. |
| **Undo for everything** (`ledger.py`) | Every change saves a before and after copy, plus the exact way to reverse it. "Undo that" or the Undo button puts things back. Tasks are archived, never deleted. Plans approved on the Recovery page can also be undone. |
| **Better recovery options** | Recovery now understands targets ("finish the pitch before 6"), things to protect, things to shorten, and things to move to tomorrow. Each option lists exactly what changes. |
| **"Why this plan?"** | Plan B explains the choice: what you asked for, when the important task now ends, and what it costs. |
| **Judge demo mode** (`/api/demo`) | One click loads a realistic day (lectures, a team meeting, notes, report, pitch due at 6 PM) with the clock pinned at 1:30 PM. Your real tasks are put aside and come back when you exit the demo. |

New backend endpoints:

- `POST /api/assistant` — talk to the assistant.
- `GET /api/assistant/capabilities` — list everything it can do.
- `GET /api/assistant/history` — the conversation so far.
- `GET /api/actions`, `POST /api/actions/undo`, `POST /api/actions/{id}/undo` — the change history and undo.
- `GET`/`POST`/`DELETE /api/demo` — check, start, or stop the judge demo.

The old single-intent assistant files (`assistant_service.py`, `agents/`, `conversation_harness.py`) were removed because the engine replaces them.

### Frontend — the "ears and voice" (`frontend/src/voice/`, `components/`)

| Feature | What it means for the user |
| --- | --- |
| **One voice session for the whole app** (`VoiceSession.jsx`) | The floating mic and the chat page share the same voice system, so voice behaves the same on every page. It moves through clear stages: idle, asking for the mic, listening, finishing up, transcribing, thinking, working, waiting for your OK, speaking, and back to idle. |
| **Sends when you pause** | No need to press "stop": after about a second of silence it sends what you said. |
| **Interrupt it** | Press the mic while Plan B is talking and it stops speaking and listens to you. |
| **Keeps listening when it asks a question** | If Plan B asks "How long should it take?", the mic opens again automatically. |
| **Clear voice errors** | Blocked mic, no mic, no speech heard, network problems, or an unsupported browser each get a plain message with a **Retry** or **Type instead** button. |
| **Pluggable speech engines** (`providers.js`) | Browser speech is used today. Wispr Flow and streaming speech recognition have slots ready, and a mock engine is used for tests. |
| **Instant acknowledgement** | While the backend works you immediately see "Got it — checking what that delay affects…" instead of a blank wait. |
| **Step timeline** (`TurnDetails.jsx`) | Each reply shows the steps Plan B took, e.g. "Reading today's calendar → Finding work affected by the delay → Protecting Finish the pitch by 6:00 PM → 2 safe options found". |
| **Buttons instead of typing** | Apply option 1, Apply option 2, Why this plan?, Confirm, Cancel, and **Undo**. |
| **"How Plan B decided"** | A fold-out panel showing what it heard, how it understood it, the evidence, and how fast it was. |
| **Debug labels removed** | "bounded orchestrator · max 6 steps", "write tools allowlisted", "approval gated", and "converse · fallback" are gone. |
| **Judge demo button** | "Load judge demo" / "Exit judge demo" on the Today screen, with a banner listing the four sentences to try. |
| **Undo after approving** | Approving a plan on the Recovery page shows a toast with an Undo button. |

## 4. How it was tested

| Test | Count | What it proves |
| --- | --- | --- |
| Conversation corpus (`backend/tests/evals/conversations.json`) | 121 conversations | Real phrasings for navigation, risk, recovery, creating and editing tasks and projects, archiving, missing details, corrections, pronouns, interruptions, pause/resume, and undo all give the right result. |
| Demo story test | 1 | After apply then undo, the schedule is exactly the original. |
| Safety tests | several | Impossible plans are never applied, slow AI providers trip the 5-second limit, repeated messages are not run twice, and replies contain no debug fields. |
| All backend tests | 158 passing | Includes the owner's existing tests. |
| Voice lifecycle tests (`frontend/src/voice/VoiceSession.test.jsx`) | 13 | Correct stage order, send on pause, interrupt, keep listening, mic errors, no-speech, backend down, cancel, and unsupported providers. |
| Orb tests (`VoiceAssistant.test.jsx`) | 4 | Confirm button, Undo button, live transcript, and blocked-mic message. |
| All frontend tests | 24 passing | |
| Manual browser run | 1 | The full demo story was run in the browser: options, correction, apply (the calendar updated), and Undo (the original times came back). |

Each demo turn took under 15 ms on the server with the rules reader.

## 5. How to try it

```bash
# backend
cd backend && .venv/bin/python -m uvicorn main:app --reload --port 8000
# frontend (new terminal)
cd frontend && npm run dev
```

1. Open the app, go to **Today**, and click **Load judge demo**.
2. Press the mic (or open **AI Assistant**) and say or type the four demo sentences:
   - "My meeting ran 45 minutes late and I still need to finish the pitch before 6"
   - "Don't move lecture notes. Shorten the report review instead"
   - "Apply it"
   - "Undo that"
3. Click **Exit judge demo** to get your own tasks back.

Optional setting in `backend/.env`: `LLM_TIMEOUT_SECONDS=5` is the longest Plan B will wait for the AI model before answering with its built-in rules.

## 6. Known limits

- Wispr Flow and server-side streaming speech recognition are prepared as slots but not connected; the browser's speech recognition is used.
- Step timelines are shown when the reply arrives, step by step, rather than streamed live while the backend works. Every step finishes in milliseconds, so live streaming would add little today.
- Voice input needs a browser with speech recognition (Chrome or Edge). Typing always works.
