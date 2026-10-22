import { useEffect, useState } from "react";
import { Mic, MicOff, RotateCcw, Sparkles, Square, Volume2, X } from "lucide-react";
import { useVoiceSession } from "../voice/VoiceSession";
import { TurnDetails } from "./TurnDetails";

const suggestionsByView = {
  dashboard: ["Plan my day", "What is at risk?", "Create a task"],
  calendar: ["Find a focus block", "What is next?", "My meeting ran 30 minutes late"],
  tasks: ["Create a task", "Create a project", "What is overdue?"],
  patterns: ["How was my focus?", "Show my progress", "Open my day"],
  settings: ["Turn on voice replies", "Open my day", "What can you do?"],
};

export function VoiceAssistant({ turn, busy, preferences, currentView = "dashboard", onOpenChat, onUndo }) {
  const voice = useVoiceSession();
  const [expanded, setExpanded] = useState(false);
  const shownTurn = voice.turn && voice.turn.turn_id === turn?.turn_id ? voice.turn : turn;
  const voiceInput = preferences?.voice_input !== false;
  const working = busy || voice.busy;
  useEffect(() => {
    if (turn?.channel === "voice" || voice.error) setExpanded(true);
  }, [turn, voice.error]);

  const send = (text) => {
    setExpanded(true);
    voice.submit(text, "voice");
  };
  const pressOrb = () => {
    setExpanded(true);
    if (!voiceInput) return;
    voice.toggle();
  };

  return (
    <div className={`voice-assistant ${expanded ? "expanded" : ""}`} aria-live="polite">
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
        className={`voice-orb ${voice.active ? "listening" : ""} ${voice.phase === "speaking" ? "speaking" : ""}`}
        aria-label={voice.active ? "Stop listening" : voice.phase === "speaking" ? "Interrupt and talk" : "Talk to Plan B"}
        onClick={pressOrb}
        disabled={working}
      >
        {voice.active ? <MicOff size={22} /> : voice.phase === "speaking" ? <Volume2 size={22} /> : <Mic size={22} />}
      </button>
    </div>
  );
}
