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

  it("the progress line shows the CFO step as skipped only when it isn't needed", () => {
    expect(stages("reconciliation", "TEAM", { cfoRequired: false }).map((s) => s.state)).toEqual(["current", "skipped", "pending"]);
    const important = stages("recon_group", "TEAM", { cfoRequired: true, cfoReason: "a missing record" });
    expect(important[1]).toMatchObject({ state: "pending", who: "CFO", note: "a missing record" });
    expect(stages("recon_group", "CFO", { cfoReason: "a data fix is proposed" }).map((s) => s.state)).toEqual(["done", "current", "pending"]);
    expect(stages("recon_run", "SIGNOFF").map((s) => s.label)).toEqual(["Every task decided", "Run sign-off", "Run closed"]);
  });
});
