# Plan B Assistant Operating Layer

Plan B treats the assistant as an operating layer over the product, not as a separate chatbot. A user can perform the same work manually or ask the assistant by voice or text.

## Interaction model

The assistant has four levels of presence:

1. A persistent floating orb on every product view.
2. A compact contextual panel for briefings, suggestions, speech, and confirmations.
3. The existing full chat workspace for longer planning conversations.
4. Product UI commands that navigate to the relevant view after an action.

The compact panel reads `/api/briefing` whenever assistant state changes. Suggestions are generated from live tasks, projects, schedule blocks, risks, and capacity. No sample task names or fixed productivity claims are presented as user data.

## Request lifecycle

1. Capture text or speech through the shared `VoiceSessionProvider` (`frontend/src/voice/`), which owns the microphone, end-of-speech detection, barge-in, speech output, and error messages for every view.
2. Show an immediate local acknowledgement while the backend works.
3. The backend `AssistantEngine` (`backend/app/engine/`) turns the request into a typed plan of capability steps, using rules first and an optional model planner with a 5-second timeout and a circuit breaker.
4. Resolve task and project references, and ask when something is missing or ambiguous.
5. Require explicit confirmation for consequential changes, then execute, verify postconditions, and record an undoable entry in the action ledger.
6. Return the reply, step timeline, choices, evidence, and undo handle; the UI refreshes affected data.
7. Speak the result when voice output is enabled, and listen again when the assistant asked a question.

See `assistant-engine-summary.md` for a plain-English overview of the engine and the judge demo.

## Briefing engine

`backend/app/briefing.py` is deterministic and explainable. It currently detects:

- schedule risks that need attention;
- plans above configured capacity;
- unscheduled open work;
- active projects without concrete next tasks;
- the next planned focus block or highest-priority open task.

Each recommendation contains a title, reason, executable assistant prompt, priority, and confidence. This keeps recommendation logic testable and independent from the language model.

## Reliability boundaries

- The language model interprets intent; typed application tools perform writes.
- The backend remains the source of truth for tasks, projects, preferences, and plans.
- Read-only recommendations may be shown proactively.
- Mutating proposals remain confirmation-gated.
- Browser speech recognition is progressive enhancement; text input always remains available.
- Speech output can be muted and respects reduced-motion browser preferences.

## Provider configuration

The existing NVIDIA-compatible provider remains model-configurable through backend environment variables. API keys stay in `backend/.env` and must never be committed. The briefing engine continues to work if the provider is unavailable, so core planning information is not coupled to model uptime.
