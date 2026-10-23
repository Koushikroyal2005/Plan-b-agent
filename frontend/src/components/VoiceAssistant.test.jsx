import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { VoiceAssistant } from "./VoiceAssistant";
import { VoiceSessionProvider } from "../voice/VoiceSession";
import { MockSynthesis, MockVoiceProvider } from "../voice/providers";

const preferences = { voice_input: true, voice_output: false, language: "en-IN" };

function renderOrb({ turn, provider = new MockVoiceProvider(), onUtterance = vi.fn(async () => null), onUndo = vi.fn() } = {}) {
  render(
    <VoiceSessionProvider provider={provider} synthesis={new MockSynthesis()} onUtterance={onUtterance}>
      <VoiceAssistant turn={turn} preferences={preferences} onOpenChat={vi.fn()} onUndo={onUndo} />
    </VoiceSessionProvider>,
  );
  return { provider, onUtterance, onUndo };
}

describe("VoiceAssistant", () => {
  it("introduces the assistant with a contextual discovery prompt", () => {
    window.sessionStorage.removeItem("planb-voice-hint-dismissed");
    renderOrb();
    expect(screen.getByText("Hey, I’m Plan B.")).toBeInTheDocument();
    expect(screen.getByText(/Ask me to plan your day/)).toBeInTheDocument();
  });

  it("shows the confirmation choices and sends an explicit yes", async () => {
    const turn = {
      turn_id: "t1",
      channel: "voice",
      say: "Create Prepare demo for 60 minutes?",
      state: "confirming",
      requires_confirmation: true,
      choices: [{ label: "Confirm", value: "yes" }, { label: "Cancel", value: "cancel" }],
    };
    const { onUtterance } = renderOrb({ turn });
    await act(async () => fireEvent.click(screen.getByText("Confirm")));
    expect(onUtterance).toHaveBeenCalledWith("yes", "voice");
  });

  it("offers one-click undo for an applied change", () => {
    const turn = { turn_id: "t2", channel: "voice", say: "Done.", state: "completed", undo: { action_id: "a1", label: "Apply recovery" } };
    const { onUndo } = renderOrb({ turn });
    fireEvent.click(screen.getByText("Undo"));
    expect(onUndo).toHaveBeenCalledWith("a1");
  });

  it("listens, shows the live transcript, and sends it when speech ends", async () => {
    const { provider, onUtterance } = renderOrb();
    await act(async () => fireEvent.click(screen.getByLabelText("Talk to Plan B")));
    expect(screen.getByTestId("voice-phase")).toHaveTextContent("Listening");
    act(() => provider.emit("what is at risk"));
    expect(screen.getByLabelText("Voice transcript")).toHaveTextContent("what is at risk");
    await act(async () => provider.finish());
    expect(onUtterance).toHaveBeenCalledWith("what is at risk", "voice");
  });

  it("explains a blocked microphone and offers retry", async () => {
    renderOrb({ provider: new MockVoiceProvider({ permission: "denied" }) });
    await act(async () => fireEvent.click(screen.getByLabelText("Talk to Plan B")));
    expect(screen.getByRole("alert")).toHaveTextContent("Microphone access is blocked");
    expect(screen.getByText("Retry")).toBeInTheDocument();
  });
});
