import { describe, expect, it } from "vitest";
import { AGEING_RANGES, concentration, coverageStatus, describeFilters, loanParams, parseFilters, topStrip } from "./derive";

const params = (q) => new URLSearchParams(q);

describe("top strip", () => {
  const stages = [{ outstanding_usd: 800, provisions_usd: 8 }, { outstanding_usd: 200, provisions_usd: 32 }];
  const products = [{ bad_loan_outstanding_usd: 60 }, { bad_loan_outstanding_usd: 40 }];
  it("derives gross loans, bad-loan ratio and coverage", () => {
    const t = topStrip(stages, products);
    expect(t.grossLoans).toBe(1000);
    expect(t.nplRatio).toBe(10);
    expect(t.provisions).toBe(40);
    expect(t.coverageRatio).toBe(40);
  });
  it("never invents a ratio from nothing, and cost of risk is unavailable", () => {
    const t = topStrip([], []);
    expect(t.nplRatio).toBeNull();
    expect(t.coverageRatio).toBeNull();
    expect(t.costOfRisk).toBeNull();
  });
  it("concentration and coverage status", () => {
    expect(concentration([{ outstanding_usd: 250 }, { outstanding_usd: 250 }], 1000)).toEqual({ count: 2, pct: 50 });
    expect(concentration([], 0).pct).toBeNull();
    expect(coverageStatus(49.9)).toBe("watch");
    expect(coverageStatus(50)).toBe("good");
    expect(coverageStatus(null)).toBe("unknown");
  });
});

describe("filters in the URL", () => {
  it("Screen 1's NPL tile link means bad loans only", () => {
    expect(parseFilters(params("filter=npl"))).toEqual({ bad: "1" });
  });
  it("turns filters into the loans query, incl. ageing ranges and the 90-day bad-loan floor", () => {
    expect(loanParams({ product: "SME", branch: "B1", ageing: "31-60" })).toEqual({ product: "SME", branch_id: "B1", min_days_past_due: 30, max_days_past_due: 59 });
    expect(loanParams({ ageing: "180+" })).toEqual({ min_days_past_due: 180 });
    expect(loanParams({ ageing: "1-30", bad: "1" })).toEqual({ min_days_past_due: 90, max_days_past_due: 29 });
    expect(loanParams({ bad: "1" })).toEqual({ min_days_past_due: 90 });
    expect(loanParams({})).toEqual({});
  });
  it("ageing buckets don't overlap", () => {
    const ranges = Object.values(AGEING_RANGES);
    for (let i = 1; i < ranges.length; i++) expect(ranges[i][0]).toBe(ranges[i - 1][1] === null ? NaN : ranges[i - 1][1] + 1);
  });
  it("describes active filters in words", () => {
    expect(describeFilters({ branch: "B1", stage: "3" }, { B1: "Beirut Main" }).map((c) => c[1])).toEqual(["Branch: Beirut Main", "Stage 3 — already bad"]);
  });
});
