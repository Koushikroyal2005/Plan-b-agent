import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AppHeader } from "./AppHeader";

const tasks = [
  {
    id: "t1",
    title: "Prepare project report",
    status: "open",
    deadline: "2026-10-21T12:00:00",
  },
];
const projects = [{ id: "p1", name: "Product launch" }];

describe("AppHeader", () => {
  it("searches tasks, projects, and navigation then routes to the result", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <AppHeader
        view="dashboard"
        tasks={tasks}
        projects={projects}
        onNavigate={onNavigate}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Search" }));
    await user.type(screen.getByPlaceholderText(/search tasks/i), "project");
    await user.click(
      screen.getByRole("button", { name: /prepare project report/i }),
    );
    expect(onNavigate).toHaveBeenCalledWith("tasks");
  });

  it("opens deadline notifications and routes to tasks", async () => {
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    render(
      <AppHeader
        view="dashboard"
        tasks={tasks}
        projects={projects}
        onNavigate={onNavigate}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Notifications" }));
    await user.click(
      screen.getByRole("button", { name: /prepare project report/i }),
    );
    expect(onNavigate).toHaveBeenCalledWith("tasks");
  });
});
