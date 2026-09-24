import { describe, expect, it } from "vitest";
import { ageBucket, ageDays, toCsv } from "./CoreSystemSection";

describe("core-system breaks helpers", () => {
  it("ages a break from when it was first seen, into the tab's buckets", () => {
    const now = new Date("2026-09-24T12:00:00Z");
    expect(ageDays("2026-09-20T06:00:00Z", now)).toBe(4);
    expect(ageBucket(4)).toBe("0-7 days");
    expect(ageBucket(12)).toBe("8-30 days");
    expect(ageBucket(45)).toBe("30+ days");
    expect(ageDays(null, now)).toBeNull();
  });

  it("exports the filtered breaks as CSV, quoting what needs quoting", () => {
    const csv = toCsv([{ entity_id: "C1", source_value: 'AL-HASSAN, "TRADING"', recurring: true }], [["entity_id", "Record"], ["source_value", "Core system"], ["recurring", "Recurring"]]);
    expect(csv).toBe('Record,Core system,Recurring\nC1,"AL-HASSAN, ""TRADING""",true');
  });
});
