import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import GroupReviewPanel, { decisionLabel } from "./GroupReviewPanel";
import { api } from "../api";
import { completeTask, getVariables } from "../workflow/tasklistApi";

const BREAKS = ["A100", "A101", "A102", "A103"].map((id, i) => ({
  exception_id: i + 1, entity_id: id, field_name: "balance", source_value: "1015.00", canonical_value: "1000.00",
  status: "OPEN", times_seen: 1, recurring: false,
}));

vi.mock("../api", () => ({
  api: {
    reconGroup: vi.fn(async () => ({ group_id: 7, important: false, break_count: 4, total_difference: 60, largest_difference: 15, due_date: "2026-09-27", requires_second_approval: true, breaks: BREAKS })),
    exceptionComments: vi.fn(async () => []),
    addExceptionComment: vi.fn(async () => ({})),
  },
}));
vi.mock("../workflow/tasklistApi", () => ({
  completeTask: vi.fn(async () => null),
  getVariables: vi.fn(async () => ({ decision: "ACCEPT", excludedIds: [4] })),
}));

beforeEach(() => vi.clearAllMocks());

describe("reconciliation group popup", () => {
  it("words the bulk decision, including carve-outs", () => {
    expect(decisionLabel("Accept", 0, 4)).toBe("Accept all");
    expect(decisionLabel("Accept", 1, 4)).toBe("Accept all except 1");
    expect(decisionLabel("Accept", 0, 1)).toBe("Accept");
  });

  it("the reviewer accepts all but one break; the left-out one goes back for its own review", async () => {
    render(<GroupReviewPanel task={{ id: "t7", taskDefinitionId: "UserTask_ReviewGroup", vars: { recordKey: "7", title: "Account balance +15.00 · 4 accounts · neon" } }} user={{ user_id: 2 }} onDone={() => {}} onClose={() => {}} />);
    await userEvent.click(await screen.findByLabelText("Leave out A103"));
    await userEvent.type(screen.getByLabelText("Comment"), "late fee batch");
    await userEvent.click(screen.getByRole("button", { name: "Accept all except 1" }));
    expect(completeTask).toHaveBeenCalledWith("t7", { decision: "ACCEPT", excludedIds: [4], decidedByUserId: 2 });
  });

  it("the second approver sees what was decided and approves it", async () => {
    render(<GroupReviewPanel task={{ id: "t8", taskDefinitionId: "UserTask_SecondApproval", vars: { recordKey: "7" } }} user={{ user_id: 3 }} onDone={() => {}} onClose={() => {}} />);
    expect(await screen.findByText(/leaving out 1 break/)).toBeTruthy();
    expect(screen.queryByLabelText("Leave out A100")).toBeNull();
    await userEvent.type(screen.getByLabelText("Comment"), "checked");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(completeTask).toHaveBeenCalledWith("t8", { approvalDecision: "APPROVE", approvedByUserId: 3 });
  });

  it("the reviewer who decided can't also give the second approval", async () => {
    getVariables.mockResolvedValueOnce({ decision: "ACCEPT", excludedIds: [], decidedByUserId: 3 });
    render(<GroupReviewPanel task={{ id: "t9", taskDefinitionId: "UserTask_SecondApproval", vars: { recordKey: "7" } }} user={{ user_id: 3 }} onDone={() => {}} onClose={() => {}} />);
    expect(await screen.findByText(/someone else has to approve it/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "Approve" }).disabled).toBe(true);
    expect(screen.getByRole("button", { name: "Return to reviewer" }).disabled).toBe(true);
  });

  it("a group whose breaks were all resolved elsewhere can still be closed", async () => {
    api.reconGroup.mockResolvedValueOnce({ group_id: 7, important: true, break_count: 1, due_date: "2026-09-27", breaks: [{ ...BREAKS[0], status: "ACCEPTED" }] });
    render(<GroupReviewPanel task={{ id: "t10", taskDefinitionId: "UserTask_ReviewGroup", vars: { recordKey: "7" } }} user={{ user_id: 2 }} onDone={() => {}} onClose={() => {}} />);
    expect(await screen.findByText(/already been resolved/)).toBeTruthy();
    await userEvent.type(screen.getByLabelText("Comment"), "resolved by admin override");
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    expect(completeTask).toHaveBeenCalledWith("t10", { decision: "ACCEPT", excludedIds: [], decidedByUserId: 2 });
  });

  it("a retry after a failed completion doesn't post the comment twice", async () => {
    completeTask.mockRejectedValueOnce(new Error("Tasklist request failed (504)"));
    render(<GroupReviewPanel task={{ id: "t11", taskDefinitionId: "UserTask_ReviewGroup", vars: { recordKey: "7" } }} user={{ user_id: 2 }} onDone={() => {}} onClose={() => {}} />);
    await userEvent.type(await screen.findByLabelText("Comment"), "late fee batch");
    await userEvent.click(screen.getByRole("button", { name: "Accept all" }));
    expect(await screen.findByText(/504/)).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Accept all" }));
    expect(api.addExceptionComment).toHaveBeenCalledTimes(1);
    expect(completeTask).toHaveBeenCalledTimes(2);
  });
});
