import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { VoiceAssistant } from "./VoiceAssistant";

describe("VoiceAssistant", () => {
  beforeEach(() => {
    window.speechSynthesis = { cancel: vi.fn(), speak: vi.fn() };
  });

  it("shows a confirmation gate and sends an explicit yes", () => {
    const onSend = vi.fn();
    render(
      <VoiceAssistant
        turn={{ say: "Create Prepare demo for 60 minutes?", state: "confirming", requires_confirmation: true, pending_action: { intent: "task.create" } }}
        preferences={{ voice_input: true, voice_output: false, language: "en-IN" }}
        onSend={onSend}
        onOpenChat={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByLabelText("Talk to Plan B"));
    fireEvent.click(screen.getByText("Confirm"));
    expect(onSend).toHaveBeenCalledWith("yes", "voice");
  });
});
