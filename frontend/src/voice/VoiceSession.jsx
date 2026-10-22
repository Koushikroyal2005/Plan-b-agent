import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from "react";
import { classifyVoiceError } from "./providers";

export const PHASE_LABELS = {
  idle: "Ready",
  requesting_permission: "Asking for the microphone",
  listening: "Listening",
  endpointing: "Finishing up",
  transcribing: "Got it",
  understanding: "Thinking",
  executing: "Working",
  confirming: "Needs your OK",
  speaking: "Speaking",
  error: "Voice problem",
};

export const initialVoiceState = {
  phase: "idle",
  interim: "",
  transcript: "",
  ack: "",
  error: null,
  turn: null,
  channel: "voice",
  metrics: {},
};

export function voiceReducer(state, action) {
  switch (action.type) {
    case "request":
      return { ...state, phase: "requesting_permission", interim: "", transcript: "", error: null, metrics: { startedAt: action.at } };
    case "listening":
      return { ...state, phase: "listening", metrics: { ...state.metrics, listeningAt: action.at } };
    case "interim":
      return {
        ...state,
        phase: "listening",
        interim: action.text,
        metrics: {
          ...state.metrics,
          firstInterimMs: state.metrics.firstInterimMs ?? Math.round(action.at - (state.metrics.listeningAt ?? action.at)),
        },
      };
    case "endpoint":
      return { ...state, phase: "endpointing" };
    case "transcribed":
      return { ...state, phase: "transcribing", transcript: action.text, interim: action.text };
    case "submit":
      return {
        ...state,
        phase: "understanding",
        transcript: action.text,
        interim: "",
        ack: action.ack,
        error: null,
        channel: action.channel,
        metrics: {
          ...(action.channel === "voice" ? state.metrics : {}),
          speechMs: action.channel === "voice" && state.metrics.listeningAt ? Math.round(action.at - state.metrics.listeningAt) : undefined,
          submittedAt: action.at,
        },
      };
    case "result":
      return {
        ...state,
        phase: action.turn.state === "confirming" ? "confirming" : "executing",
        turn: action.turn,
        ack: "",
        metrics: {
          ...state.metrics,
          responseMs: Math.round(action.at - (state.metrics.submittedAt ?? action.at)),
          serverMs: action.turn.metrics?.total_ms,
        },
      };
    case "speaking":
      return {
        ...state,
        phase: "speaking",
        metrics: { ...state.metrics, firstAudioMs: Math.round(action.at - (state.metrics.submittedAt ?? action.at)) },
      };
    case "done":
      return { ...state, phase: state.turn?.state === "confirming" ? "confirming" : "idle", ack: "" };
    case "error":
      return { ...state, phase: "error", error: action.error, ack: "", interim: "" };
    case "cancel":
      return { ...initialVoiceState, turn: state.turn, metrics: state.metrics };
    default:
      return state;
  }
}

export function acknowledgementFor(text) {
  const lower = text.toLowerCase();
  if (/\b(late|overran|behind|delayed|lost|came up|went over)\b/.test(lower)) return "Got it — checking what that delay affects…";
  if (/\b(undo|revert|put it back)\b/.test(lower)) return "Undoing that…";
  if (/^(yes|yeah|confirm|apply|go with|do it)/.test(lower)) return "Applying…";
  if (/\b(don'?t|instead|shorten|keep)\b/.test(lower)) return "Okay, adjusting…";
  return "One moment…";
}

const VoiceSessionContext = createContext(null);

export function VoiceSessionProvider({
  provider,
  synthesis,
  language = "en-IN",
  voiceOutput = false,
  autoListen = true,
  silenceMs = 1100,
  onUtterance,
  onEvent,
  children,
}) {
  const [state, rawDispatch] = useReducer(voiceReducer, initialVoiceState);
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;
  const dispatch = useCallback((action) => {
    onEventRef.current?.(action);
    rawDispatch(action);
  }, []);
  const sessionRef = useRef(null);
  const silenceRef = useRef(null);
  const interimRef = useRef("");
  const phaseRef = useRef(state.phase);
  const failedRef = useRef(false);
  const onUtteranceRef = useRef(onUtterance);
  const startRef = useRef(null);
  const speechRef = useRef(0);
  phaseRef.current = state.phase;
  useEffect(() => {
    onUtteranceRef.current = onUtterance;
  }, [onUtterance]);

  const clearSilence = () => {
    if (silenceRef.current) window.clearTimeout(silenceRef.current);
    silenceRef.current = null;
  };

  const releaseMic = useCallback(() => {
    clearSilence();
    sessionRef.current?.abort();
    sessionRef.current = null;
  }, []);

  const submit = useCallback(
    async (text, channel = "voice") => {
      const message = (text || "").trim();
      if (!message) return null;
      releaseMic();
      dispatch({ type: "submit", text: message, channel, ack: acknowledgementFor(message), at: performance.now() });
      let turn;
      try {
        turn = await onUtteranceRef.current?.(message, channel);
      } catch {
        dispatch({ type: "error", error: classifyVoiceError("service") });
        return null;
      }
      if (!turn) {
        dispatch({ type: "done" });
        return null;
      }
      dispatch({ type: "result", turn, at: performance.now() });
      const token = ++speechRef.current;
      const spoken =
        channel === "voice" && voiceOutput && synthesis?.supported && turn.say &&
        synthesis.speak(turn.say, {
          language,
          onStart: () => token === speechRef.current && dispatch({ type: "speaking", at: performance.now() }),
          onEnd: () => {
            if (token !== speechRef.current) return;
            dispatch({ type: "done" });
            if (autoListen && turn.listen_again) startRef.current?.();
          },
        });
      if (!spoken) dispatch({ type: "done" });
      return turn;
    },
    [autoListen, language, releaseMic, synthesis, voiceOutput],
  );

  const start = useCallback(async () => {
    if (phaseRef.current === "speaking") {
      speechRef.current += 1;
      synthesis?.cancel();
    }
    if (["listening", "requesting_permission", "endpointing"].includes(phaseRef.current)) return;
    if (!provider?.supported) {
      dispatch({ type: "error", error: provider?.reason ? { code: "unsupported", message: provider.reason, recoverable: false } : classifyVoiceError("unsupported") });
      return;
    }
    failedRef.current = false;
    interimRef.current = "";
    dispatch({ type: "request", at: performance.now() });
    if ((await provider.permission?.()) === "denied") {
      dispatch({ type: "error", error: classifyVoiceError("not-allowed") });
      return;
    }
    try {
      sessionRef.current = provider.start({
        language,
        onStart: () => dispatch({ type: "listening", at: performance.now() }),
        onInterim: (text) => {
          interimRef.current = text;
          dispatch({ type: "interim", text, at: performance.now() });
          clearSilence();
          silenceRef.current = window.setTimeout(() => {
            dispatch({ type: "endpoint" });
            sessionRef.current?.stop();
          }, silenceMs);
        },
        onError: (error) => {
          failedRef.current = true;
          releaseMic();
          dispatch({ type: "error", error });
        },
        onEnd: (finalText) => {
          clearSilence();
          sessionRef.current = null;
          if (failedRef.current) return;
          const text = (finalText || interimRef.current || "").trim();
          if (text) {
            dispatch({ type: "transcribed", text });
            submit(text, "voice");
          }
          else dispatch({ type: "error", error: classifyVoiceError("no-speech") });
        },
      });
    } catch {
      dispatch({ type: "error", error: classifyVoiceError("start-failed") });
    }
  }, [language, provider, releaseMic, silenceMs, submit, synthesis]);
  startRef.current = start;

  const stop = useCallback(() => {
    clearSilence();
    if (sessionRef.current) {
      dispatch({ type: "endpoint" });
      sessionRef.current.stop();
    }
  }, []);

  const cancel = useCallback(() => {
    failedRef.current = true;
    releaseMic();
    speechRef.current += 1;
    synthesis?.cancel();
    dispatch({ type: "cancel" });
  }, [releaseMic, synthesis]);

  const toggle = useCallback(() => {
    if (["listening", "endpointing"].includes(phaseRef.current)) stop();
    else start();
  }, [start, stop]);

  useEffect(() => () => {
    clearSilence();
    sessionRef.current?.abort();
  }, []);

  const value = useMemo(
    () => ({
      ...state,
      label: PHASE_LABELS[state.phase],
      busy: ["understanding", "executing"].includes(state.phase),
      active: ["requesting_permission", "listening", "endpointing"].includes(state.phase),
      supported: Boolean(provider?.supported),
      providerLabel: provider?.label,
      start,
      stop,
      cancel,
      retry: start,
      toggle,
      submit,
    }),
    [cancel, provider, start, state, stop, submit, toggle],
  );
  return <VoiceSessionContext.Provider value={value}>{children}</VoiceSessionContext.Provider>;
}

export function useVoiceSession() {
  const value = useContext(VoiceSessionContext);
  if (!value) throw new Error("useVoiceSession must be used inside VoiceSessionProvider");
  return value;
}
