import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VoiceSessionProvider, initialVoiceState, useVoiceSession, voiceReducer } from "./VoiceSession";
import { MockSynthesis, MockVoiceProvider, StreamingASRProvider, WisprFlowProvider, classifyVoiceError, selectVoiceProvider } from "./providers";

function setup({ provider = new MockVoiceProvider(), synthesis = new MockSynthesis(), turn = { turn_id: "t", say: "Done.", state: "completed" }, ...props } = {}) {
  const session = { current: null };
  const phases = ["idle"];
  let replayed = initialVoiceState;
  const onEvent = (action) => {
    replayed = voiceReducer(replayed, action);
    if (phases[phases.length - 1] !== replayed.phase) phases.push(replayed.phase);
  };
  const onUtterance = vi.fn(async () => turn);
  function Probe() {
    session.current = useVoiceSession();
    return null;
  }
  render(
    <VoiceSessionProvider provider={provider} synthesis={synthesis} voiceOutput onUtterance={onUtterance} onEvent={onEvent} {...props}>
      <Probe />
    </VoiceSessionProvider>,
  );
  return { session, phases, provider, synthesis, onUtterance };
}

afterEach(() => vi.useRealTimers());

describe("voice session lifecycle", () => {
  it("moves through listening, understanding, speaking and back to idle", async () => {
    const { session, phases, provider, synthesis, onUtterance } = setup();
    await act(async () => session.current.start());
    act(() => provider.emit("plan my day"));
    await act(async () => provider.finish());
    expect(onUtterance).toHaveBeenCalledWith("plan my day", "voice");
    expect(synthesis.spoken).toEqual(["Done."]);
    act(() => synthesis.finish());
    expect(session.current.phase).toBe("idle");
    expect(phases).toEqual(["idle", "requesting_permission", "listening", "transcribing", "understanding", "executing", "speaking", "idle"]);
    expect(session.current.metrics.responseMs).toBeGreaterThanOrEqual(0);
  });

  it("ends the utterance after a pause without a button press", async () => {
    vi.useFakeTimers();
    const { session, provider, onUtterance } = setup({ silenceMs: 800 });
    await act(async () => session.current.start());
    act(() => provider.emit("what is next"));
    await act(async () => vi.advanceTimersByTime(900));
    expect(onUtterance).toHaveBeenCalledWith("what is next", "voice");
  });

  it("stops speaking and listens again when the user barges in", async () => {
    const turn = { turn_id: "t", say: "Here are two options.", state: "completed" };
    const { session, provider, synthesis } = setup({ turn });
    await act(async () => session.current.start());
    await act(async () => provider.finish("my meeting ran late"));
    expect(session.current.phase).toBe("speaking");
    await act(async () => session.current.start());
    expect(synthesis.cancelled).toBeGreaterThan(0);
    expect(session.current.phase).toBe("listening");
    expect(provider.starts).toBe(2);
  });

  it("keeps listening after a question that needs an answer", async () => {
    const turn = { turn_id: "t", say: "How long should it take?", state: "asking", listen_again: true };
    const { session, provider, synthesis } = setup({ turn });
    await act(async () => session.current.start());
    await act(async () => provider.finish("create a task"));
    await act(async () => synthesis.finish());
    expect(provider.starts).toBe(2);
    expect(session.current.phase).toBe("listening");
  });

  it("reports recognition failures instead of hanging", async () => {
    const { session, onUtterance } = setup({ provider: new MockVoiceProvider({ failWith: "audio-capture" }) });
    await act(async () => session.current.start());
    expect(session.current.phase).toBe("error");
    expect(session.current.error.message).toMatch(/No microphone/);
    expect(onUtterance).not.toHaveBeenCalled();
  });

  it("treats silence as a visible no-speech error", async () => {
    const { session, provider } = setup();
    await act(async () => session.current.start());
    await act(async () => provider.finish(""));
    expect(session.current.error.code).toBe("no-speech");
  });

  it("shows a service error when the backend is down", async () => {
    const { session, onUtterance } = setup();
    onUtterance.mockRejectedValueOnce(new Error("offline"));
    await act(async () => session.current.submit("hello", "text"));
    expect(session.current.error.code).toBe("service");
  });

  it("cancel discards the transcript and releases the mic", async () => {
    const { session, provider, onUtterance } = setup();
    await act(async () => session.current.start());
    act(() => provider.emit("never mind"));
    act(() => session.current.cancel());
    await act(async () => provider.finish());
    expect(provider.aborted).toBe(true);
    expect(onUtterance).not.toHaveBeenCalled();
    expect(session.current.phase).toBe("idle");
  });

  it("does not speak text-channel replies", async () => {
    const { session, synthesis } = setup();
    await act(async () => session.current.submit("what is at risk", "text"));
    expect(synthesis.spoken).toEqual([]);
    expect(session.current.phase).toBe("idle");
  });
});

describe("voice providers", () => {
  it("classifies browser errors into user-facing messages", () => {
    expect(classifyVoiceError("not-allowed").message).toMatch(/blocked/);
    expect(classifyVoiceError("weird-code").code).toBe("start-failed");
    expect(classifyVoiceError("unsupported").recoverable).toBe(false);
  });

  it("falls back to browser speech when Wispr Flow or streaming ASR is unavailable", () => {
    expect(WisprFlowProvider().supported).toBe(false);
    expect(StreamingASRProvider().supported).toBe(false);
    expect(selectVoiceProvider("wispr").id).toBe("browser");
  });

  it("explains an unsupported provider", async () => {
    const { session } = setup({ provider: WisprFlowProvider() });
    await act(async () => session.current.start());
    expect(session.current.error.message).toMatch(/Wispr Flow/);
  });

  it("reducer confirms instead of idling while a decision is pending", () => {
    const state = voiceReducer(initialVoiceState, { type: "result", turn: { state: "confirming" }, at: 1 });
    expect(voiceReducer(state, { type: "done" }).phase).toBe("confirming");
  });
});
