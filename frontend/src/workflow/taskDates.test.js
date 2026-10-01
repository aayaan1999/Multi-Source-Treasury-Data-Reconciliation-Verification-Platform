import { describe, expect, it } from "vitest";
import { createdAt, createdBetween, createdDay } from "./taskDates";

// Midday UTC, so the calendar day is the same in any time zone the tests run in.
const task = (creationDate) => ({ creationDate });

describe("task creation dates", () => {
  it("reads Tasklist's +0000 offset, which isn't ISO 8601", () => {
    expect(createdAt(task("2026-09-30T12:40:11.452+0000")).toISOString()).toBe("2026-09-30T12:40:11.452Z");
    expect(createdAt(task("2026-09-30T12:40:11.452Z")).toISOString()).toBe("2026-09-30T12:40:11.452Z");
  });

  it("gives the calendar day, or null when there's no usable date", () => {
    expect(createdDay(task("2026-09-30T12:00:00.000+0000"))).toBe("2026-09-30");
    expect(createdDay(task(null))).toBeNull();
    expect(createdDay(task("not a date"))).toBeNull();
  });

  it("keeps tasks created between the two days, both included; either end may be open", () => {
    const t = task("2026-09-30T12:00:00.000+0000");
    expect(createdBetween(t, "2026-09-30", "2026-09-30")).toBe(true);           // one day
    expect(createdBetween(t, "2026-09-28", "2026-10-01")).toBe(true);
    expect(createdBetween(t, "2026-10-01", "")).toBe(false);                     // from only
    expect(createdBetween(t, "", "2026-09-29")).toBe(false);                     // to only
    expect(createdBetween(t, "", "")).toBe(true);                                // no range: everything
  });

  it("drops a task with no creation date only when a range is set", () => {
    expect(createdBetween(task(null), "", "")).toBe(true);
    expect(createdBetween(task(null), "2026-09-30", "")).toBe(false);
  });
});
