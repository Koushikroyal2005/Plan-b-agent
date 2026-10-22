"""Assistant runtime: understand -> resolve -> validate -> confirm -> execute -> verify -> record."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Callable

from pydantic import ValidationError

from .capabilities import ExecContext, Outcome
from .catalog import build_registry, run_inverse
from .errors import Ambiguous, NeedsInfo, NotFound, Refused
from .interpreter import CANCEL, InterpretContext, interpret, universal
from .language import duration_minutes, normalize, ordinal
from .ledger import ActionLedger
from .memory import SessionStore
from .model_planner import ModelPlanner
from .plans import Plan, PlanStep
from .resolver import score

HELP = (
    "Tell me what changed and I'll rebuild your day, for example \"my meeting ran 45 minutes late\". "
    "I can also add, edit, move, complete, archive and restore tasks, check what's at risk, find free time, "
    "change your settings, and undo anything I did. Say cancel or stop at any time."
)
FAST_PATH = {"actions.undo", "schedule.apply", "app.navigate", "actions.history"}


@dataclass
class Run:
    text: str
    started: float = field(default_factory=perf_counter)
    steps: list[dict[str, Any]] = field(default_factory=list)
    tools: list[dict[str, str]] = field(default_factory=list)
    ui: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[str] = field(default_factory=list)
    outcomes: list[Outcome] = field(default_factory=list)
    recovery: dict[str, Any] | None = None
    undo: dict[str, Any] | None = None
    planner: str = "rules"
    understand_ms: int = 0
    execute_ms: int = 0
    prefix: str = ""
    suffix: str = ""

    def step(self, capability: str, label: str, status: str, detail: str = "", ms: int | None = None) -> None:
        self.steps.append({"capability": capability, "label": label, "status": status, "detail": detail, "ms": ms})


class AssistantEngine:
    def __init__(self, *, db: Callable[[], Any], services: Any,
                 structured_provider: Callable[[str, str], dict[str, Any] | None] | None = None,
                 model_enabled: Callable[[], bool] = lambda: False):
        self.registry = build_registry()
        self.ledger = ActionLedger(db)
        self.store = SessionStore(db)
        self.services = services
        self.model_enabled = model_enabled
        self.model = ModelPlanner(structured_provider, self.registry) if structured_provider else None

    # ---------- public ----------

    def turn(self, payload: dict[str, Any]) -> dict[str, Any]:
        text = re.sub(r"\s+", " ", (payload.get("utterance") or payload.get("message") or "").strip())
        session_id = payload.get("session_id") or "default"
        key = payload.get("idempotency_key")
        cached = self.store.cached(session_id, key)
        if cached:
            return cached
        memory = self.store.load(session_id)
        ctx = ExecContext(services=self.services, memory=memory, session_id=session_id,
                          ledger=self.ledger, today=self.services.today())
        run = Run(text=text)
        result = self._dispatch(text, payload, ctx, run)
        self.store.save(session_id, ctx.memory, text, result, key)
        return result

    def undo(self, action_id: str | None, session_id: str = "ui") -> dict[str, Any]:
        ctx = ExecContext(services=self.services, memory=self.store.load(session_id), session_id=session_id,
                          ledger=self.ledger, today=self.services.today())
        plan = Plan(goal="Undo", steps=[PlanStep(capability="actions.undo", arguments={"action_id": action_id})])
        run = Run(text="undo")
        result = self._execute(plan, ctx, run, 0, {})
        self.store.save(session_id, ctx.memory, "undo (button)", result, None)
        return result

    def record_external(self, *, capability: str, arguments: dict[str, Any], before: Any, after: Any,
                        inverse: dict[str, Any] | None, summary: str) -> str:
        return self.ledger.record(session_id="ui", requested_by="ui", capability=capability, arguments=arguments,
                                  before=before, after=after, validation={"verified": True}, confirmed=True,
                                  inverse=inverse, summary=summary)

    # ---------- dispatch ----------

    def _dispatch(self, text: str, payload: dict[str, Any], ctx: ExecContext, run: Run) -> dict[str, Any]:
        command = universal(text)
        pending = ctx.memory.get("pending")
        if command == "repeat":
            last = self.store.last_response(ctx.session_id)
            return {**last, "turn_id": str(uuid.uuid4())} if last else self._respond(ctx, run, "There's nothing to repeat yet.")
        if command == "help":
            run.ui.append({"type": "show_help"})
            return self._respond(ctx, run, HELP)
        if command == "back":
            run.ui.append({"type": "back"})
            return self._respond(ctx, run, "Going back.")
        if command == "resume":
            held = pending
            if not held:
                suspended = ctx.memory.get("suspended") or []
                if not suspended:
                    return self._respond(ctx, run, "There's nothing paused to continue.")
                held = suspended.pop()
                ctx.memory["pending"] = held
            confirming = held["kind"] == "confirm"
            return self._respond(ctx, run, held.get("preview") or held.get("question"),
                                 state="confirming" if confirming else "asking",
                                 plan=Plan.model_validate(held["plan"]), confirmation=confirming)
        if pending:
            return self._continue(pending, text, command, payload, ctx, run)
        if command == "cancel":
            return self._respond(ctx, run, "Okay, stopped. Nothing was waiting, so nothing changed.")
        if command == "confirm":
            recovery = ctx.memory.get("recovery")
            if recovery and not recovery.get("applied"):
                plan = Plan(goal="Apply the recovery plan", steps=[PlanStep(capability="schedule.apply", confirmed=True)])
            else:
                return self._respond(ctx, run, "There's nothing waiting for a yes right now.")
        else:
            plan = self._understand(text, payload, ctx, run)
        return self._execute(plan, ctx, run, 0, payload)

    def _understand(self, text: str, payload: dict[str, Any], ctx: ExecContext, run: Run) -> Plan:
        started = perf_counter()
        rules = interpret(text, InterpretContext(today=ctx.today, memory=ctx.memory, current_view=payload.get("current_view")))
        fast = rules.steps and rules.steps[0].capability in FAST_PATH and rules.confidence >= 0.95
        plan = None
        if self.model and not fast and self.model_enabled():
            plan = self.model.plan(
                text, today=ctx.today, memory=ctx.memory, tasks=self.services.tasks(),
                recent_turns=self.store.recent_turns(ctx.session_id), episodes=self.store.episodes(ctx.session_id),
                current_view=payload.get("current_view"),
            )
            if plan:
                for step in plan.steps:
                    if step.capability == "schedule.apply" and rules.steps and rules.steps[0].capability == "schedule.apply":
                        step.confirmed = True
        run.planner = plan.source if plan else "rules"
        run.understand_ms = round((perf_counter() - started) * 1000)
        return plan or rules

    # ---------- pending conversations ----------

    def _continue(self, pending: dict[str, Any], text: str, command: str | None,
                  payload: dict[str, Any], ctx: ExecContext, run: Run) -> dict[str, Any]:
        plan = Plan.model_validate(pending["plan"])
        index = pending["index"]
        step = plan.steps[index]
        kind = pending["kind"]
        if command == "cancel" or normalize(text) in CANCEL:
            ctx.memory.pop("pending", None)
            run.ui.append({"type": "close_modal"})
            return self._respond(ctx, run, "Cancelled. I did not change anything.", plan=plan)

        if kind == "confirm":
            if command == "confirm" or (step.capability == "schedule.apply" and re.search(r"\bapply\b", normalize(text))):
                step.confirmed = True
                ctx.memory.pop("pending", None)
                return self._execute(plan, ctx, run, index, payload)
            capability = self.registry.get(step.capability)
            if capability and capability.amend:
                amended = capability.amend(step.arguments, text, ctx)
                if amended:
                    step.arguments, step.prepared = amended, False
                    ctx.memory.pop("pending", None)
                    return self._execute(plan, ctx, run, index, payload)
            interruption = self._understand(text, payload, ctx, run)
            if interruption.steps:
                writes = [s for s in interruption.steps if (self.registry.get(s.capability) or capability).mode == "write"]
                if not writes and interruption.steps[0].capability != "schedule.recover":
                    held = ctx.memory.pop("pending")
                    result = self._execute(interruption, ctx, run, 0, payload, finish=False)
                    ctx.memory["pending"] = held
                    say = f"{result['say']} I'm still holding this for you: {held['preview']} Say yes or cancel."
                    return self._respond(ctx, run, say, state="confirming", plan=plan, confirmation=True)
                ctx.memory.pop("pending", None)
                run.prefix = "Okay, I dropped the earlier request. "
                return self._execute(interruption, ctx, run, 0, payload)
            return self._respond(ctx, run, f"{pending['preview']} Say yes to confirm, or cancel.",
                                 state="confirming", plan=plan, confirmation=True)

        if kind == "slot":
            value = self._fill(pending["slot_kind"], text)
            lower = normalize(text)
            asked = text.strip().endswith("?") or re.match(
                r"^(what|when|where|why|how|can|could|is|are|am|do|does|will|should|show|open|go to|take me|undo)\b", lower)
            candidate = interpret(text, InterpretContext(today=ctx.today, memory=ctx.memory))
            if candidate.steps and (asked or value is None or candidate.steps[0].capability in FAST_PATH | {"schedule.recover"}):
                suspended = ctx.memory.setdefault("suspended", [])
                suspended.append(pending)
                del suspended[:-3]
                ctx.memory.pop("pending", None)
                run.suffix = " I kept your unfinished draft; say continue when you want to resume it."
                return self._execute(self._understand(text, payload, ctx, run), ctx, run, 0, payload)
            if value is None:
                hint = "Tell me a duration such as 30 minutes or 2 hours." if pending["slot_kind"] == "duration" else pending["question"]
                return self._respond(ctx, run, hint, state="asking", plan=plan)
            if pending["slot_kind"] in {"text", "duration"}:
                step.arguments[pending["slot"]] = value
                capability = self.registry.get(step.capability)
                if capability and capability.amend and pending["slot_kind"] == "duration":
                    step.arguments = capability.amend(step.arguments, text, ctx) or step.arguments
                step.prepared = False
                ctx.memory.pop("pending", None)
                return self._execute(plan, ctx, run, index, payload)
            ctx.memory.pop("pending", None)
            return self._execute(self._understand(text, payload, ctx, run), ctx, run, 0, payload)

        if kind == "choice":
            choices = pending["choices"]
            position = ordinal(text)
            chosen = choices[position] if position is not None and -len(choices) <= position < len(choices) else None
            if not chosen:
                ranked = sorted(choices, key=lambda c: -score(text, c["label"]))
                chosen = ranked[0] if ranked and score(text, ranked[0]["label"]) >= 0.45 else None
            if not chosen:
                return self._respond(ctx, run, pending["question"], state="asking", plan=plan,
                                     choices=[{"label": c["label"], "value": c["label"]} for c in choices])
            step.arguments = _replace_ref(step.arguments, pending["reference"], f"id:{chosen['id']}")
            step.prepared = False
            ctx.memory.pop("pending", None)
            return self._execute(plan, ctx, run, index, payload)

        ctx.memory.pop("pending", None)
        return self._respond(ctx, run, "I lost track of that request, so I cancelled it safely.")

    @staticmethod
    def _fill(kind: str, text: str) -> Any:
        if kind == "duration":
            if re.fullmatch(r"\d{1,3}", text.strip(" .")):
                return int(text.strip(" ."))
            return duration_minutes(text)
        if kind == "text":
            value = re.sub(r"^(?:call it|it'?s|its|name it|it is|the name is)\s+", "", text.strip(), flags=re.I).strip(" .")
            return value[:160] or None
        return text

    # ---------- execution ----------

    def _execute(self, plan: Plan, ctx: ExecContext, run: Run, start: int, payload: dict[str, Any],
                 finish: bool = True) -> dict[str, Any]:
        began = perf_counter()
        if not plan.steps:
            if plan.missing_information:
                return self._respond(ctx, run, plan.missing_information[0], state="asking", plan=plan)
            return self._respond(ctx, run, plan.reply or HELP, plan=plan)

        for index in range(start, len(plan.steps)):
            step = plan.steps[index]
            capability = self.registry.get(step.capability)
            if not capability:
                run.step(step.capability, "Unsupported action", "failed")
                return self._respond(ctx, run, "I can't do that yet.", state="failed", plan=plan)
            step_started = perf_counter()
            try:
                if not step.prepared:
                    args = capability.args_model.model_validate(step.arguments).model_dump()
                    if capability.prepare:
                        args, preview = capability.prepare(args, ctx)
                    else:
                        preview = None
                    step.arguments, step.prepared = args, True
                    if preview:
                        step.arguments["_preview"] = preview
                if capability.confirmation == "required" and not step.confirmed:
                    preview = step.arguments.get("_preview") or f"{capability.label}?"
                    ctx.memory["pending"] = {"kind": "confirm", "plan": plan.model_dump(), "index": index, "preview": preview}
                    run.step(capability.name, capability.label, "waiting", "needs your OK")
                    return self._respond(ctx, run, preview, state="confirming", plan=plan, confirmation=True)
                outcome = capability.execute({k: v for k, v in step.arguments.items() if k != "_preview"}, ctx)
            except ValidationError as error:
                problem = error.errors()[0]
                field_name = ".".join(str(p) for p in problem["loc"])
                run.step(capability.name, capability.label, "failed", field_name)
                return self._respond(ctx, run, f"I couldn't use that {field_name.replace('_', ' ')}: {problem['msg'].lower()}.",
                                     state="failed", plan=plan)
            except NeedsInfo as question:
                ctx.memory["pending"] = {"kind": "slot", "plan": plan.model_dump(), "index": index,
                                         "slot": question.slot, "slot_kind": question.kind, "question": question.question}
                run.step(capability.name, capability.label, "waiting", "needs a detail")
                return self._respond(ctx, run, question.question, state="asking", plan=plan)
            except Ambiguous as unclear:
                choices = [{"id": c["id"], "label": c.get("title") or c.get("name")} for c in unclear.choices]
                ctx.memory["pending"] = {"kind": "choice", "plan": plan.model_dump(), "index": index,
                                         "reference": unclear.reference, "choices": choices, "question": str(unclear)}
                run.step(capability.name, capability.label, "waiting", "which one?")
                return self._respond(ctx, run, str(unclear), state="asking", plan=plan,
                                     choices=[{"label": c["label"], "value": c["label"]} for c in choices])
            except (NotFound, Refused) as problem:
                ctx.memory.pop("pending", None)
                run.step(capability.name, capability.label, "failed", str(problem))
                return self._respond(ctx, run, str(problem), state="failed", plan=plan)
            except Exception as error:  # services raise HTTP errors with a user-facing detail
                detail = getattr(error, "detail", None)
                if not isinstance(detail, str):
                    raise
                ctx.memory.pop("pending", None)
                run.step(capability.name, capability.label, "failed", detail)
                return self._respond(ctx, run, detail, state="failed", plan=plan)

            ms = round((perf_counter() - step_started) * 1000)
            run.step(capability.name, capability.label, "done", "", ms)
            for extra in outcome.timeline:
                run.steps.append({"capability": capability.name, "ms": None, **extra})
            run.tools.append({"tool": capability.name, "status": "complete"})
            if capability.mode == "write" and outcome.summary:
                action_id = self.ledger.record(
                    session_id=ctx.session_id, requested_by=payload.get("channel") or "assistant",
                    capability=capability.name, arguments={k: v for k, v in step.arguments.items() if k != "_preview"},
                    before=outcome.before, after=outcome.after, validation={"verified": outcome.verified},
                    confirmed=step.confirmed or capability.confirmation == "none",
                    inverse=outcome.inverse if capability.reversible else None, summary=outcome.summary,
                )
                if capability.reversible and outcome.inverse:
                    run.undo = {"action_id": action_id, "label": outcome.summary}
                    ctx.memory["last_action_id"] = action_id
                self.store.add_episode(ctx.session_id, outcome.summary)
            if outcome.verified is False:
                run.step(capability.name, "Verifying the change", "failed")
                outcome.say += " I couldn't verify the result, so please check it."
            ctx.memory.setdefault("focus", {}).update(outcome.focus)
            run.ui.extend(outcome.ui)
            run.evidence.extend(outcome.evidence)
            if outcome.recovery:
                run.recovery = outcome.recovery
            run.outcomes.append(outcome)

        if finish:
            ctx.memory.pop("pending", None)
        run.execute_ms += round((perf_counter() - began) * 1000)
        say = " ".join(dict.fromkeys(o.say for o in run.outcomes if o.say))
        if plan.acknowledgement and any(s.capability == "schedule.recover" for s in plan.steps):
            say = f"{plan.acknowledgement} {say}"
        return self._respond(ctx, run, say, plan=plan)

    # ---------- response ----------

    def _respond(self, ctx: ExecContext, run: Run, say: str, *, state: str = "completed", plan: Plan | None = None,
                 confirmation: bool = False, choices: list[dict[str, str]] | None = None) -> dict[str, Any]:
        say = (run.prefix + say + (run.suffix if state != "asking" or not ctx.memory.get("pending") else "")).strip()
        pending = ctx.memory.get("pending")
        if choices is None:
            choices = []
            if confirmation:
                choices = [{"label": "Confirm", "value": "yes"}, {"label": "Cancel", "value": "cancel"}]
            elif run.recovery and any(o["feasible"] for o in run.recovery["options"]):
                safe = [o for o in run.recovery["options"] if o["feasible"]][:2]
                choices = [{"label": f"Apply option {i + 1}", "value": f"apply option {i + 1}"} for i, _ in enumerate(safe)]
                choices.append({"label": "Why this plan?", "value": "why this plan?"})
        result = {
            "turn_id": str(uuid.uuid4()),
            "message": say,
            "say": say,
            "display": say,
            "state": state,
            "heard": run.text,
            "understood": plan.goal if plan and plan.goal else None,
            "acknowledgement": plan.acknowledgement if plan else None,
            "pending_action": {
                "intent": pending["plan"]["steps"][pending["index"]]["capability"],
                "kind": pending["kind"],
                "prompt": pending.get("preview") or pending.get("question"),
                "slots": {k: v for k, v in pending["plan"]["steps"][pending["index"]]["arguments"].items() if k != "_preview"},
            } if pending else None,
            "requires_confirmation": confirmation,
            "listen_again": state in {"asking", "confirming"},
            "choices": choices,
            "steps": run.steps,
            "tools": run.tools,
            "tool_events": run.tools,
            "ui_commands": run.ui,
            "evidence": run.evidence,
            "undo": run.undo,
            "planner": run.planner,
            "metrics": {
                "understand_ms": run.understand_ms,
                "execute_ms": run.execute_ms,
                "total_ms": round((perf_counter() - run.started) * 1000),
            },
        }
        if run.recovery is not None:
            result["recovery"] = run.recovery
        return result


def _replace_ref(value: Any, reference: str, replacement: str) -> Any:
    if isinstance(value, str):
        return replacement if value == reference else value
    if isinstance(value, list):
        return [_replace_ref(item, reference, replacement) for item in value]
    if isinstance(value, dict):
        return {k: _replace_ref(v, reference, replacement) for k, v in value.items()}
    return value


__all__ = ["AssistantEngine", "run_inverse"]
