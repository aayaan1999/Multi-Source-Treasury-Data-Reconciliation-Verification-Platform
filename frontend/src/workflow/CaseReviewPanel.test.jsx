import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import CaseReviewPanel from "./CaseReviewPanel";
import { policyLines } from "./DigestAndPolicy";
import { api } from "../api";
import { completeTask } from "./tasklistApi";

vi.mock("../api", () => ({
  api: {
    caseDetail: vi.fn(async () => ({
      case_id: 5, severity: "HIGH", due_date: "2026-09-26", flag_count: 3,
      flags: [
        { transaction_id: "T5", flag_label: "VELOCITY_BREACH", description: "3 txns", date: "2026-09-21", amount: 50, currency: "USD", channel: "Branch" },
        { transaction_id: "T5", flag_label: "STRUCTURING_PATTERN", description: "band", date: "2026-09-21", amount: 50, currency: "USD", channel: "Branch" },
        { transaction_id: "T6", flag_label: "VELOCITY_BREACH", description: "3 txns", date: "2026-09-21", amount: 60, currency: "USD", channel: "Mobile" },
      ],
    })),
    exceptionComments: vi.fn(async () => []),
    addExceptionComment: vi.fn(async () => ({})),
    logTaskCompletion: vi.fn(async () => ({})),
  },
}));
vi.mock("./tasklistApi", () => ({ completeTask: vi.fn(async () => null) }));

beforeEach(() => vi.clearAllMocks());

const TASK = { id: "task-9", vars: { recordType: "fraud_case", recordKey: "5", flagLabel: "SUSPICIOUS", title: "A3 · 21 Sep 2026 · 3 Suspicious flags" } };

describe("case review popup", () => {
  it("lists every flag with why it was raised, and one decision closes them all", async () => {
    const onDone = vi.fn();
    render(<CaseReviewPanel task={TASK} user={{ user_id: 2 }} onDone={onDone} onClose={() => {}} />);
    const table = await screen.findByRole("table", { name: "Flags in this case" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);                 // header + 3 flags
    expect(within(table).getAllByText(/money-laundering pattern/)).toHaveLength(1);

    await userEvent.click(screen.getByRole("button", { name: "Approve all" }));
    expect(screen.getByRole("alert").textContent).toMatch(/comment is required/);

    await userEvent.type(screen.getByLabelText("Comment"), "same customer, one incident");
    await userEvent.click(screen.getByRole("button", { name: "Approve all" }));
    expect(completeTask).toHaveBeenCalledWith("task-9", { outcome: "APPROVED", correctedValue: "", reviewedByUserId: 2 });
    expect(api.logTaskCompletion).toHaveBeenCalledWith({ source_table: "task_cases", record_key: "5", flag_label: "SUSPICIOUS", outcome: "APPROVED", camunda_task_id: "task-9" });
    expect(onDone).toHaveBeenCalled();
  });
});

describe("task policy text", () => {
  it("is written from the settings, so changing a value changes the wording", () => {
    const lines = policyLines({
      "task.severity": { base: { SUSPICIOUS: 3, THRESHOLD: 2, OPERATIONAL: 1 }, many_flags_at: 3, many_rules_at: 2, high_min: 4, medium_min: 2 },
      "task.due_days": { HIGH: 2, MEDIUM: 5, LOW: 10, DATA_QUALITY: 5, RECONCILIATION: 3 },
    });
    expect(lines.join(" ")).toContain("Suspicious 3, Threshold 2, Operational 1");
    expect(lines.join(" ")).toContain("High 2 days, Medium 5, Low 10");
    expect(policyLines({})).toEqual([]);
  });
});
