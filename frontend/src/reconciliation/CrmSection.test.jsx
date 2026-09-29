import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import CoreSystemSection from "./CoreSystemSection";
import { api } from "../api";

vi.mock("../auth", () => ({ useAuth: () => ({ user: { user_id: 1, name: "Demo Admin", role: "admin" } }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { reconRun: vi.fn(), reconGroups: vi.fn(), reconciliationExceptions: vi.fn() } };
});

const BREAK = {
  exception_id: 9, source_system: "salesforce", entity_type: "customer", entity_id: "CN0008", field_name: "name",
  source_value: "Haddad Construction LLC", canonical_value: "Haddad Contracting LLC", mismatch_type: "VALUE_MISMATCH",
  status: "OPEN", detected_at: "2026-09-29T14:00:00Z", first_seen: "2026-09-29T14:00:00Z", times_seen: 1, group_id: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  api.reconRun.mockResolvedValue({ run_date: "2026-09-29", source_system: "salesforce", breaks_seen: 4, auto_cleared: 1, groups_open: 0, important_open: 0, recurring_open: 0, signoff: null });
  api.reconGroups.mockResolvedValue([]);
  api.reconciliationExceptions.mockResolvedValue([BREAK]);
});

describe("CRM reconciliation section", () => {
  it("asks only for Salesforce's run, groups and breaks, and calls the other side the CRM", async () => {
    await act(async () => render(<MemoryRouter><CoreSystemSection source="salesforce" /></MemoryRouter>));
    expect(api.reconRun).toHaveBeenCalledWith("salesforce");
    expect(api.reconGroups).toHaveBeenCalledWith({ source_system: "salesforce" });
    expect(api.reconciliationExceptions).toHaveBeenCalledWith({ limit: 5000, source_system: "salesforce" });
    const table = screen.getByRole("table", { name: "Reconciliation exceptions: CRM" });
    expect(within(table).getByRole("columnheader", { name: "CRM" })).toBeTruthy();
    expect(within(table).getByText("Haddad Construction LLC")).toBeTruthy();
    expect(screen.getByText(/comparison with the CRM \(Salesforce\)/)).toBeTruthy();
  });

  it("the core-banking section keeps asking for core banking only", async () => {
    await act(async () => render(<MemoryRouter><CoreSystemSection /></MemoryRouter>));
    expect(api.reconRun).toHaveBeenCalledWith("neon");
    expect(api.reconciliationExceptions).toHaveBeenCalledWith({ limit: 5000, source_system: "neon" });
    expect(within(screen.getByRole("table", { name: "Reconciliation exceptions: Core system" })).getByRole("columnheader", { name: "Core system" })).toBeTruthy();
  });
});
