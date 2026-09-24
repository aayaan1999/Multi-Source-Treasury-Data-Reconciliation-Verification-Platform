import { describe, expect, it } from "vitest";
import { TRANSACTION_FLAGS, alertType } from "./flagTypes";

describe("alertType (Tasks list 'Type' column)", () => {
  it("never calls a large amount fraud: it is a threshold event", () => {
    expect(alertType({ recordType: "fraud", flagLabel: "LARGE_AMOUNT" })).toBe("Threshold");
  });

  it("labels the pattern rules suspicious and duplicates operational", () => {
    expect(alertType({ recordType: "fraud", flagLabel: "VELOCITY_BREACH" })).toBe("Suspicious");
    expect(alertType({ recordType: "fraud", flagLabel: "STRUCTURING_PATTERN" })).toBe("Suspicious");
    expect(alertType({ recordType: "fraud", flagLabel: "DUPLICATE_TRANSACTION" })).toBe("Operational");
  });

  it("keeps data-quality and breach tasks as they were", () => {
    expect(alertType({ recordType: "data_quality", flagLabel: "ORPHAN_CUSTOMER" })).toBe("Data quality");
    expect(alertType({ recordType: "breach", flagLabel: "CAR_BELOW_LIMIT" })).toBe("Breach");
  });

  it("falls back to a neutral label for a rule it doesn't know yet", () => {
    expect(alertType({ recordType: "fraud", flagLabel: "SOME_NEW_RULE" })).toBe("Transaction alert");
  });

  it("gives every rule a reason", () => {
    for (const info of Object.values(TRANSACTION_FLAGS)) expect(info.reason.length).toBeGreaterThan(20);
  });
});
