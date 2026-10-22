import { useState } from "react";
import { Check, ChevronDown, Circle, RotateCcw, X } from "lucide-react";

export function StepTimeline({ steps = [] }) {
  if (!steps.length) return null;
  return (
    <ol className="turn-timeline">
      {steps.map((step, index) => (
        <li
          className={`turn-step ${step.status || "done"}`}
          key={`${step.label}-${index}`}
          style={{ animationDelay: `${index * 90}ms` }}
        >
          <span>{step.status === "failed" ? <X size={11} /> : step.status === "waiting" ? <Circle size={10} /> : <Check size={11} />}</span>
          <div>
            <b>{step.label}</b>
            {step.detail && <small>{step.detail}</small>}
          </div>
        </li>
      ))}
    </ol>
  );
}

function formatMs(value) {
  return typeof value === "number" ? `${value} ms` : "—";
}

export function DecisionPanel({ turn, metrics }) {
  const [open, setOpen] = useState(false);
  if (!turn) return null;
  const rows = [
    ["Heard", turn.heard],
    ["Understood as", turn.understood],
    ["Planned by", turn.planner === "model" ? "Language model, checked by Plan B's rules" : "Plan B's built-in rules"],
  ].filter(([, value]) => value);
  return (
    <div className={`decision-panel ${open ? "open" : ""}`}>
      <button type="button" onClick={() => setOpen(!open)} aria-expanded={open}>
        How Plan B decided <ChevronDown size={13} />
      </button>
      {open && (
        <div>
          <dl>
            {rows.map(([label, value]) => (
              <div key={label}><dt>{label}</dt><dd>{value}</dd></div>
            ))}
          </dl>
          {turn.evidence?.length > 0 && (
            <ul>{turn.evidence.map((item) => <li key={item}>{item}</li>)}</ul>
          )}
          <small className="decision-metrics">
            Server {formatMs(turn.metrics?.total_ms)}
            {metrics?.responseMs != null && ` · round trip ${formatMs(metrics.responseMs)}`}
            {metrics?.firstInterimMs != null && ` · first words ${formatMs(metrics.firstInterimMs)}`}
            {metrics?.firstAudioMs != null && ` · reply audio ${formatMs(metrics.firstAudioMs)}`}
          </small>
        </div>
      )}
    </div>
  );
}

export function TurnActions({ turn, onSend, onUndo, disabled }) {
  if (!turn) return null;
  const choices = turn.choices || [];
  if (!choices.length && !turn.undo) return null;
  return (
    <div className="turn-actions">
      {choices.map((choice, index) => (
        <button
          type="button"
          className={index === 0 && choice.value !== "cancel" ? "primary" : ""}
          key={choice.value}
          disabled={disabled}
          onClick={() => onSend?.(choice.value)}
        >
          {choice.value === "yes" && <Check size={13} />} {choice.label}
        </button>
      ))}
      {turn.undo && (
        <button type="button" className="undo" disabled={disabled} onClick={() => onUndo?.(turn.undo.action_id)}>
          <RotateCcw size={13} /> Undo
        </button>
      )}
    </div>
  );
}

export function TurnDetails({ turn, metrics, onSend, onUndo, disabled, showSteps = true }) {
  if (!turn) return null;
  return (
    <div className="turn-details">
      {showSteps && <StepTimeline steps={turn.steps} />}
      <TurnActions turn={turn} onSend={onSend} onUndo={onUndo} disabled={disabled} />
      <DecisionPanel turn={turn} metrics={metrics} />
    </div>
  );
}
