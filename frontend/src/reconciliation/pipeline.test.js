import { describe, expect, it } from "vitest";
import { correctableFields, currencyLines, fmtAmount, gapSummary, statusText, taskStep } from "./pipeline";

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


describe("CFO workflow helpers", () => {
  it("knows each step by its BPMN id or its name", () => {
    expect(taskStep({ taskDefinitionId: "UserTask_CfoReview" })).toBe("CFO_REVIEW");
    expect(taskStep({ name: "Update values" })).toBe("ASSIGNEE_UPDATE");
    expect(taskStep({ taskDefinitionId: "UserTask_CfoFinalReview" })).toBe("CFO_FINAL_REVIEW");
    expect(taskStep({ name: "Fraud Investigation" })).toBeNull();
  });

  it("words the status, naming the assignee", () => {
    expect(statusText({ status: "ASSIGNED", assigned_to_name: "Demo Reviewer" })).toBe("Assigned: Demo Reviewer");
    expect(statusText({ status: "SUBMITTED" })).toBe("Awaiting CFO approval");
  });

  it("never offers the record's key as a field to correct", () => {
    const t0009 = { transaction_id: "T0009", account_id: "ACC004", channel: "Cheque" };
    expect(correctableFields(t0009, "transactions")).toEqual(["account_id", "channel"]);
    expect(correctableFields({ date: "2026-09-01", currency_pair: "USD/LBP", rate: 0 }, "fx_rates")).toEqual(["rate"]);
  });
});
