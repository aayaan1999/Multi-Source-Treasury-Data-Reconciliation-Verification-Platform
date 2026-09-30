import { describe, expect, it } from "vitest";
import { blockedReason, decisionLabel, stages, stepOf } from "./reconTask";

describe("reconciliation task helpers", () => {
  it("knows each step by its BPMN id or its name", () => {
    expect(stepOf({ taskDefinitionId: "UserTask_TeamReview" })).toBe("TEAM");
    expect(stepOf({ name: "CFO approval" })).toBe("CFO");
    expect(stepOf({ taskDefinitionId: "UserTask_RunSignoff" })).toBe("SIGNOFF");
    expect(stepOf({ name: "Fraud Investigation" })).toBeNull();
  });

  it("words the bulk decision, including records left out", () => {
    expect(decisionLabel("Accept", 0, 4)).toBe("Accept all");
    expect(decisionLabel("Accept", 1, 4)).toBe("Accept all except 1");
    expect(decisionLabel("Accept", 0, 1)).toBe("Accept");
  });

  it("two different people: never approve your own decision or sign off a run you decided in", () => {
    const cfo = { user_id: 3, role: "approver" };
    expect(blockedReason("TEAM", { user_id: 1, role: "analyst" })).toBeNull();
    expect(blockedReason("CFO", { user_id: 1, role: "analyst" }, { decidedBy: 2 })).toMatch(/Only the CFO/);
    expect(blockedReason("CFO", cfo, { decidedBy: 3 })).toMatch(/You made this decision/);
    expect(blockedReason("CFO", cfo, { decidedBy: 1 })).toBeNull();
    expect(blockedReason("SIGNOFF", cfo, { deciders: [1, 3, 3] })).toBe("You decided 2 tasks in this run, so a different person has to sign it off.");
    expect(blockedReason("SIGNOFF", { user_id: 4, role: "admin" }, { deciders: [1, 3] })).toBeNull();
  });

  it("the step tracker says who acts, what's happening, and why the CFO is needed", () => {
    const small = stages("reconciliation", "TEAM", { cfoRequired: false });
    expect(small.map((s) => s.state)).toEqual(["current", "skipped", "pending"]);
    expect(small.map((s) => s.detail)).toEqual(["Deciding now", "Not needed, unless a data fix is proposed", "Once every task in the run is decided"]);
    const important = stages("recon_group", "TEAM", { cfoRequired: true, cfoReason: "a total difference of 108,000.00" });
    expect(important[1]).toMatchObject({ state: "pending", who: "CFO", detail: "Required because of a total difference of 108,000.00" });
    const atCfo = stages("recon_group", "CFO", { cfoReason: "a proposed data fix" });
    expect(atCfo.map((s) => s.state)).toEqual(["done", "current", "pending"]);
    expect(atCfo[1].detail).toBe("Approving now. Required because of a proposed data fix");
    expect(stages("recon_run", "SIGNOFF").map((s) => s.label)).toEqual(["Tasks decided", "Run sign-off", "Run closed"]);
  });
});
