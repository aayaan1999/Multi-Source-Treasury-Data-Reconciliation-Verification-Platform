import { describe, expect, it } from "vitest";
import { withBankTotal } from "./CountryBreakdown";

const ROWS = [
  { country: "Lebanon", customer_count: 3, deposits_usd: 300, loans_usd: 900, npl_loans_usd: 90, transaction_count: 5, transaction_volume_usd: 70 },
  { country: "Qatar", customer_count: 2, deposits_usd: 100, loans_usd: 100, npl_loans_usd: 0, transaction_count: 2, transaction_volume_usd: 30 },
];

describe("country view totals", () => {
  it("adds a bank-wide row whose bad-loan ratio comes from the sums, not an average", () => {
    const total = withBankTotal(ROWS).at(-1);
    expect(total).toMatchObject({ country: "Bank-wide", customer_count: 5, loans_usd: 1000, npl_loans_usd: 90, transaction_count: 7 });
    expect(total.npl_ratio_pct).toBeCloseTo(9);          // 90 / 1000, not the average of 10% and 0%
    expect(total.loan_share_pct).toBe(100);
  });

  it("gives each country its share of the bank's loans", () => {
    expect(withBankTotal(ROWS).slice(0, 2).map((r) => r.loan_share_pct)).toEqual([90, 10]);
  });

  it("copes with no loans at all", () => {
    expect(withBankTotal([{ country: "X", loans_usd: 0, npl_loans_usd: 0 }]).at(-1).npl_ratio_pct).toBeNull();
  });
});
