import { describe, expect, it } from "vitest";
import { recordLabel } from "./Tasks";

const task = (vars, extra = {}) => ({ vars, ...extra });

describe("recordLabel (Tasks list 'Record' column)", () => {
  it("shows the transaction ID for fraud and transaction data-quality tasks", () => {
    expect(recordLabel(task({ sourceTable: "transactions", recordKey: "TN33073" }))).toBe("TN33073");
  });

  it("names the table for data-quality flags on other tables", () => {
    expect(recordLabel(task({ sourceTable: "loans", recordKey: "LN0059" }))).toBe("Loan LN0059");
  });

  it("shows a breach as the KPI, its value and the limit", () => {
    const breach = { metric_name: "capital_adequacy_ratio", actual_value: 12.4, threshold_value: 12.5 };
    expect(recordLabel(task({ sourceTable: "breaches", recordKey: "2" }, { breach }))).toBe("Capital ratio 12.4% (limit 12.5%)");
  });

  it("falls back to the breach number when the breach details couldn't be loaded", () => {
    expect(recordLabel(task({ sourceTable: "breaches", recordKey: "3" }))).toBe("Breach #3");
  });
});
