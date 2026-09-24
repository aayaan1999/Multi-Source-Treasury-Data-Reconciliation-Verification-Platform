import { describe, expect, it } from "vitest";
import { byUrgency, daysLeftText, isOverdue, taskDue } from "./taskDue";

const DUE_DAYS = { HIGH: 2, MEDIUM: 5, LOW: 10, DATA_QUALITY: 5, RECONCILIATION: 3 };
const TODAY = new Date(2026, 8, 24);   // 24 Sep 2026, local
const task = (vars, creationDate = "2026-09-20T10:00:00.000+0000") => ({ vars, creationDate });

describe("task deadlines", () => {
  it("a case keeps its own due date; other tasks are due N days after creation", () => {
    expect(taskDue(task({ recordType: "fraud_case", dueDate: "2026-09-26" }), DUE_DAYS)).toBe("2026-09-26");
    expect(taskDue(task({ recordType: "data_quality" }), DUE_DAYS)).toBe("2026-09-25");
    expect(taskDue(task({ recordType: "reconciliation" }), DUE_DAYS)).toBe("2026-09-23");
    expect(taskDue(task({ recordType: "breach" }), DUE_DAYS, { resolution_days: 7 })).toBe("2026-09-27");
    expect(taskDue(task({ recordType: "breach" }), DUE_DAYS, undefined)).toBeNull();
  });

  it("knows overdue and words the time left", () => {
    expect(isOverdue("2026-09-23", TODAY)).toBe(true);
    expect(isOverdue("2026-09-24", TODAY)).toBe(false);
    expect(daysLeftText("2026-09-23", TODAY)).toBe("1 day overdue");
    expect(daysLeftText("2026-09-24", TODAY)).toBe("Due today");
    expect(daysLeftText("2026-09-29", TODAY)).toBe("5 days left");
  });

  it("sorts overdue first, then by severity, then soonest due", () => {
    const rows = [
      { id: "medium-soon", severity: "MEDIUM", due: "2026-09-25" },
      { id: "high-later", severity: "HIGH", due: "2026-09-28" },
      { id: "overdue-low", severity: "LOW", due: "2026-09-20" },
      { id: "undated", severity: null, due: null },
      { id: "high-soon", severity: "HIGH", due: "2026-09-26" },
    ];
    expect(rows.sort(byUrgency(TODAY)).map((r) => r.id)).toEqual(["overdue-low", "high-soon", "high-later", "medium-soon", "undated"]);
  });
});
