import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReconTaskPanel from "./ReconTaskPanel";
import { api } from "../api";
import { completeTask, getVariables } from "../workflow/tasklistApi";

const ANALYST = { user_id: 1, name: "Demo Analyst", role: "analyst" };
const CFO = { user_id: 3, name: "Demo Approver", role: "approver" };
const RUN = { run_id: 5, name: "core banking files of 29 Sep 2026", tasks: 3, decided: 1, status: "OPEN" };

const PIPELINE = {
  item: { recon_id: 662, source_table: "transactions", source_country: "Lebanon", status: "WITH_TEAM", note: null,
    cfo_required: false, cfo_reason: null, decision: null, decided_by: null },
  records: [{ record_key: "TNDEMO12", flag_label: "INVALID_CHANNEL", bad_field: "channel", description: "channel 'Cheque' is not one of Branch/ATM/Mobile/Online",
    record_data: { transaction_id: "TNDEMO12", amount: 4000, channel: "Cheque", currency: "USD" } }],
  records_available: true,
  summary: {
    headline: "1,419 rows of Lebanon transactions arrived in the core banking delivery of 29 Sep 2026: 1,418 loaded, 1 rejected.",
    reasons: ["TNDEMO12: channel 'Cheque' is not one of Branch/ATM/Mobile/Online"],
    money: "Not in our books because of this: USD 4,000.00.",
    job: "Decide what happens to these rows.",
  },
  run: RUN,
};
const BREAKS = ["ACN0001", "ACN0002", "ACN0003"].map((id, i) => ({
  exception_id: i + 1, entity_type: "account", entity_id: id, field_name: "balance", source_value: "1015.0000", canonical_value: "1000.00",
  mismatch_type: "VALUE_MISMATCH", status: "OPEN", times_seen: 1, recurring: false,
}));
const GROUP = {
  group_id: 21, source_system: "neon", mismatch_type: "VALUE_MISMATCH", status: "OPEN", cfo_required: false, cfo_reason: null,
  decision: null, decided_by: null, breaks: BREAKS, corrections: [], run: RUN,
  summary: { headline: "3 accounts have a balance 15.00 higher in core banking than in our data (45.00 in total).", reasons: [], money: null, job: "Decide for the whole group." },
};
const MISSING = { ...GROUP, group_id: 22, mismatch_type: "MISSING_IN_CANONICAL", cfo_required: true, cfo_reason: "a missing record",
  breaks: [{ ...BREAKS[0], entity_type: "customer", entity_id: "CB-EXTRA-001", field_name: null, source_value: null, canonical_value: null, mismatch_type: "MISSING_IN_CANONICAL" }] };
const RUN_DETAIL = {
  ...RUN, source_system: "CORE_CSV", status: "IN_SIGNOFF",
  summary: { headline: "All 2 tasks from the core banking files of 29 Sep 2026 are decided: 1 accepted, 1 corrected.", job: "Check the decisions, then sign off." },
  tasks: [
    { kind: "reconciliation", id: 656, title: "Lebanon accounts: 1 row not loaded (unknown currency)", decision: "CORRECT", decided_by: 2, decided_by_name: "Demo Reviewer", approved_by_name: "Demo Approver", cfo_required: true, fixes: 1, decided: true, awaiting_cfo: false },
    { kind: "reconciliation", id: 662, title: "Lebanon transactions: 1 row not loaded (unknown channel)", decision: "ACCEPT", decided_by: 1, decided_by_name: "Demo Analyst", approved_by_name: null, cfo_required: false, fixes: 0, decided: true, awaiting_cfo: false },
  ],
};

vi.mock("../api", () => ({
  api: {
    pipelineRecords: vi.fn(),
    pipelineCorrections: vi.fn(async () => []),
    proposeCorrection: vi.fn(async () => ({ correction_id: 1 })),
    reconGroup: vi.fn(),
    reconRunDetail: vi.fn(),
    exceptionComments: vi.fn(async () => []),
    addExceptionComment: vi.fn(async () => ({})),
  },
}));
vi.mock("../workflow/tasklistApi", () => ({ completeTask: vi.fn(async () => null), getVariables: vi.fn(async () => ({})) }));

beforeEach(() => {
  vi.clearAllMocks();
  api.pipelineRecords.mockResolvedValue(PIPELINE);
  api.reconGroup.mockImplementation(async (id) => (String(id) === "22" ? MISSING : GROUP));
  api.reconRunDetail.mockResolvedValue(RUN_DETAIL);
  getVariables.mockResolvedValue({});
});

const task = (kind, key, step, title) => ({
  id: `t-${key}-${step}`, taskDefinitionId: step, vars: { recordType: kind, recordKey: String(key), title },
});
function show(t, user = ANALYST) {
  const onDone = vi.fn();
  render(<ReconTaskPanel task={t} user={user} onDone={onDone} onClose={() => {}} />);
  return onDone;
}

describe("a pipeline gap at team review", () => {
  it("says what happened, why each row was rejected, and what to decide, with the bad field highlighted", async () => {
    show(task("reconciliation", 662, "UserTask_TeamReview", "Lebanon transactions: 1 row not loaded (unknown channel)"));
    expect(await screen.findByText(PIPELINE.summary.headline)).toBeTruthy();
    expect(screen.getByText("TNDEMO12: channel 'Cheque' is not one of Branch/ATM/Mobile/Online")).toBeTruthy();
    expect(screen.getByText("Not in our books because of this: USD 4,000.00.")).toBeTruthy();
    expect(screen.getByText("channel: Cheque").getAttribute("style")).toContain("var(--critical)");
    expect(screen.getByText("currency: USD").getAttribute("style")).toBeNull();
    expect(screen.getByText(/Part of the core banking files of 29 Sep 2026: 1 of 3 tasks decided/)).toBeTruthy();
    const steps = within(screen.getByRole("list", { name: "Steps" }));
    expect(steps.getByText("Team review").closest("li").getAttribute("aria-current")).toBe("step");
    expect(steps.getByText("Deciding now")).toBeTruthy();
    expect(steps.getByText("Not needed, unless a data fix is proposed")).toBeTruthy();
  });

  it("needs a comment, then completes the task with the decision and who made it", async () => {
    const onDone = show(task("reconciliation", 662, "UserTask_TeamReview"));
    await userEvent.click(await screen.findByRole("button", { name: "Approve changes" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Say why in a comment/);
    expect(completeTask).not.toHaveBeenCalled();
    await userEvent.type(screen.getByLabelText("Comment"), "Cheque deposits are out of scope");
    await userEvent.click(screen.getByRole("button", { name: "Approve changes" }));
    expect(api.addExceptionComment).toHaveBeenCalledWith({ source_table: "pipeline_reconciliation", record_key: "662", flag_label: "RECONCILIATION", comment_text: "Cheque deposits are out of scope" });
    expect(completeTask).toHaveBeenCalledWith("t-662-UserTask_TeamReview", { decision: "ACCEPT", decidedByUserId: 1, excludedIds: [] });
    expect(onDone).toHaveBeenCalled();
  });

  it("won't choose Assign to CFO until a right value is entered", async () => {
    show(task("reconciliation", 662, "UserTask_TeamReview"));
    await userEvent.type(await screen.findByLabelText("Comment"), "mistyped channel");
    await userEvent.click(screen.getByRole("button", { name: "Assign to CFO" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Enter the right value for at least one row first/);
    expect(completeTask).not.toHaveBeenCalled();
    // The only rejected row and its bad field are picked already.
    expect(screen.getByLabelText("Row").value).toBe("TNDEMO12");
    expect(screen.getByLabelText("Field").value).toBe("channel");
    await userEvent.type(screen.getByLabelText("Right value"), "Branch");
    await userEvent.click(screen.getByRole("button", { name: "Save value" }));
    expect(api.proposeCorrection).toHaveBeenCalledWith(662, { record_key: "TNDEMO12", field_name: "channel", new_value: "Branch" });
  });

  it("shows why the last attempt wasn't saved, and the CFO's reason when it was sent back", async () => {
    getVariables.mockResolvedValue({
      decisionError: "This item can't be decided now.", sentBackNote: "Branch is wrong, it was an ATM",
      sentBackByName: "CFO", sentBackAt: "2026-09-30T10:00:00Z", sentBackFrom: "CFO_APPROVAL",
    });
    show(task("reconciliation", 662, "UserTask_TeamReview"));
    expect(await screen.findByText("Sent back by CFO at CFO approval on 30 Sep 2026: Branch is wrong, it was an ATM")).toBeTruthy();
    expect(screen.getByText("Not saved: This item can't be decided now.")).toBeTruthy();
  });
});

describe("a task carried over at a sign-off", () => {
  it("says since when and that it's escalated", async () => {
    api.reconGroup.mockResolvedValue({ ...GROUP, carried_count: 3, carried_since: "2026-09-27", escalated_at: "2026-09-30T05:00:00Z" });
    show(task("recon_group", 21, "UserTask_TeamReview"));
    expect(await screen.findByText(/Carried over from 27 Sep 2026: still open at 3 sign-offs, so it's a high priority\. Escalated/)).toBeTruthy();
  });
});

describe("a task sent back at run sign-off", () => {
  it("says so from the item's own record, even though its task started fresh", async () => {
    api.pipelineRecords.mockResolvedValue({ ...PIPELINE, item: { ...PIPELINE.item, sent_back_at: "2026-09-30T11:00:00Z",
      sent_back_by_name: "CFO", sent_back_from: "RUN_SIGNOFF", sent_back_note: "Check the channel again" } });
    show(task("reconciliation", 662, "UserTask_TeamReview"));
    expect(await screen.findByText("Sent back by CFO at run sign-off on 30 Sep 2026: Check the channel again")).toBeTruthy();
  });
});

describe("CFO approval", () => {
  const awaiting = { ...PIPELINE, item: { ...PIPELINE.item, status: "AWAITING_CFO", decision: "CORRECT", decided_by: 1, decided_by_name: "Demo Analyst" } };

  it("the CFO sees what was decided and why they're asked, and approves", async () => {
    api.pipelineRecords.mockResolvedValue(awaiting);
    getVariables.mockResolvedValue({ cfoReason: "a proposed data fix" });
    const onDone = show(task("reconciliation", 662, "UserTask_CfoApproval"), CFO);
    expect(await screen.findByText(/Demo Analyst decided: corrected\. The CFO approves this because of a proposed data fix/)).toBeTruthy();
    expect(screen.queryByRole("form", { name: "Enter a corrected value" })).toBeNull();          // values are locked
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(completeTask).toHaveBeenCalledWith("t-662-UserTask_CfoApproval", { cfoDecision: "APPROVE", approvedByUserId: 3 });
    expect(onDone).toHaveBeenCalled();
  });

  it("sending back needs a reason, which goes with the task", async () => {
    api.pipelineRecords.mockResolvedValue(awaiting);
    show(task("reconciliation", 662, "UserTask_CfoApproval"), CFO);
    await userEvent.click(await screen.findByRole("button", { name: "Send back to the team" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Say why you're sending it back/);
    await userEvent.type(screen.getByLabelText("Comment"), "Wrong channel");
    await userEvent.click(screen.getByRole("button", { name: "Send back to the team" }));
    expect(completeTask).toHaveBeenCalledWith("t-662-UserTask_CfoApproval", { cfoDecision: "SEND_BACK", sentBackByUserId: 3, sendBackNote: "Wrong channel" });
  });

  it("the person who decided can't approve their own decision, and only the CFO or an admin can approve", async () => {
    api.pipelineRecords.mockResolvedValue({ ...awaiting, item: { ...awaiting.item, decided_by: 3 } });
    show(task("reconciliation", 662, "UserTask_CfoApproval"), CFO);
    expect(await screen.findByText("You made this decision, so a different person has to approve it.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" }).disabled).toBe(true);
  });

  it("an analyst can't approve", async () => {
    api.pipelineRecords.mockResolvedValue(awaiting);
    show(task("reconciliation", 662, "UserTask_CfoApproval"), { user_id: 2, role: "reviewer" });
    expect(await screen.findByText("Only the CFO or the Platform Administrator can do this step.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" }).disabled).toBe(true);
  });
});

describe("a core-system break group", () => {
  it("leaves one record out and decides for the rest", async () => {
    show(task("recon_group", 21, "UserTask_TeamReview", "3 accounts: balance 15.00 higher in core banking"));
    expect(await screen.findByText(GROUP.summary.headline)).toBeTruthy();
    expect(screen.queryByText(/^Important/)).toBeNull();                                      // a small task isn't
    expect(within(screen.getByRole("table", { name: "Records that differ" })).getAllByText("+15").length).toBe(3);
    await userEvent.click(screen.getByLabelText("Leave out ACN0003"));
    await userEvent.type(screen.getByLabelText("Comment"), "fee batch");
    await userEvent.click(screen.getByRole("button", { name: "Approve all changes except 1" }));
    expect(completeTask).toHaveBeenCalledWith("t-21-UserTask_TeamReview", { decision: "ACCEPT", decidedByUserId: 1, excludedIds: [3] });
  });

  it("the reviewer can change the fixed values before correcting; the rest take core banking's value", async () => {
    show(task("recon_group", 21, "UserTask_TeamReview"));
    const box = await screen.findByLabelText("Fixed value for ACN0001");
    expect(box.value).toBe("1015");                                                  // core banking's value, tidied
    await userEvent.clear(box);
    await userEvent.type(box, "1012.50");
    await userEvent.click(screen.getByLabelText("Leave out ACN0003"));
    expect(screen.getByLabelText("Fixed value for ACN0003").disabled).toBe(true);    // left out: not fixed here
    await userEvent.type(screen.getByLabelText("Comment"), "core banking posted a fee twice on ACN0001");
    await userEvent.click(screen.getByRole("button", { name: "Assign to CFO except 1" }));
    expect(completeTask).toHaveBeenCalledWith("t-21-UserTask_TeamReview", {
      decision: "CORRECT", decidedByUserId: 1, excludedIds: [3], correctedValues: { 1: "1012.50", 2: "1015" },
    });
  });

  it("won't correct to an empty, non-numeric or unchanged value", async () => {
    show(task("recon_group", 21, "UserTask_TeamReview"));
    const box = await screen.findByLabelText("Fixed value for ACN0002");
    await userEvent.type(screen.getByLabelText("Comment"), "fix");
    for (const [value, message] of [["", /Enter the fixed value for account ACN0002/], ["lots", /balance is a number/], ["1,000.00", /same as ours/]]) {
      await userEvent.clear(box);
      if (value) await userEvent.type(box, value);
      await userEvent.click(screen.getByRole("button", { name: "Assign to CFO" }));
      expect(screen.getByRole("alert").textContent).toMatch(message);
    }
    expect(completeTask).not.toHaveBeenCalled();
  });

  it("a missing record can't be corrected from here, and the CFO approval is flagged up front", async () => {
    show(task("recon_group", 22, "UserTask_TeamReview"));
    expect((await screen.findByRole("button", { name: "Assign to CFO" })).disabled).toBe(true);
    expect(screen.getByText("Important: a missing record")).toBeTruthy();                      // tagged, with why
    expect(screen.getByText("Whatever you decide, this task goes to the CFO for approval next.")).toBeTruthy();
    expect(within(screen.getByRole("list", { name: "Steps" })).getByText("Required because of a missing record")).toBeTruthy();
  });
});

describe("run sign-off", () => {
  it("lists every decision; the CFO signs off", async () => {
    const onDone = show(task("recon_run", 5, "UserTask_RunSignoff", "Sign off the core banking files of 29 Sep 2026"), CFO);
    expect(await screen.findByText(RUN_DETAIL.summary.headline)).toBeTruthy();
    const rows = within(screen.getByRole("table", { name: "Every task in this run" })).getAllByRole("row");
    expect(rows[1].textContent).toContain("Demo Approver");
    expect(rows[2].textContent).toContain("Not needed");
    await userEvent.type(screen.getByLabelText("Comment"), "All explained");
    await userEvent.click(screen.getByRole("button", { name: "Sign off the run" }));
    expect(completeTask).toHaveBeenCalledWith("t-5-UserTask_RunSignoff", { signoffDecision: "SIGN_OFF", signedByUserId: 3, signNote: "All explained" });
    expect(onDone).toHaveBeenCalled();
  });

  it("sends named tasks back with a reason", async () => {
    show(task("recon_run", 5, "UserTask_RunSignoff"), CFO);
    await userEvent.click(await screen.findByLabelText("Send back Lebanon transactions: 1 row not loaded (unknown channel)"));
    expect(screen.getByRole("button", { name: "Sign off the run" }).disabled).toBe(true);
    await userEvent.click(screen.getByRole("button", { name: "Send back 1 task" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Say why/);
    await userEvent.type(screen.getByLabelText("Comment"), "Needs a second look");
    await userEvent.click(screen.getByRole("button", { name: "Send back 1 task" }));
    expect(completeTask).toHaveBeenCalledWith("t-5-UserTask_RunSignoff", {
      signoffDecision: "SEND_BACK", sentBackByUserId: 3, sendBackNote: "Needs a second look", sendBackTasks: [{ kind: "reconciliation", id: 662 }],
    });
  });

  it("past the cut-off, signs off the decided tasks and carries the open one, saying why", async () => {
    const open = { kind: "recon_group", id: 21, title: "3 accounts: balance 15.00 higher in core banking", decision: null, decided_by: null,
      decided_by_name: null, approved_by_name: null, cfo_required: false, fixes: 0, decided: false, awaiting_cfo: false, carried_count: 1, escalated: false };
    api.reconRunDetail.mockResolvedValue({ ...RUN_DETAIL, tasks: [...RUN_DETAIL.tasks, open] });
    show(task("recon_run", 5, "UserTask_RunSignoff"), CFO);
    const rows = within(await screen.findByRole("table", { name: "Every task in this run" })).getAllByRole("row");
    expect(rows[3].textContent).toContain("Open: carried to the next day");
    expect(rows[3].textContent).toContain("Carried over ×1");
    expect(within(rows[3]).queryByRole("checkbox")).toBeNull();                 // only decided tasks can be sent back
    await userEvent.click(screen.getByRole("button", { name: "Sign off 2 decided, carry 1" }));
    expect(screen.getByRole("alert").textContent).toMatch(/Say why the 1 open task is carried over/);
    await userEvent.type(screen.getByLabelText("Comment"), "Waiting on core banking ops");
    await userEvent.click(screen.getByRole("button", { name: "Sign off 2 decided, carry 1" }));
    expect(completeTask).toHaveBeenCalledWith("t-5-UserTask_RunSignoff", { signoffDecision: "SIGN_OFF", signedByUserId: 3, signNote: "Waiting on core banking ops" });
  });

  it("a task waiting for the CFO's own approval has to be dealt with first", async () => {
    const waiting = { ...RUN_DETAIL.tasks[0], id: 99, decision: "CORRECT", decided_by: 1, decided: false, awaiting_cfo: true, approved_by_name: null };
    api.reconRunDetail.mockResolvedValue({ ...RUN_DETAIL, tasks: [RUN_DETAIL.tasks[1], waiting] });
    show(task("recon_run", 5, "UserTask_RunSignoff"), { user_id: 4, role: "admin" });
    expect(await screen.findByText("Waiting for your approval")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign off the run" }).disabled).toBe(true);
  });

  it("anyone who decided a task in the run can't sign it off", async () => {
    show(task("recon_run", 5, "UserTask_RunSignoff"), { user_id: 1, role: "admin" });
    expect(await screen.findByText("You decided 1 task in this run, so a different person has to sign it off.")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Sign off the run" }).disabled).toBe(true);
  });
});
