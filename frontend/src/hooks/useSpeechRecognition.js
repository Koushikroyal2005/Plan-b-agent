import { useCallback, useEffect, useRef, useState } from "react";

export function useSpeechRecognition({ language = "en-IN", onTranscript, onInterim }) {
  const recognitionRef = useRef(null);
  const keepListeningRef = useRef(false);
  const discardRef = useRef(false);
  const finalRef = useRef("");
  const onTranscriptRef = useRef(onTranscript);
  const onInterimRef = useRef(onInterim);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState(null);
  const SpeechRecognition = typeof window === "undefined"
    ? null
    : window.SpeechRecognition || window.webkitSpeechRecognition;

  useEffect(() => { onTranscriptRef.current = onTranscript; }, [onTranscript]);
  useEffect(() => { onInterimRef.current = onInterim; }, [onInterim]);

  const publish = useCallback((interim = "") => {
    const text = [finalRef.current, interim].filter(Boolean).join(" ").replace(/\s+/g, " ").trim();
    onInterimRef.current?.(text);
  }, []);

  const finish = useCallback(() => {
    const text = finalRef.current.replace(/\s+/g, " ").trim();
    finalRef.current = "";
    onInterimRef.current?.(text);
    if (text && !discardRef.current) onTranscriptRef.current?.(text);
    discardRef.current = false;
  }, []);

  const createRecognition = useCallback(() => {
    if (!SpeechRecognition) return null;
    const recognition = new SpeechRecognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = true;
    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const segment = event.results[index][0].transcript.trim();
        if (!segment) continue;
        if (event.results[index].isFinal) finalRef.current = `${finalRef.current} ${segment}`.trim();
        else interim = `${interim} ${segment}`.trim();
      }
      publish(interim);
    };
    recognition.onerror = (event) => {
      if (event.error === "aborted") return;
      setError(event.error || "recognition-error");
      if (["not-allowed", "service-not-allowed", "audio-capture"].includes(event.error)) {
        keepListeningRef.current = false;
        setListening(false);
      }
    };
    recognition.onend = () => {
      if (keepListeningRef.current) {
        window.setTimeout(() => {
          try { recognition.start(); }
          catch { keepListeningRef.current = false; setListening(false); finish(); }
        }, 120);
        return;
      }
      recognitionRef.current = null;
      setListening(false);
      finish();
    };
    return recognition;
  }, [SpeechRecognition, finish, language, publish]);

  const start = useCallback(() => {
    if (!SpeechRecognition || keepListeningRef.current) return false;
    setError(null);
    discardRef.current = false;
    keepListeningRef.current = true;
    const recognition = createRecognition();
    recognitionRef.current = recognition;
    try {
      recognition.start();
      setListening(true);
      return true;
    } catch {
      keepListeningRef.current = false;
      setError("start-failed");
      return false;
    }
  }, [SpeechRecognition, createRecognition]);

  const stop = useCallback(() => {
    keepListeningRef.current = false;
    if (recognitionRef.current) recognitionRef.current.stop();
    else finish();
  }, [finish]);

  const cancel = useCallback(() => {
    discardRef.current = true;
    keepListeningRef.current = false;
    finalRef.current = "";
    onInterimRef.current?.("");
    recognitionRef.current?.abort();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const reset = useCallback(() => {
    finalRef.current = "";
    onInterimRef.current?.("");
  }, []);
  const toggle = useCallback(() => listening ? (stop(), true) : start(), [listening, start, stop]);

  useEffect(() => () => {
    keepListeningRef.current = false;
    discardRef.current = true;
    recognitionRef.current?.abort();
  }, []);

  return { supported: Boolean(SpeechRecognition), listening, error, toggle, start, stop, cancel, reset };
}
