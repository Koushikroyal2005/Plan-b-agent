import { useCallback, useEffect, useRef, useState } from "react";
import { Check, Mic, MicOff, Sparkles, Volume2, X } from "lucide-react";
import { useSpeechRecognition } from "../hooks/useSpeechRecognition";
import { useSpeechSynthesis } from "../hooks/useSpeechSynthesis";

const suggestionsByView = {
  dashboard: ["Plan my day", "What is at risk?", "Create a task"],
  calendar: ["Find a focus block", "What is next?", "Fix my day"],
  tasks: ["Create a task", "Create a project", "What is overdue?"],
  patterns: ["How was my focus?", "Show my progress", "Open my day"],
  settings: ["Turn on voice replies", "Open my day", "What can you do?"],
};

export function VoiceAssistant({ turn, busy, preferences, currentView = "dashboard", onSend, onOpenChat, onDismiss }) {
  const [expanded, setExpanded] = useState(false);
  const [liveTranscript, setLiveTranscript] = useState("");
  const wasSpeaking = useRef(false);
  const greetingPending = useRef(false);
  const voiceEnabled = preferences?.voice_output !== false;
  const { speaking, speak, stop: stopSpeaking } = useSpeechSynthesis({
    enabled: voiceEnabled,
    language: preferences?.language || "en-IN",
  });
  const onTranscript = useCallback(
    (value) => {
      setExpanded(true);
      setLiveTranscript("");
      onSend(value, "voice");
    },
    [onSend],
  );
  const { listening, supported, toggle, stop } = useSpeechRecognition({
    language: preferences?.language || "en-IN",
    onTranscript,
    onInterim: setLiveTranscript,
  });

  useEffect(() => {
    if (turn?.channel === "voice" && turn.say) speak(turn.say);
  }, [turn, speak]);

  useEffect(() => {
    if (speaking) wasSpeaking.current = true;
    if (!speaking && wasSpeaking.current && greetingPending.current) {
      wasSpeaking.current = false;
      greetingPending.current = false;
      const timer = window.setTimeout(() => toggle(), 250);
      return () => window.clearTimeout(timer);
    }
    if (!speaking && wasSpeaking.current && turn?.channel === "voice" && turn?.listen_again) {
      wasSpeaking.current = false;
      const timer = window.setTimeout(() => toggle(), 250);
      return () => window.clearTimeout(timer);
    }
    return undefined;
  }, [speaking, toggle, turn]);

  const listen = () => {
    if (speaking) stopSpeaking();
    if (!expanded) {
      setExpanded(true);
      const hour = new Date().getHours();
      const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
      const name = preferences?.display_name ? `, ${preferences.display_name}` : "";
      greetingPending.current = speak(`${greeting}${name}. What can I help you plan?`);
      if (greetingPending.current) return;
    }
    setExpanded(true);
    toggle();
  };
  const cancel = () => {
    stop();
    stopSpeaking();
    if (turn?.state === "asking" || turn?.state === "confirming") onSend("cancel", "voice");
    else onDismiss?.();
  };
  const status = busy ? "Thinking" : speaking ? "Speaking" : listening ? "Listening" : turn?.state === "confirming" ? "Needs confirmation" : "Ready";

  return (
    <div className={`voice-assistant ${expanded ? "expanded" : ""}`} aria-live="polite">
      {expanded && (
        <div className="voice-card">
          <header>
            <span className="voice-mark"><Sparkles size={16} /></span>
            <div><b>Plan B Assistant</b><small>{status}</small></div>
            <button aria-label="Close assistant" onClick={() => setExpanded(false)}><X size={16} /></button>
          </header>
          <p>{turn?.say || "Tell me what you want to do in Plan B."}</p>
          {(listening || liveTranscript) && (
            <div className="voice-wave-wrap">
              <div className="voice-wave" aria-hidden="true">{[1, 2, 3, 4, 5, 6, 7].map((bar) => <i key={bar} />)}</div>
              <span>{liveTranscript || "Listening…"}</span>
            </div>
          )}
          {turn?.pending_action && (
            <div className="voice-intent">
              <small>Pending action</small>
              <b>{turn.pending_action.intent.replace(".", " ")}</b>
            </div>
          )}
          <div className="voice-actions">
            {turn?.requires_confirmation && <button className="confirm" onClick={() => onSend("yes", "voice")}><Check size={14} /> Confirm</button>}
            {turn?.requires_confirmation && <button onClick={() => onSend("cancel", "voice")}>Cancel</button>}
            <button onClick={onOpenChat}>Open chat</button>
          </div>
          {!turn?.requires_confirmation && !listening && (
            <div className="voice-suggestions">
              {(suggestionsByView[currentView] || suggestionsByView.dashboard).map((suggestion) => (
                <button key={suggestion} onClick={() => onSend(suggestion, "voice")}>{suggestion}</button>
              ))}
            </div>
          )}
          {!supported && <small className="voice-warning">Voice recognition is unavailable in this browser. Text commands still work.</small>}
        </div>
      )}
      <button
        className={`voice-orb ${listening ? "listening" : ""} ${speaking ? "speaking" : ""}`}
        aria-label={listening ? "Stop listening" : "Talk to Plan B"}
        onClick={listen}
        disabled={busy || !preferences?.voice_input}
      >
        {listening ? <MicOff size={22} /> : speaking ? <Volume2 size={22} /> : <Mic size={22} />}
      </button>
      {(listening || speaking || busy) && <button className="voice-stop" onClick={cancel}>Stop</button>}
    </div>
  );
}
