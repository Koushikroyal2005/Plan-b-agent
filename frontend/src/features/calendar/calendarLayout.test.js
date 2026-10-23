import { describe, expect, it } from "vitest";
import {
  eventHeightPercent,
  eventHeightPx,
  layoutDayEvents,
} from "./calendarLayout";

describe("layoutDayEvents", () => {
  it("keeps non-overlapping events in a single column", () => {
    const laid = layoutDayEvents([
      { id: "a", startMinutes: 540, duration: 60 },
      { id: "b", startMinutes: 660, duration: 45 },
    ]);
    expect(laid.every((e) => e.layoutColumns === 1 && e.layoutColumn === 0)).toBe(true);
  });

  it("places overlapping events side by side", () => {
    const laid = layoutDayEvents([
      { id: "a", startMinutes: 540, duration: 90 },
      { id: "b", startMinutes: 570, duration: 90 },
      { id: "c", startMinutes: 600, duration: 60 },
    ]);
    expect(laid.find((e) => e.id === "a").layoutColumns).toBe(3);
    const columns = laid.map((e) => e.layoutColumn);
    expect(new Set(columns).size).toBe(3);
  });

  it("caps height before the next event in the same lane", () => {
    const laid = layoutDayEvents([
      { id: "break", startMinutes: 760, duration: 10, layoutColumn: 0 },
      { id: "next", startMinutes: 770, duration: 45, layoutColumn: 0 },
    ]);
    const breakEvent = laid.find((e) => e.id === "break");
    const heightPx = eventHeightPx(breakEvent, laid);
    expect(heightPx).toBeLessThan(20);
    expect(heightPx).toBeGreaterThanOrEqual(11);
    const heightPct = eventHeightPercent(breakEvent, laid);
    expect(heightPct).toBeLessThan(3);
    expect(heightPct).toBeGreaterThanOrEqual(2.4);
  });

  it("resets columns after a gap", () => {
    const laid = layoutDayEvents([
      { id: "a", startMinutes: 540, duration: 60 },
      { id: "b", startMinutes: 540, duration: 60 },
      { id: "c", startMinutes: 720, duration: 30 },
    ]);
    expect(laid.find((e) => e.id === "c").layoutColumns).toBe(1);
  });
});
