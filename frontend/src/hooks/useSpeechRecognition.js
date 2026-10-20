import { useCallback, useEffect, useRef, useState } from "react";

export function useSpeechRecognition({ language = "en-IN", onTranscript }) {
  const recognitionRef = useRef(null);
  const [listening, setListening] = useState(false);
  const SpeechRecognition =
    window.SpeechRecognition || window.webkitSpeechRecognition;

  useEffect(() => () => recognitionRef.current?.stop(), []);

  const toggle = useCallback(() => {
    if (!SpeechRecognition) return false;
    if (listening) {
      recognitionRef.current?.stop();
      setListening(false);
      return true;
    }
    const recognition = new SpeechRecognition();
    recognition.lang = language;
    recognition.interimResults = false;
    recognition.continuous = false;
    recognition.onresult = (event) =>
      onTranscript(event.results[0][0].transcript);
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
    return true;
  }, [SpeechRecognition, language, listening, onTranscript]);

  return { supported: Boolean(SpeechRecognition), listening, toggle };
}
