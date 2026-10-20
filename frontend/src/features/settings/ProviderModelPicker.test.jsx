import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ProviderModelPicker } from "./ProviderModelPicker";

afterEach(() => vi.unstubAllGlobals());

describe("ProviderModelPicker", () => {
  it("loads account models and activates a tested selection", async () => {
    const responses = [
      {
        items: ["openai/gpt-oss-20b", "meta/llama-3.3-70b-instruct"],
        active: "openai/gpt-oss-20b",
      },
      {
        ok: true,
        model: "meta/llama-3.3-70b-instruct",
        reply: "Plan B provider ready",
      },
    ];
    vi.stubGlobal(
      "fetch",
      vi.fn(async () => ({ ok: true, json: async () => responses.shift() })),
    );
    const notify = vi.fn();
    const onChanged = vi.fn();
    const user = userEvent.setup();
    render(
      <ProviderModelPicker
        activeModel="openai/gpt-oss-20b"
        configured
        notify={notify}
        onChanged={onChanged}
      />,
    );
    await screen.findByText(/2 account models found/i);
    await user.selectOptions(
      screen.getByLabelText("Available model"),
      "meta/llama-3.3-70b-instruct",
    );
    await user.click(screen.getByRole("button", { name: /activate & test/i }));
    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(fetch).toHaveBeenLastCalledWith(
      "/api/provider/model",
      expect.objectContaining({ method: "PUT" }),
    );
  });
});
