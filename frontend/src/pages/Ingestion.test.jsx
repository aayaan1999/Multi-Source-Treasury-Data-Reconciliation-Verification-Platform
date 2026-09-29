import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Ingestion from "./Ingestion";
import { api } from "../api";

let role = "admin";
vi.mock("../auth", () => ({ useAuth: () => ({ user: { name: "Demo Admin", role }, logout: vi.fn() }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return { ...actual, api: { ingestionOverview: vi.fn(), refreshNow: vi.fn() } };
});

const OVERVIEW = {
  trigger: "On file arrival",
  stats: { demo: false, run_at: "2026-09-28T07:22:29Z", files: 9, received: 2655, kept: 2650, held: 5, failed: 1,
           failed_example: "Group Core Banking · fx_rates.csv: No rows delivered" },
  sources: { demo: true, connected: 5, total: 6, missing: ["Core Banking / ERP"] },
  connectors: { demo: true, items: [
    { code: "SFTP", name: "SFTP", detail: "Lebanon core banking files", status: "connected" },
    { code: "ERP", name: "Core Banking / ERP", detail: "Add another system", status: "not_connected" },
  ] },
  schedules: { demo: true, items: [{ source: "Saudi Arabia ERP", runs: "Every 6 hours", next_at: "2026-09-29T12:00:00Z" }] },
  recent: { demo: false, items: [
    { source: "Lebanon Core Banking", type: "File (CSV)", data: "transactions.csv", received: 1419, kept: 1416, held: 3, status: "success", reason: null, at: "2026-09-28T07:22:29Z" },
    { source: "Group Core Banking", type: "File (CSV)", data: "fx_rates.csv", received: 0, kept: 0, held: 0, status: "failed", reason: "No rows delivered", at: "2026-09-28T07:22:29Z" },
  ] },
  upload_formats: ["CSV", "XLSX", "JSON", "XML", "PDF"],
};

beforeEach(() => {
  vi.clearAllMocks();
  role = "admin";
  api.ingestionOverview.mockResolvedValue(OVERVIEW);
});

async function show() {
  await act(async () => render(<MemoryRouter><Ingestion /></MemoryRouter>));
}

describe("Data ingestion", () => {
  it("shows the latest run's real figures, and labels demo content", async () => {
    await show();
    expect(screen.getByRole("heading", { name: "Bring data in" })).toBeTruthy();
    expect(screen.getByText("2,655")).toBeTruthy();
    expect(screen.getByText("2,650 kept · 5 held back with a reason")).toBeTruthy();
    expect(screen.getByText("Group Core Banking · fx_rates.csv: No rows delivered")).toBeTruthy();
    expect(screen.getByText("Core Banking / ERP not yet connected")).toBeTruthy();
    // demo: sources card, connectors, schedules, upload - but not the real stat cards or recent loads
    expect(screen.getAllByRole("button", { name: /Demo data/ })).toHaveLength(4);
    const recent = screen.getByRole("table", { name: "Recent ingestions" });
    expect(within(recent).getByText("transactions.csv")).toBeTruthy();
    expect(within(recent).getByText("3 held back")).toBeTruthy();
    expect(within(recent).getByText("Failed")).toBeTruthy();
    expect(screen.getByText("Schedule: on file arrival")).toBeTruthy();
  });

  it("checks uploaded files but never sends them", async () => {
    await show();
    const input = screen.getByLabelText("Choose files to upload");
    const good = new File(["a,b"], "branch_finance_sept.xlsx");
    const bad = new File(["x"], "notes.docx");
    fireEvent.change(input, { target: { files: [good, bad] } });
    const files = screen.getByRole("list", { name: "Files" });
    expect(within(files).getByText("branch_finance_sept.xlsx")).toBeTruthy();
    expect(within(files).getByText("DOCX isn't accepted")).toBeTruthy();
    expect(api.refreshNow).not.toHaveBeenCalled();
  });

  it("starts the pipeline, and says so plainly when it isn't connected", async () => {
    const { ApiError } = await import("../api");
    api.refreshNow.mockRejectedValueOnce(new ApiError(503, "not configured")).mockResolvedValueOnce({});
    await show();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Run all sources now" })));
    expect(screen.getByRole("status").textContent).toMatch(/isn't connected to the Databricks pipeline/);
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Run all sources now" })));
    expect(screen.getByRole("status").textContent).toMatch(/takes a few minutes/);
  });

  it("only the CFO and admins can start a run", async () => {
    role = "analyst";
    await show();
    expect(screen.queryByRole("button", { name: "Run all sources now" })).toBeNull();
  });

  it("explains that a new connector isn't available yet", async () => {
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Connect" }));
    expect(screen.getByRole("status").textContent).toMatch(/Connecting Core Banking \/ ERP .* not available in this demo yet/);
  });
});
