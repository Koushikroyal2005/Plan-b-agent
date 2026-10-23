const MESSAGES = {
  "not-allowed": "Microphone access is blocked. Allow the microphone for this site in your browser settings, then press Retry.",
  "service-not-allowed": "This browser blocked speech recognition. Allow it in site settings, or type instead.",
  "audio-capture": "No microphone was found. Connect one and press Retry, or type instead.",
  "no-speech": "I didn't hear anything. Press Retry and start speaking.",
  network: "Speech recognition lost its network connection. Press Retry, or type instead.",
  unsupported: "Voice input isn't available in this browser. Chrome or Edge support it; you can always type.",
  "language-not-supported": "Speech recognition doesn't support your language setting. Change it in Settings or type instead.",
  "start-failed": "The microphone couldn't start. Press Retry.",
  service: "Plan B couldn't reach the planning service. Check that the backend is running, then retry.",
};

export function classifyVoiceError(code) {
  const key = MESSAGES[code] ? code : "start-failed";
  return {
    code: key,
    message: MESSAGES[key],
    recoverable: !["unsupported", "service-not-allowed", "language-not-supported"].includes(key),
  };
}

export class BrowserSpeechProvider {
  constructor(win = typeof window === "undefined" ? undefined : window) {
    this.id = "browser";
    this.label = "Browser speech";
    this.win = win;
    this.Recognition = win?.SpeechRecognition || win?.webkitSpeechRecognition || null;
  }

  get supported() {
    return Boolean(this.Recognition);
  }

  async permission() {
    try {
      const status = await this.win?.navigator?.permissions?.query({ name: "microphone" });
      return status?.state || "prompt";
    } catch {
      return "prompt";
    }
  }

  start({ language, onStart, onInterim, onError, onEnd }) {
    const recognition = new this.Recognition();
    recognition.lang = language;
    recognition.interimResults = true;
    recognition.continuous = true;
    let finalText = "";
    let latestText = "";
    let failed = false;
    recognition.onstart = () => onStart?.();
    recognition.onresult = (event) => {
      let interim = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const segment = event.results[index][0].transcript.trim();
        if (!segment) continue;
        if (event.results[index].isFinal) finalText = `${finalText} ${segment}`.trim();
        else interim = `${interim} ${segment}`.trim();
      }
      latestText = `${finalText} ${interim}`.trim();
      onInterim?.(latestText);
    };
    recognition.onerror = (event) => {
      if (event.error === "aborted") return;
      failed = true;
      onError?.(classifyVoiceError(event.error));
    };
    recognition.onend = () => {
      // Browsers sometimes end recognition before promoting the last interim
      // segment to a final result. Preserve the latest stable transcript so a
      // user's trailing words are not silently dropped.
      if (!failed) onEnd?.((latestText || finalText).trim());
    };
    recognition.start();
    return { stop: () => recognition.stop(), abort: () => recognition.abort() };
  }
}

class UnavailableProvider {
  constructor(id, label, reason) {
    this.id = id;
    this.label = label;
    this.reason = reason;
    this.supported = false;
  }

  start({ onError }) {
    onError?.({ code: "unsupported", message: this.reason, recoverable: false });
    return { stop() {}, abort() {} };
  }
}

export const WisprFlowProvider = () =>
  new UnavailableProvider("wispr", "Wispr Flow", "Wispr Flow isn't connected yet, so Plan B uses browser speech.");

export const StreamingASRProvider = () =>
  new UnavailableProvider("streaming", "Streaming ASR", "Server-side streaming speech recognition isn't configured.");

/** Scripted provider for tests and offline demos: call emit()/finish() to simulate speech. */
export class MockVoiceProvider {
  constructor({ failWith = null, permission = "granted" } = {}) {
    this.id = "mock";
    this.label = "Mock voice";
    this.supported = true;
    this.failWith = failWith;
    this.permissionState = permission;
    this.handlers = null;
    this.aborted = false;
    this.starts = 0;
  }

  async permission() {
    return this.permissionState;
  }

  start(handlers) {
    this.handlers = handlers;
    this.aborted = false;
    this.starts += 1;
    this.text = "";
    if (this.failWith) {
      handlers.onError?.(classifyVoiceError(this.failWith));
    } else {
      handlers.onStart?.();
    }
    return {
      stop: () => !this.aborted && this.handlers?.onEnd?.(this.text),
      abort: () => {
        this.aborted = true;
      },
    };
  }

  emit(text) {
    this.text = text;
    this.handlers?.onInterim?.(text);
  }

  finish(text = this.text) {
    this.text = text;
    if (!this.aborted) this.handlers?.onEnd?.(text);
  }
}

export class BrowserSynthesis {
  constructor(win = typeof window === "undefined" ? undefined : window) {
    this.win = win;
    this.supported = Boolean(win && "speechSynthesis" in win && win.SpeechSynthesisUtterance);
  }

  speak(text, { language, onStart, onEnd }) {
    if (!this.supported || !text) return false;
    this.win.speechSynthesis.cancel();
    const utterance = new this.win.SpeechSynthesisUtterance(text);
    utterance.lang = language;
    utterance.onstart = () => onStart?.();
    utterance.onend = () => onEnd?.();
    utterance.onerror = () => onEnd?.();
    this.win.speechSynthesis.speak(utterance);
    return true;
  }

  cancel() {
    if (this.supported) this.win.speechSynthesis.cancel();
  }
}

export class MockSynthesis {
  constructor() {
    this.supported = true;
    this.spoken = [];
    this.cancelled = 0;
    this.onEnd = null;
  }

  speak(text, { onStart, onEnd }) {
    this.spoken.push(text);
    this.onEnd = onEnd;
    onStart?.();
    return true;
  }

  finish() {
    const done = this.onEnd;
    this.onEnd = null;
    done?.();
  }

  cancel() {
    this.cancelled += 1;
    this.onEnd = null;
  }
}

export function selectVoiceProvider(preferred = "browser") {
  const candidates = {
    wispr: WisprFlowProvider,
    streaming: StreamingASRProvider,
    browser: () => new BrowserSpeechProvider(),
  };
  const first = candidates[preferred]?.();
  if (first?.supported) return first;
  return new BrowserSpeechProvider();
}
