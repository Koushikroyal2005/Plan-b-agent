import { useCallback, useEffect, useRef, useState } from "react";

export function useSpeechSynthesis({ enabled = true, language = "en-IN" } = {}) {
  const utteranceRef = useRef(null);
  const [speaking, setSpeaking] = useState(false);
  const supported = typeof window !== "undefined" && "speechSynthesis" in window;

  const stop = useCallback(() => {
    if (supported) window.speechSynthesis.cancel();
    utteranceRef.current = null;
    setSpeaking(false);
  }, [supported]);

  const speak = useCallback(
    (text) => {
      if (!enabled || !supported || !text) return false;
      window.speechSynthesis.cancel();
      const utterance = new SpeechSynthesisUtterance(text);
      utterance.lang = language;
      utterance.rate = 1;
      utterance.onstart = () => setSpeaking(true);
      utterance.onend = () => setSpeaking(false);
      utterance.onerror = () => setSpeaking(false);
      utteranceRef.current = utterance;
      window.speechSynthesis.speak(utterance);
      return true;
    },
    [enabled, language, supported],
  );

  useEffect(() => stop, [stop]);
  return { supported, speaking, speak, stop };
}
