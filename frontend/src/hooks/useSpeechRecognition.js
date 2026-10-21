import { useCallback, useEffect, useRef, useState } from "react";

export function useSpeechRecognition({ language = "en-IN", onTranscript, onInterim }) {
  const recognitionRef = useRef(null);
  const [listening, setListening] = useState(false);
  const [error, setError] = useState(null);
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  useEffect(() => () => recognitionRef.current?.stop(), []);

  const stop = useCallback(() => {
    recognitionRef.current?.stop();
    recognitionRef.current = null;
    setListening(false);
  }, []);

  const toggle = useCallback(() => {
    if (!SpeechRecognition) return false;
    if (listening) {
      stop();
      return true;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = false;
    setError(null);
    recognition.onresult = (event) => {
      const results = Array.from(event.results);
      const transcript = results.map((result) => result[0].transcript).join(" ").trim();
      onInterim?.(transcript);
      const final = results.filter((result) => result.isFinal).map((result) => result[0].transcript).join(" ").trim();
      if (final) onTranscript(final);
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = (event) => {
      setError(event.error || "recognition-error");
      setListening(false);
    };
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
    return true;
  }, [SpeechRecognition, language, listening, onInterim, onTranscript, stop]);

  return { supported: Boolean(SpeechRecognition), listening, error, toggle, stop };
}
