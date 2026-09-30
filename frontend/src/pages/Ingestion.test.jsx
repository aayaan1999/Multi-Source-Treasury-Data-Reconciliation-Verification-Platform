import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Ingestion from "./Ingestion";
import { formProblems } from "../ingestion/forms";
import { api } from "../api";

let role = "admin";
vi.mock("../auth", () => ({ useAuth: () => ({ user: { name: "Demo Admin", role }, logout: vi.fn() }) }));
vi.mock("../api", async (importOriginal) => {
  const actual = await importOriginal();
  return {
    ...actual,
    api: {
      ingestionOverview: vi.fn(), testSource: vi.fn(), connectSource: vi.fn(), disconnectSource: vi.fn(),
      syncSource: vi.fn(), runAllSources: vi.fn(),
    },
  };
});

const SF_FIELDS = [
  { key: "instance_url", label: "Instance URL", kind: "url", required: true, placeholder: "https://your-domain.my.salesforce.com" },
  { key: "client_id", label: "Client ID / Consumer key", kind: "text", required: true, placeholder: "" },
  { key: "client_secret", label: "Client secret", kind: "secret", required: true, placeholder: "" },
  { key: "username", label: "Username", kind: "text", required: true, placeholder: "" },
  { key: "password", label: "Password", kind: "secret", required: true, placeholder: "" },
  { key: "security_token", label: "Security token", kind: "secret", required: false, placeholder: "" },
];
const card = (key, name, extra = {}) => ({
  key, name, code: key.slice(0, 3).toUpperCase(), builtin: false, detail: `${name} detail`, status: "disconnected",
  fields: [], config: {}, secret_fields: [], credentials: null, connected_at: null, last_sync_at: null, ...extra,
});
const SALESFORCE = card("salesforce", "Salesforce", { fields: SF_FIELDS });
const SOURCES = [
  card("core_files", "Core banking files", { builtin: true, status: "connected" }),
  SALESFORCE,
  card("postgresql", "PostgreSQL"),
  card("snowflake", "Snowflake"),
];

const OVERVIEW = {
  trigger: "On file arrival",
  stats: { demo: false, run_at: "2026-09-28T07:22:29Z", files: 9, received: 2655, kept: 2650, held: 5, failed: 1,
           failed_example: "Group Core Banking · fx_rates.csv: No rows delivered" },
  sources: { demo: false, connected: 1, total: 4, missing: ["Salesforce", "PostgreSQL", "Snowflake"] },
  connectors: { demo: false, databricks: false, items: SOURCES },
  schedules: { demo: true, items: [{ source: "Saudi Arabia ERP", runs: "Every 6 hours", next_at: "2026-09-29T12:00:00Z" }] },
  recent: { demo: false, items: [
    { source: "Lebanon Core Banking", type: "File (CSV)", data: "transactions.csv", received: 1419, kept: 1416, held: 3, status: "success", reason: null, at: "2026-09-28T07:22:29Z" },
    { source: "Group Core Banking", type: "File (CSV)", data: "fx_rates.csv", received: 0, kept: 0, held: 0, status: "failed", reason: "No rows delivered", at: "2026-09-28T07:22:29Z" },
  ] },
  upload_formats: ["CSV", "JSON", "PARQUET", "XLSX", "XML", "PDF"],
};

beforeEach(() => {
  vi.clearAllMocks();
  role = "admin";
  api.ingestionOverview.mockResolvedValue(OVERVIEW);
});

async function show() {
  await act(async () => render(<MemoryRouter><Ingestion /></MemoryRouter>));
}
const sourceCard = (name) => within(screen.getByRole("list", { name: "Sources" })).getByRole("listitem", { name });
const toastText = () => screen.getAllByRole("status").map((t) => t.textContent).join(" | ");

function fillSalesforce(dialog, overrides = {}) {
  const values = { "Instance URL": "https://bankx.my.salesforce.com", "Client ID / Consumer key": "3MVG9", "Client secret": "cs",
                   Username: "ingest@bankx.com", Password: "pw", ...overrides };
  for (const [label, value] of Object.entries(values)) {
    fireEvent.change(within(dialog).getByLabelText(new RegExp(`^${label.replace(/[()/]/g, "\\$&")}`)), { target: { value } });
  }
}

describe("Data ingestion", () => {
  it("shows the latest run's real figures and each source's status", async () => {
    await show();
    expect(screen.getByRole("heading", { name: "Bring data in" })).toBeTruthy();
    expect(screen.getByText("2,650 kept · 5 held back with a reason")).toBeTruthy();
    expect(screen.getByText("Group Core Banking · fx_rates.csv: No rows delivered")).toBeTruthy();
    expect(within(sourceCard("Core banking files")).getByText("Connected")).toBeTruthy();
    expect(within(sourceCard("Salesforce")).getByText("Disconnected")).toBeTruthy();
    expect(within(sourceCard("Salesforce")).getByRole("button", { name: "Connect" })).toBeTruthy();
    expect(within(sourceCard("Core banking files")).getByRole("button", { name: "Sync Core banking files" })).toBeTruthy();
    const recent = screen.getByRole("table", { name: "Recent ingestions" });
    expect(within(recent).getByText("3 held back")).toBeTruthy();
  });

  it("keeps Connect & Save disabled until every required field is filled and well-formed", async () => {
    await show();
    fireEvent.click(within(sourceCard("Salesforce")).getByRole("button", { name: "Connect" }));
    const dialog = screen.getByRole("dialog", { name: "Connect Salesforce" });
    const save = within(dialog).getByRole("button", { name: "Connect & Save" });
    expect(save.disabled).toBe(true);
    fillSalesforce(dialog, { "Instance URL": "http://not-secure.example.com" });
    expect(save.disabled).toBe(true);
    fireEvent.blur(within(dialog).getByLabelText(/^Instance URL/));
    expect(within(dialog).getByText("Instance URL must start with https://")).toBeTruthy();
    fillSalesforce(dialog);
    expect(save.disabled).toBe(false);
    expect(within(dialog).getByLabelText(/^Password/).getAttribute("type")).toBe("password");
  });

  it("tests the connection, then connects and updates the card without reloading", async () => {
    api.testSource.mockResolvedValue({ ok: true, live: false, message: "Salesforce details are complete and well-formed." });
    api.connectSource.mockResolvedValue({
      source: { ...SALESFORCE, status: "connected", detail: "https://bankx.my.salesforce.com", credentials: "databricks" },
      message: "Credentials stored in the Databricks secret scope bank-data-sources",
    });
    await show();
    fireEvent.click(within(sourceCard("Salesforce")).getByRole("button", { name: "Connect" }));
    const dialog = screen.getByRole("dialog", { name: "Connect Salesforce" });
    fillSalesforce(dialog);
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Test connection" })));
    expect(within(dialog).getByText(/details are complete and well-formed/)).toBeTruthy();
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Connect & Save" })));

    expect(api.connectSource).toHaveBeenCalledWith("salesforce", {
      instance_url: "https://bankx.my.salesforce.com", client_id: "3MVG9", client_secret: "cs", username: "ingest@bankx.com", password: "pw",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(within(sourceCard("Salesforce")).getByText("Connected")).toBeTruthy();
    expect(within(sourceCard("Salesforce")).getByRole("button", { name: "Configure Salesforce" })).toBeTruthy();
    expect(screen.getByText("PostgreSQL, Snowflake not yet connected")).toBeTruthy();   // the stat card recounted
    expect(toastText()).toMatch(/Salesforce connected\. Credentials stored in the Databricks secret scope/);
    expect(api.ingestionOverview).toHaveBeenCalledTimes(1);                           // no reload
  });

  it("configure opens the saved settings with secrets empty, and can disconnect", async () => {
    const connected = { ...SALESFORCE, status: "connected", config: { instance_url: "https://bankx.my.salesforce.com", client_id: "3MVG9", username: "u" } };
    api.ingestionOverview.mockResolvedValue({ ...OVERVIEW, connectors: { ...OVERVIEW.connectors, items: [SOURCES[0], connected] } });
    api.disconnectSource.mockResolvedValue({ source: SALESFORCE });
    await show();
    fireEvent.click(screen.getByRole("button", { name: "Configure Salesforce" }));
    const dialog = screen.getByRole("dialog", { name: "Configure Salesforce" });
    expect(within(dialog).getByLabelText(/^Instance URL/).value).toBe("https://bankx.my.salesforce.com");
    expect(within(dialog).getByLabelText(/^Password/).value).toBe("");
    await act(async () => fireEvent.click(within(dialog).getByRole("button", { name: "Disconnect" })));
    expect(within(sourceCard("Salesforce")).getByText("Disconnected")).toBeTruthy();
  });

  it("Run all sources now shows a spinner and a toast while it triggers the pipeline", async () => {
    let finish;
    api.runAllSources.mockReturnValue(new Promise((r) => { finish = r; }));
    await show();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Run all sources now" })));
    expect(screen.getByRole("button", { name: "Triggering…" }).disabled).toBe(true);
    expect(toastText()).toMatch(/Triggering Databricks ingestion pipeline…/);
    await act(async () => finish({ run_id: 77, message: "Databricks ingestion pipeline started" }));
    expect(toastText()).toMatch(/Databricks ingestion pipeline started \(run 77\)/);
    expect(screen.getByRole("button", { name: "Run all sources now" }).disabled).toBe(false);
  });

  it("says plainly when the app isn't connected to Databricks", async () => {
    const { ApiError } = await import("../api");
    api.syncSource.mockRejectedValue(new ApiError(503, "not configured"));
    await show();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sync Core banking files" })));
    expect(toastText()).toMatch(/isn't connected to the Databricks pipeline yet, so no run was started/);
  });

  it("checks uploaded files but never sends them", async () => {
    await show();
    const input = screen.getByLabelText("Choose files to upload");
    fireEvent.change(input, { target: { files: [new File(["a"], "positions.parquet"), new File(["x"], "notes.docx")] } });
    const files = screen.getByRole("list", { name: "Files" });
    expect(within(files).getByText("positions.parquet")).toBeTruthy();
    expect(within(files).getByText("DOCX isn't accepted")).toBeTruthy();
    expect(api.runAllSources).not.toHaveBeenCalled();
  });

  describe("upload box, edge cases", () => {
    const pick = (files) => fireEvent.change(screen.getByLabelText("Choose files to upload"), { target: { files } });
    const problemOf = (name) => within(screen.getByRole("list", { name: "Files" })).getByText(name).closest("li").textContent;

    it("names a file with no extension plainly instead of treating its name as the type", async () => {
      await show();
      pick([new File(["a"], "README")]);
      expect(problemOf("README")).toContain("No file type (add .csv, .json, …)");
    });

    it("reads the type case-insensitively and from the last dot", async () => {
      await show();
      pick([new File(["a"], "LOANS.CSV"), new File(["a"], "branches.v2.json"), new File(["a"], "backup.csv.zip")]);
      expect(problemOf("LOANS.CSV")).not.toContain("accepted");
      expect(problemOf("branches.v2.json")).not.toContain("accepted");
      expect(problemOf("backup.csv.zip")).toContain("ZIP isn't accepted");
    });

    it("refuses an empty file, and a file over 2 GB", async () => {
      await show();
      const huge = new File(["a"], "huge.csv");
      Object.defineProperty(huge, "size", { value: 2 * 1024 ** 3 + 1 });
      const limit = new File(["a"], "limit.csv");
      Object.defineProperty(limit, "size", { value: 2 * 1024 ** 3 });
      pick([new File([], "empty.csv"), huge, limit]);
      expect(problemOf("empty.csv")).toContain("The file is empty");
      expect(problemOf("huge.csv")).toContain("Larger than 2 GB");
      expect(problemOf("limit.csv")).not.toContain("Larger than 2 GB");       // exactly 2 GB is allowed
    });

    it("flags the same file added twice", async () => {
      await show();
      pick([new File(["abc"], "loans.csv")]);
      pick([new File(["abc"], "loans.csv")]);
      const rows = within(screen.getByRole("list", { name: "Files" })).getAllByText("loans.csv");
      expect(rows).toHaveLength(2);
      expect(rows[0].closest("li").textContent).toContain("Already added");
    });

    it("finishes each accepted file and says it wasn't sent; a refused one never shows progress", async () => {
      vi.useFakeTimers();
      try {
        await show();
        pick([new File(["a"], "loans.csv"), new File(["x"], "notes.docx")]);
        await act(async () => { vi.advanceTimersByTime(2000); });
        expect(problemOf("loans.csv")).toContain("100%");
        expect(problemOf("loans.csv")).toContain("Checked - not sent");
        expect(problemOf("notes.docx")).not.toContain("%");
        expect(toastText()).toContain("loans.csv uploaded (demo)");
        expect(toastText()).not.toContain("notes.docx uploaded");
      } finally {
        vi.useRealTimers();
      }
    });

    it("leaving the page mid-upload stops its timers (no toast afterwards)", async () => {
      vi.useFakeTimers();
      try {
        let view;
        await act(async () => { view = render(<MemoryRouter><Ingestion /></MemoryRouter>); });
        pick([new File(["a"], "loans.csv")]);
        const errors = vi.spyOn(console, "error").mockImplementation(() => {});
        view.unmount();
        await act(async () => { vi.advanceTimersByTime(3000); });
        expect(vi.getTimerCount()).toBe(0);
        expect(errors).not.toHaveBeenCalled();
        errors.mockRestore();
      } finally {
        vi.useRealTimers();
      }
    });

    it("dropping files works like picking them, and dragging over the text inside doesn't flicker", async () => {
      await show();
      const zone = screen.getByText("Drag & drop files here").parentElement;
      fireEvent.dragOver(zone);
      const leave = createEvent.dragLeave(zone);          // jsdom drops relatedTarget from drag event options
      Object.defineProperty(leave, "relatedTarget", { value: screen.getByText("Drag & drop files here") });
      fireEvent(zone, leave);
      expect(zone.className).toContain("border-[var(--brand-yellow)]");            // still highlighted over a child
      fireEvent.drop(zone, { dataTransfer: { files: [new File(["a"], "fx.csv")] } });
      expect(within(screen.getByRole("list", { name: "Files" })).getByText("fx.csv")).toBeTruthy();
      expect(zone.className).not.toContain("border-[var(--brand-yellow)]");
    });
  });

  it("recent ingestions sort by any column, newest run first to start with", async () => {
    api.ingestionOverview.mockResolvedValue({ ...OVERVIEW, recent: { demo: false, items: [
      ...OVERVIEW.recent.items,
      { source: "Qatar Core Banking", type: "File (CSV)", data: "loans.csv", received: 320, kept: 320, held: 0, status: "success", reason: null, at: "2026-09-29T09:00:00Z" },
    ] } });
    await show();
    const table = screen.getByRole("table", { name: "Recent ingestions" });
    const firstCells = () => within(table).getAllByRole("row").slice(1).map((r) => r.querySelector("td").textContent);
    expect(firstCells()[0]).toBe("Qatar Core Banking");                                     // newest first
    expect(within(table).getByRole("columnheader", { name: /Last run/ }).getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(within(table).getByRole("button", { name: /Records received/ }));
    expect(firstCells()).toEqual(["Group Core Banking", "Qatar Core Banking", "Lebanon Core Banking"]);   // 0, 320, 1,419
    fireEvent.click(within(table).getByRole("button", { name: /Records received/ }));
    expect(firstCells()[0]).toBe("Lebanon Core Banking");
    expect(within(table).getByRole("columnheader", { name: /Records received/ }).getAttribute("aria-sort")).toBe("descending");
    fireEvent.click(within(table).getByRole("button", { name: /Status/ }));
    expect(firstCells()[0]).toBe("Group Core Banking");                                     // "Failed" before "Success"
    fireEvent.click(within(table).getByRole("button", { name: /Source/ }));
    expect(firstCells()).toEqual(["Group Core Banking", "Lebanon Core Banking", "Qatar Core Banking"]);
  });

  it("only the CFO and admins can connect sources or start a run", async () => {
    role = "analyst";
    await show();
    expect(screen.queryByRole("button", { name: "Run all sources now" })).toBeNull();
    expect(within(sourceCard("Salesforce")).getByRole("button", { name: "Connect" }).disabled).toBe(true);
  });
});

describe("connect form rules", () => {
  it("flags missing required fields, non-https addresses and bad ports", () => {
    const fields = [...SF_FIELDS, { key: "port", label: "Port", kind: "port", required: true }];
    const problems = formProblems(fields, { instance_url: "ftp://x", client_id: " ", port: "70000", security_token: "" });
    expect(problems.instance_url).toMatch(/https/);
    expect(problems.client_id).toMatch(/required/);
    expect(problems.port).toMatch(/65535/);
    expect(problems.security_token).toBeUndefined();                                   // optional
  });
});
