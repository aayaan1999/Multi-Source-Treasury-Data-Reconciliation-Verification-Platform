import { describe, expect, it } from "vitest";
import { canSee, homeOf, isMyTask, screenOf } from "./access";
import { navFor } from "./components/TopBar";
import { userFor } from "./test/users";

const task = (recordType, group) => ({ vars: { recordType }, candidateGroups: [group] });
const labels = (user) => navFor(user).map((e) => (e.group ? `${e.group}: ${e.items.map((i) => i[1]).join(", ")}` : e[1]));

describe("who sees what (specs/user-roles.md)", () => {
  it("names the screen behind each route", () => {
    expect(["/", "/kpi/car_pct", "/reports/7", "/audit-oversight", "/nowhere"].map(screenOf)).toEqual(["summary", "summary", "reports", "audit", null]);
  });

  it("each person's menu lists only their screens; a group left with one screen becomes a tab", () => {
    expect(labels(userFor("approver"))).toEqual(["Executive summary", "Portfolio & credit risk",
      "Analysis & reporting: Branch & segment, Scenario modelling, Regulatory reporting", "Reconciliation", "Tasks", "Audit & Oversight", "AI assistant"]);
    expect(labels(userFor("analyst"))).toEqual(["Data ingestion", "Executive summary", "Reconciliation", "Tasks", "AI assistant"]);
    expect(labels(userFor("compliance"))).toEqual(["Executive summary", "Tasks", "AI assistant"]);
    expect(labels(userFor("auditor"))).toContain("Analysis & reporting: Branch & segment, Regulatory reporting");
  });

  it("each person starts on their own home screen", () => {
    expect(["approver", "risk", "analyst", "auditor", "admin"].map((r) => homeOf(userFor(r)))).toEqual(["/", "/portfolio", "/tasks", "/audit-oversight", "/ingestion"]);
    expect(canSee(userFor("analyst"), "/scenario")).toBe(false);
    expect(canSee(userFor("auditor"), "/tasks")).toBe(false);
  });

  it("tasks are split by person: the analyst decides, the CFO approves and signs off", () => {
    const teamStep = task("recon_group", "operations");
    const cfoStep = task("recon_group", "cfo");
    const signOff = task("recon_run", "cfo");
    const breach = task("breach", "risk");
    const fraudCase = task("fraud_case", "operations");
    const dqFlag = task("data_quality", "compliance");
    const mine = (role) => [teamStep, cfoStep, signOff, breach, fraudCase, dqFlag].filter((t) => isMyTask(userFor(role), t));
    expect(mine("analyst")).toEqual([teamStep, dqFlag]);
    expect(mine("approver")).toEqual([cfoStep, signOff]);
    expect(mine("risk")).toEqual([breach]);
    expect(mine("compliance")).toEqual([fraudCase]);
    expect(mine("auditor")).toEqual([]);
    expect(mine("admin")).toHaveLength(6);
  });
});
