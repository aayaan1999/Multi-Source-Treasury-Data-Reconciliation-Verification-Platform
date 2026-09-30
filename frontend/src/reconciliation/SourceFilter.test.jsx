import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CoreSystemSection from "./CoreSystemSection";
import { api } from "../api";

vi.mock("../auth", () => ({ useAuth: () => ({ user: { user_id: 1, name: "Demo Admin", role: "admin" } }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { reconRun: vi.fn(), reconRuns: vi.fn(), reconGroups: vi.fn(), reconciliationExceptions: vi.fn() } };
});

const row = (id, source_system, entity_id, extra = {}) => ({
  exception_id: id, source_system, entity_type: "customer", entity_id, field_name: "name", source_value: `${source_system} value`,
  canonical_value: "our value", mismatch_type: "VALUE_MISMATCH", status: "OPEN", detected_at: "2026-09-29T14:00:00Z",
  first_seen: "2026-09-29T14:00:00Z", times_seen: 1, group_id: null, ...extra,
});
const RUNS = {
  neon: { run_date: "2026-09-28", source_system: "neon", breaks_seen: 31, auto_cleared: 2, groups_open: 11, important_open: 3, recurring_open: 2 },
  salesforce: { run_date: "2026-09-29", source_system: "salesforce", breaks_seen: 5, auto_cleared: 1, groups_open: 4, important_open: 3, recurring_open: 0 },
};
const CURRENT = [
  { run_id: 1, source_system: "CORE_CSV", name: "core banking files of 29 Sep 2026", status: "OPEN", tasks: 3, decided: 0, awaiting_cfo: 0 },
  { run_id: 2, source_system: "neon", name: "core banking comparison of 28 Sep 2026", status: "OPEN", tasks: 11, decided: 9, awaiting_cfo: 1 },
  { run_id: 3, source_system: "salesforce", name: "CRM comparison of 29 Sep 2026", status: "SIGNED_OFF", tasks: 4, decided: 4, awaiting_cfo: 0,
    signed_by_name: "Demo Admin", signed_at: "2026-09-30T10:00:00Z", sign_note: "All explained" },
];

beforeEach(() => {
  vi.clearAllMocks();
  api.reconRun.mockImplementation(async (source) => RUNS[source]);
  api.reconRuns.mockResolvedValue(CURRENT);
  api.reconGroups.mockResolvedValue([
    { group_id: 3, source_system: "neon", entity_type: "account", field_name: "balance", pattern: "+15.00", mismatch_type: "VALUE_MISMATCH", break_count: 4, important: false, status: "PENDING" },
    { group_id: 17, source_system: "salesforce", entity_type: "customer", field_name: "name", pattern: "different value", mismatch_type: "VALUE_MISMATCH", break_count: 1, important: true, status: "PENDING" },
  ]);
  api.reconciliationExceptions.mockResolvedValue([row(1, "neon", "ACN0007"), row(2, "salesforce", "CN0008")]);
});

async function show() {
  await act(async () => render(<MemoryRouter><CoreSystemSection /></MemoryRouter>));
}
const breaks = () => screen.getByRole("table", { name: "Reconciliation exceptions" });
const groups = () => screen.getByRole("table", { name: "Groups of breaks" });

describe("reconciliation against the source systems", () => {
  it("shows every source by default: added-up run, each source's sign-off status, and a Source column", async () => {
    await show();
    expect(api.reconRun.mock.calls.map((c) => c[0])).toEqual(["neon", "salesforce"]);
    expect(within(screen.getByRole("list", { name: "Latest run" })).getByText("36")).toBeTruthy();       // 31 + 5
    expect(screen.getByRole("generic", { name: "Run: core banking comparison of 28 Sep 2026" })).toBeTruthy();
    expect(screen.getByRole("generic", { name: "Run: CRM comparison of 29 Sep 2026" })).toBeTruthy();
    expect(screen.queryByRole("generic", { name: "Run: core banking files of 29 Sep 2026" })).toBeNull();   // the pipeline's run lives above
    expect(within(breaks()).getByRole("columnheader", { name: "Source" })).toBeTruthy();
    expect(within(breaks()).getByRole("columnheader", { name: "Their value" })).toBeTruthy();
    expect(within(breaks()).getByText("CN0008", { exact: false })).toBeTruthy();
    expect(within(breaks()).getByText("ACN0007", { exact: false })).toBeTruthy();
    expect(within(groups()).getAllByRole("row")).toHaveLength(3);                                   // header + 2 groups
  });

  it("one Source filter narrows the run, the groups and the breaks together", async () => {
    await show();
    fireEvent.change(screen.getByLabelText("Source"), { target: { value: "salesforce" } });
    expect(within(screen.getByRole("list", { name: "Latest run" })).getByText("5")).toBeTruthy();
    expect(screen.queryByRole("generic", { name: "Run: core banking comparison of 28 Sep 2026" })).toBeNull();
    expect(within(breaks()).queryByText("ACN0007", { exact: false })).toBeNull();
    expect(within(breaks()).getByText("CN0008", { exact: false })).toBeTruthy();
    expect(within(breaks()).getByRole("columnheader", { name: "CRM" })).toBeTruthy();                // named after the source
    expect(within(breaks()).queryByRole("columnheader", { name: "Source" })).toBeNull();
    expect(within(groups()).getByText("#17")).toBeTruthy();
    expect(within(groups()).queryByText("#3")).toBeNull();
    expect(api.reconciliationExceptions).toHaveBeenCalledTimes(1);                                    // filtered in the browser
  });

  it("says where each run's sign-off stands; signing off happens in Tasks", async () => {
    await show();
    const core = screen.getByRole("generic", { name: "Run: core banking comparison of 28 Sep 2026" });
    expect(within(core).getByText(/9 of 11 tasks decided\. Sign-off starts once every task is decided \(2 to go, 1 of them waiting for CFO approval\)\./)).toBeTruthy();
    expect(within(core).getByRole("link", { name: "Tasks" })).toBeTruthy();
    const crm = screen.getByRole("generic", { name: "Run: CRM comparison of 29 Sep 2026" });
    expect(within(crm).getByText(/Signed off by Demo Admin on .*\("All explained"\)\./)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /sign off|submit/i })).toBeNull();
  });
});
