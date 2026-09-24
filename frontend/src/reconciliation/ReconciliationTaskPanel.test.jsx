import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import ReconciliationTaskPanel from "./ReconciliationTaskPanel";
import { api } from "../api";
import { completeTask } from "../workflow/tasklistApi";

const ITEM = {
  recon_id: 7, source_system: "CORE_CSV", source_country: "Lebanon", source_table: "transactions",
  received_rows: 6, clean_rows: 5, rejected_rows: 1, status: "WITH_CFO", assigned_to: null,
  amounts_by_currency: { USD: { received: 64800, clean: 63800, gap: 1000 } },
};
const T0009 = { transaction_id: "T0009", account_id: "ACC004", amount: 1000, channel: "Cheque" };

vi.mock("../api", () => ({
  api: {
    pipelineRecords: vi.fn(async () => ({
      item: ITEM, records_available: true,
      records: [{ record_key: "T0009", flag_label: "INVALID_CHANNEL", description: "channel 'Cheque' is not valid", record_data: T0009 }],
    })),
    pipelineCorrections: vi.fn(async () => []),
    exceptionComments: vi.fn(async () => []),
    assignees: vi.fn(async () => [{ user_id: 2, name: "Demo Reviewer", role: "reviewer" }]),
    addExceptionComment: vi.fn(async () => ({})),
    proposeCorrection: vi.fn(async () => ({ correction_id: 1 })),
    pipelineEvent: vi.fn(async () => ({})),
  },
}));
vi.mock("../workflow/tasklistApi", () => ({ completeTask: vi.fn(async () => null) }));

const USER = { user_id: 3, name: "Demo Approver" };
const task = (taskDefinitionId) => ({ id: "task-1", taskDefinitionId, vars: { recordType: "reconciliation", recordKey: "7" } });

function renderPanel(step) {
  const onDone = vi.fn();
  render(<ReconciliationTaskPanel task={task(step)} user={USER} onDone={onDone} onClose={() => {}} />);
  return onDone;
}

beforeEach(() => vi.clearAllMocks());

describe("reconciliation task popup", () => {
  it("CFO review: reassigning needs someone, then completes the task in Camunda before recording the step", async () => {
    const onDone = renderPanel("UserTask_CfoReview");
    await screen.findByRole("table", { name: "Rejected records" });
    expect(screen.getByRole("list", { name: "Reconciliation steps" }).querySelector("[aria-current]").textContent).toBe("CFO review");

    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));
    expect(screen.getByRole("alert").textContent).toMatch(/who to reassign/);

    await userEvent.selectOptions(screen.getByLabelText("Reassign to"), "2");
    await userEvent.type(screen.getByLabelText("Comment"), "please fix the channel");
    await userEvent.click(screen.getByRole("button", { name: "Reassign" }));

    expect(completeTask).toHaveBeenCalledWith("task-1", { cfoDecision: "REASSIGN", assigneeUserId: 2 });
    expect(api.pipelineEvent).toHaveBeenCalledWith(7, { event: "REASSIGNED", assignee_user_id: 2, comment: "please fix the channel" });
    expect(completeTask.mock.invocationCallOrder[0]).toBeLessThan(api.pipelineEvent.mock.invocationCallOrder[0]);
    expect(onDone).toHaveBeenCalled();
  });

  it("CFO final review: approving needs a comment, then completes with who approved (the worker writes the approval)", async () => {
    renderPanel("UserTask_CfoFinalReview");
    await screen.findByRole("table", { name: "Rejected records" });
    expect(screen.queryByRole("form", { name: "Propose a correction" })).toBeNull();   // values are locked now

    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(screen.getByRole("alert").textContent).toMatch(/comment is required/);
    expect(completeTask).not.toHaveBeenCalled();

    await userEvent.type(screen.getByLabelText("Comment"), "fix checked");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));
    expect(api.addExceptionComment).toHaveBeenCalledWith({
      source_table: "pipeline_reconciliation", record_key: "7", flag_label: "RECONCILIATION", comment_text: "fix checked",
    });
    expect(completeTask).toHaveBeenCalledWith("task-1", { finalDecision: "APPROVE", approvedByUserId: 3 });
    expect(api.pipelineEvent).not.toHaveBeenCalled();
  });

  it("assignee: proposes a correction to a real field, never the record's key, then submits", async () => {
    const onDone = renderPanel("UserTask_AssigneeUpdate");
    const form = await screen.findByRole("form", { name: "Propose a correction" });
    await userEvent.selectOptions(within(form).getByLabelText("Record"), "T0009");
    const fields = [...within(form).getByLabelText("Field").options].map((o) => o.value);
    expect(fields).toEqual(["", "account_id", "amount", "channel"]);                  // no transaction_id

    await userEvent.selectOptions(within(form).getByLabelText("Field"), "channel");
    expect(within(form).getByText("Current value: Cheque")).toBeTruthy();
    await userEvent.type(within(form).getByLabelText("Corrected value"), "Branch");
    await userEvent.click(within(form).getByRole("button", { name: "Save correction" }));
    expect(api.proposeCorrection).toHaveBeenCalledWith(7, { record_key: "T0009", field_name: "channel", new_value: "Branch" });

    await userEvent.type(screen.getByLabelText("Comment"), "channel was mistyped");
    await userEvent.click(screen.getByRole("button", { name: "Submit to CFO" }));
    expect(completeTask).toHaveBeenCalledWith("task-1", {});
    expect(api.pipelineEvent).toHaveBeenCalledWith(7, { event: "SUBMITTED", comment: "channel was mistyped" });
    expect(onDone).toHaveBeenCalled();
  });
});
