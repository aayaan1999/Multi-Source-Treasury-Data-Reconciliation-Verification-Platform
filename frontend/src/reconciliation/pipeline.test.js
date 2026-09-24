import { describe, expect, it } from "vitest";
import { currencyLines, fmtAmount, gapSummary } from "./pipeline";

// The Lebanon accounts item from specs/pipeline-reconciliation.md section 7.
const lebanonAccounts = {
  USD: { received: 245000, clean: 250000, gap: -5000 },
  XYZ: { received: 50000, clean: 0, gap: 50000 },
  LBP: { received: 15000000, clean: 15000000, gap: 0 },
};

describe("pipeline reconciliation helpers", () => {
  it("lists currencies biggest gap first, whatever its sign, and never sums them", () => {
    expect(currencyLines(lebanonAccounts).map((l) => l.currency)).toEqual(["XYZ", "USD", "LBP"]);
    expect(currencyLines(lebanonAccounts)[1]).toEqual({ currency: "USD", received: 245000, clean: 250000, gap: -5000 });
  });

  it("summarises the biggest gap and counts the other currencies that moved", () => {
    expect(gapSummary(lebanonAccounts)).toBe("XYZ 50,000 · +1 more");
    expect(gapSummary({ USD: { received: 500, clean: 0, gap: 500 } })).toBe("USD 500");
  });

  it("shows a dash when no amount moved, or the table has no amounts at all", () => {
    expect(gapSummary({ QAR: { received: 30000, clean: 30000, gap: 0 } })).toBe("—");
    expect(gapSummary(null)).toBe("—");
    expect(currencyLines(null)).toEqual([]);
  });

  it("formats amounts with separators and at most 2 decimals", () => {
    expect(fmtAmount(64800)).toBe("64,800");
    expect(fmtAmount(-500.126)).toBe("-500.13");
  });
});
