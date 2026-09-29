import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CoreSystemSection from "./CoreSystemSection";
import { api } from "../api";

vi.mock("../auth", () => ({ useAuth: () => ({ user: { user_id: 1, name: "Demo Admin", role: "admin" } }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { reconRun: vi.fn(), reconGroups: vi.fn(), reconciliationExceptions: vi.fn(), submitReconRun: vi.fn() } };
});

const row = (id, source_system, entity_id, extra = {}) => ({
  exception_id: id, source_system, entity_type: "customer", entity_id, field_name: "name", source_value: `${source_system} value`,
  canonical_value: "our value", mismatch_type: "VALUE_MISMATCH", status: "OPEN", detected_at: "2026-09-29T14:00:00Z",
  first_seen: "2026-09-29T14:00:00Z", times_seen: 1, group_id: null, ...extra,
});
const RUNS = {
  neon: { run_date: "2026-09-28", source_system: "neon", breaks_seen: 31, auto_cleared: 2, groups_open: 11, important_open: 3, recurring_open: 2, signoff: null },
  salesforce: { run_date: "2026-09-29", source_system: "salesforce", breaks_seen: 5, auto_cleared: 1, groups_open: 4, important_open: 3, recurring_open: 0, signoff: null },
};

beforeEach(() => {
  vi.clearAllMocks();
  api.reconRun.mockImplementation(async (source) => RUNS[source]);
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
  it("shows every source by default: added-up run, one sign-off per source, and a Source column", async () => {
    await show();
    expect(api.reconRun.mock.calls.map((c) => c[0])).toEqual(["neon", "salesforce"]);
    expect(within(screen.getByRole("list", { name: "Latest run" })).getByText("36")).toBeTruthy();       // 31 + 5
    expect(screen.getByRole("generic", { name: "Run sign-off: Core banking system" })).toBeTruthy();
    expect(screen.getByRole("generic", { name: "Run sign-off: CRM (Salesforce)" })).toBeTruthy();
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
    expect(screen.queryByRole("generic", { name: "Run sign-off: Core banking system" })).toBeNull();
    expect(within(breaks()).queryByText("ACN0007", { exact: false })).toBeNull();
    expect(within(breaks()).getByText("CN0008", { exact: false })).toBeTruthy();
    expect(within(breaks()).getByRole("columnheader", { name: "CRM" })).toBeTruthy();                // named after the source
    expect(within(breaks()).queryByRole("columnheader", { name: "Source" })).toBeNull();
    expect(within(groups()).getByText("#17")).toBeTruthy();
    expect(within(groups()).queryByText("#3")).toBeNull();
    expect(api.reconciliationExceptions).toHaveBeenCalledTimes(1);                                    // filtered in the browser
  });

  it("each source's run is submitted for sign-off on its own", async () => {
    api.submitReconRun.mockResolvedValue({});
    await show();
    const crm = screen.getByRole("generic", { name: "Run sign-off: CRM (Salesforce)" });
    await act(async () => fireEvent.click(within(crm).getByRole("button", { name: "Submit for sign-off" })));
    expect(api.submitReconRun).toHaveBeenCalledWith({ source_system: "salesforce", note: undefined });
  });
});
