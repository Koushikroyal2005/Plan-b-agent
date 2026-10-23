import { useEffect, useState } from "react";
import { RotateCcw, Sparkles, Square, X } from "lucide-react";
import { useVoiceSession } from "../voice/VoiceSession";
import { TurnDetails } from "./TurnDetails";

const suggestionsByView = {
  dashboard: ["Plan my day", "What is at risk?", "Create a task"],
  calendar: ["Find a focus block", "What is next?", "My meeting ran 30 minutes late"],
  tasks: ["Create a task", "Create a project", "What is overdue?"],
  patterns: ["How was my focus?", "Show my progress", "Open my day"],
  settings: ["Turn on voice replies", "Open my day", "What can you do?"],
};

const discoveryByView = {
  dashboard: ["Ask me to plan your day", "Ask what is at risk today", "Tell me what changed"],
  calendar: ["Ask me to find a free block", "Ask which session a task is in", "Tell me to move a task"],
  tasks: ["Tell me to create a task", "Ask me to organise a project", "Ask what is still open"],
  patterns: ["Ask when you focus best", "Ask me to explain your trends", "Ask how this week is going"],
  settings: ["Tell me your planning preferences", "Ask me to turn on voice replies", "Ask what I can control"],
};

export function VoiceAssistant({ turn, busy, preferences, currentView = "dashboard", onOpenChat, onUndo }) {
  const voice = useVoiceSession();
  const [expanded, setExpanded] = useState(false);
  const [hintIndex, setHintIndex] = useState(0);
  const [hintVisible, setHintVisible] = useState(false);
  const [hintDismissed, setHintDismissed] = useState(() => window.sessionStorage.getItem("planb-voice-hint-dismissed") === "1");
  const shownTurn = voice.turn && voice.turn.turn_id === turn?.turn_id ? voice.turn : turn;
  const voiceInput = preferences?.voice_input !== false;
  const working = busy || voice.busy;
  useEffect(() => {
    if (turn?.channel === "voice" || voice.error) setExpanded(true);
  }, [turn, voice.error]);
  useEffect(() => {
    if (expanded || hintDismissed) {
      setHintVisible(false);
      return undefined;
    }
    setHintVisible(true);
    const hide = window.setTimeout(() => setHintVisible(false), 10000);
    const next = window.setTimeout(() => setHintIndex((value) => value + 1), 15000);
    return () => {
      window.clearTimeout(hide);
      window.clearTimeout(next);
    };
  }, [expanded, hintDismissed, hintIndex]);

  const dismissHint = () => {
    setHintDismissed(true);
    setHintVisible(false);
    window.sessionStorage.setItem("planb-voice-hint-dismissed", "1");
  };

  const send = (text) => {
    setExpanded(true);
    voice.submit(text, "voice");
  };
  const pressOrb = () => {
    dismissHint();
    setExpanded(true);
    if (!voiceInput) return;
    voice.toggle();
  };

  return (
    <div className={`voice-assistant ${expanded ? "expanded" : ""}`} aria-live="polite">
      {!expanded && hintVisible && (
        <div className="voice-discovery" role="status">
          <button className="voice-discovery-copy" onClick={pressOrb}>
            <b>Hey, I’m Plan B.</b>
            <span>{(discoveryByView[currentView] || discoveryByView.dashboard)[hintIndex % 3]}.</span>
          </button>
          <button className="voice-discovery-close" onClick={dismissHint} aria-label="Dismiss assistant tip">×</button>
        </div>
      )}
      {expanded && (
        <div className="voice-card">
          <header>
            <span className="voice-mark"><Sparkles size={16} /></span>
            <div><b>Plan B Assistant</b><small data-testid="voice-phase">{voice.label}</small></div>
            <button aria-label="Close assistant" onClick={() => setExpanded(false)}><X size={16} /></button>
          </header>

          {voice.error ? (
            <div className="voice-error" role="alert">
              <p>{voice.error.message}</p>
              <div>
                {voice.error.recoverable && <button onClick={voice.retry}><RotateCcw size={13} /> Retry</button>}
                <button onClick={onOpenChat}>Type instead</button>
              </div>
            </div>
          ) : voice.active ? (
            <div className="voice-wave-wrap">
              <div className="voice-wave" aria-hidden="true">{[1, 2, 3, 4, 5, 6, 7].map((bar) => <i key={bar} />)}</div>
              <p className="voice-live" aria-label="Voice transcript">{voice.interim || "Listening… speak naturally. I'll send when you pause."}</p>
            </div>
          ) : voice.busy ? (
            <p className="voice-ack"><span className="thinking-dots"><i /><i /><i /></span> {voice.ack || "One moment…"}</p>
          ) : (
            <p>{shownTurn?.say || "Tell me what changed, or ask me to plan, move, or create something."}</p>
          )}

          {!voice.active && !voice.busy && (
            <TurnDetails turn={shownTurn} metrics={voice.metrics} onSend={send} onUndo={onUndo} disabled={working} />
          )}

          <div className="voice-actions">
            {voice.active && <button className="confirm" onClick={voice.stop}><Square size={12} /> Done speaking</button>}
            {(voice.active || voice.phase === "speaking") && <button onClick={voice.cancel}>Cancel</button>}
            <button onClick={onOpenChat}>Open chat</button>
          </div>
          {!shownTurn?.choices?.length && !voice.active && !voice.busy && (
            <div className="voice-suggestions">
              {(suggestionsByView[currentView] || suggestionsByView.dashboard).map((suggestion) => (
                <button key={suggestion} onClick={() => send(suggestion)}>{suggestion}</button>
              ))}
            </div>
          )}
          {!voiceInput && <small className="voice-warning">Voice input is off in Settings. Tap a suggestion or open chat.</small>}
          {voiceInput && !voice.supported && <small className="voice-warning">Voice input isn't available in this browser. Text commands still work.</small>}
        </div>
      )}
      <button
        className={`voice-orb phase-${voice.phase} ${voice.active ? "listening" : ""} ${voice.phase === "speaking" ? "speaking" : ""}`}
        aria-label={voice.active ? "Stop listening" : voice.phase === "speaking" ? "Interrupt and talk" : "Talk to Plan B"}
        onClick={pressOrb}
        disabled={working}
      >
        <span className="orb-halo" aria-hidden="true" />
        <span className="orb-core" aria-hidden="true">
          {voice.active || voice.phase === "speaking" ? (
            <span className="orb-wave">{[1, 2, 3, 4, 5].map((bar) => <i key={bar} />)}</span>
          ) : (
            <Sparkles size={21} />
          )}
        </span>
      </button>
    </div>
  );
}
