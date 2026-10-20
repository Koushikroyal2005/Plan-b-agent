import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { CalendarWorkspace } from "./CalendarWorkspace";

const tasks = [
  {
    id: "task-1",
    title: "Team meeting",
    description: "Meet at https://meet.example/plan-b",
    duration_minutes: 60,
    fixed_start: "2026-10-19T14:00",
    deadline: "2026-10-19T15:00",
    priority: "high",
    flexibility: "fixed",
    status: "open",
  },
  {
    id: "task-2",
    title: "Review notes",
    description: "",
    duration_minutes: 45,
    priority: "medium",
    flexibility: "flexible",
    status: "open",
  },
];

const day = {
  date: "2026-10-19",
  blocks: [
    {
      task_id: "task-1",
      title: "Team meeting",
      start: "2:00 PM",
      end: "3:00 PM",
      start_iso: "2026-10-19T14:00",
      minutes: 60,
      kind: "fixed",
      label: "high",
    },
  ],
  metrics: { confidence: 88, free_buffer_minutes: 90 },
};

const renderCalendar = () => {
  const props = {
    day,
    tasks,
    onRecovery: vi.fn(),
    sendMessage: vi.fn(),
    onAdd: vi.fn(),
    onPatch: vi.fn(async () => {}),
    notify: vi.fn(),
  };
  render(<CalendarWorkspace {...props} />);
  return props;
};

describe("CalendarWorkspace", () => {
  it("navigates views and opens the full day breakdown", async () => {
    const user = userEvent.setup();
    renderCalendar();
    await user.click(screen.getByRole("button", { name: "Month" }));
    expect(screen.getByText("October 2026")).toBeInTheDocument();
    const period = within(document.querySelector(".cal-period"));
    await user.click(period.getByRole("button", { name: "Next month" }));
    expect(screen.getByText("November 2026")).toBeInTheDocument();
    await user.click(period.getByRole("button", { name: "Previous month" }));
    await user.click(
      within(document.querySelector(".month-grid")).getByRole("button", {
        name: "19",
      }),
    );
    expect(await screen.findByText("DAY BREAKDOWN")).toBeInTheDocument();
    expect(
      within(document.querySelector(".day-popup")).getByText("Team meeting"),
    ).toBeInTheDocument();
  });

  it("opens, edits, and persists an event", async () => {
    const user = userEvent.setup();
    const props = renderCalendar();
    const eventButtons = screen.getAllByRole("button", {
      name: /team meeting/i,
    });
    await user.click(eventButtons.at(-1));
    expect(screen.getByText("CALENDAR EVENT")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: /meet.example/i }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Edit event" }));
    const popup = screen.getByText("Edit event").closest(".event-popup");
    const title = within(popup).getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Team retrospective");
    await user.click(
      within(popup).getByRole("button", { name: "Save changes" }),
    );
    expect(props.onPatch).toHaveBeenCalledWith(
      "task-1",
      expect.objectContaining({ title: "Team retrospective" }),
    );
    expect(props.notify).toHaveBeenCalled();
  });

  it("connects creation and recovery actions", async () => {
    const user = userEvent.setup();
    const props = renderCalendar();
    await user.click(screen.getByRole("button", { name: /new event/i }));
    await user.click(screen.getByRole("button", { name: /preview recovery/i }));
    expect(props.onAdd).toHaveBeenCalled();
    expect(props.onRecovery).toHaveBeenCalledWith(
      30,
      "Calendar schedule changed",
    );
  });
});
