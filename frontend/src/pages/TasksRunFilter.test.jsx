import { describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Tasks from "./Tasks";
import { userFor } from "../test/users";

vi.mock("../auth", () => ({ useAuth: () => ({ user: userFor("analyst"), logout: vi.fn() }) }));
// Three of the analyst's reconciliation tasks: two core banking file runs (8 and 9 Oct) and a loan system run.
const run = (run_id, source_system, source_name, run_date, day) => ({ run_id, source_system, source_name, run_date, day });
const TASK_RUNS = {
  reconciliation: {
    11: run(174, "CORE_CSV", "Core banking files", "2026-10-08", "8 Oct 2026"),
    12: run(180, "CORE_CSV", "Core banking files", "2026-10-09", "9 Oct 2026 (carried over)"),
  },
  recon_group: { 21: run(175, "los", "Loan origination system", "2026-10-08", "8 Oct 2026") },
  recon_run: {},
};
// Every other call the page makes answers "nothing" (digest, policy, carried tasks...).
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: new Proxy({}, { get: (_, name) => (name === "reconTaskRuns" ? vi.fn(async () => TASK_RUNS) : vi.fn(async () => [])) }),
  };
});
vi.mock("../workflow/tasklistApi", () => ({
  claimTask: vi.fn(), completeTask: vi.fn(), getVariables: vi.fn(async () => ({})),
  searchTasks: vi.fn(async () => [
    { id: "1", name: "Team review", creationDate: "2026-10-08T12:00:00.000+0000", candidateGroups: ["operations"],
      vars: { recordType: "reconciliation", sourceTable: "pipeline_reconciliation", recordKey: "11", title: "Lebanon accounts: 1 row not loaded" } },
    { id: "2", name: "Team review", creationDate: "2026-10-09T12:00:00.000+0000", candidateGroups: ["operations"],
      vars: { recordType: "reconciliation", sourceTable: "pipeline_reconciliation", recordKey: "12", title: "Lebanon transactions: 3 rows not loaded" } },
    { id: "3", name: "Team review", creationDate: "2026-10-08T12:00:00.000+0000", candidateGroups: ["operations"],
      vars: { recordType: "recon_group", sourceTable: "reconciliation_groups", recordKey: "21", title: "3 loans differ from the loan system" } },
  ]),
}));

async function show() {
  await act(async () => render(<MemoryRouter><Tasks /></MemoryRouter>));
}
const rows = () => within(screen.getByRole("table", { name: "My tasks" })).getAllByRole("row").slice(1);
const options = (label) => within(screen.getByLabelText(label)).getAllByRole("option").map((o) => o.textContent);

describe("Tasks: Source and Run filters", () => {
  it("shows each task's run, filters by source, then by one of that source's runs", async () => {
    await show();
    expect(rows()).toHaveLength(3);
    expect(rows().map((r) => r.textContent).join("|")).toContain("Core banking files · 9 Oct 2026 (carried over)");
    expect(options("Source")).toEqual(["All sources", "Core banking files", "Loan origination system"]);
    // Before a source is picked, a run says which source it's from; newest first
    expect(options("Run")).toEqual(["All runs", "Core banking files · 9 Oct 2026 (carried over)",
      "Core banking files · 8 Oct 2026", "Loan origination system · 8 Oct 2026"]);

    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "CORE_CSV" } });
    expect(rows()).toHaveLength(2);
    expect(options("Run")).toEqual(["All runs", "9 Oct 2026 (carried over)", "8 Oct 2026"]);

    fireEvent.change(screen.getByLabelText("Run"), { target: { value: "174" } });
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toContain("Lebanon accounts: 1 row not loaded");
  });

  it("clears the run when the source changes, and says plainly when nothing matches", async () => {
    await show();
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "CORE_CSV" } });
    fireEvent.change(screen.getByLabelText("Run"), { target: { value: "174" } });
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "los" } });
    expect(screen.getByLabelText("Run").value).toBe("");
    expect(rows()).toHaveLength(1);
    expect(rows()[0].textContent).toContain("3 loans differ from the loan system");

    fireEvent.change(screen.getByLabelText("Created from"), { target: { value: "2026-10-09" } });
    expect(screen.getByText(/None of your tasks are from that source or run/)).toBeTruthy();
  });
});
