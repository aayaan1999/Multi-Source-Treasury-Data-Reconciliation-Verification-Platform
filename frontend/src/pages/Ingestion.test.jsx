import { beforeEach, describe, expect, it, vi } from "vitest";
import { act, createEvent, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import Ingestion, { pipelineFile } from "./Ingestion";
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
      syncSource: vi.fn(), runAllSources: vi.fn(), uploadFile: vi.fn(),
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
  upload_formats: ["CSV"],
  upload_files: ["customers.csv", "accounts.csv", "loans.csv", "transactions.csv", "branches.csv",
                 "capital_positions.csv", "liquidity_daily.csv", "fx_rates.csv"],
};

beforeEach(() => {
  vi.clearAllMocks();
  role = "admin";
  api.ingestionOverview.mockResolvedValue(OVERVIEW);
  api.uploadFile.mockImplementation(async (file) => ({ message: `Sent to the pipeline as ${pipelineFile(file.name, OVERVIEW.upload_files)} (3 rows).` }));
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

  it("Run All Sources shows a spinner and a toast while it triggers the pipeline", async () => {
    let finish;
    api.runAllSources.mockReturnValue(new Promise((r) => { finish = r; }));
    await show();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Run All Sources" })));
    expect(screen.getByRole("button", { name: "Triggering…" }).disabled).toBe(true);
    expect(toastText()).toMatch(/Triggering Databricks ingestion pipeline…/);
    await act(async () => finish({ run_id: 77, message: "Databricks ingestion pipeline started" }));
    expect(toastText()).toMatch(/Databricks ingestion pipeline started \(run 77\)/);
    expect(screen.getByRole("button", { name: "Run All Sources" }).disabled).toBe(false);
  });

  it("says plainly when the app isn't connected to Databricks", async () => {
    const { ApiError } = await import("../api");
    api.syncSource.mockRejectedValue(new ApiError(503, "not configured"));
    await show();
    await act(async () => fireEvent.click(screen.getByRole("button", { name: "Sync Core banking files" })));
    expect(toastText()).toMatch(/isn't connected to the Databricks pipeline yet, so no run was started/);
  });

  describe("upload box", () => {
    const pick = (files) => fireEvent.change(screen.getByLabelText("Choose files to upload"), { target: { files } });
    const rowOf = (name) => within(screen.getByRole("list", { name: "Files" })).getByText(name).closest("li").textContent;

    it("sends each of the pipeline's files and says so; refuses the rest without sending them", async () => {
      await show();
      await act(async () => pick([new File(["a"], "Transactions_2026-09-30.csv"), new File(["x"], "notes.docx"), new File(["a"], "loans2.csv")]));
      expect(api.uploadFile).toHaveBeenCalledTimes(1);
      expect(api.uploadFile.mock.calls[0]).toEqual([expect.objectContaining({ name: "Transactions_2026-09-30.csv" }), { confirmed: false }]);
      expect(rowOf("Transactions_2026-09-30.csv")).toContain("Sent to the pipeline as transactions.csv");
      expect(rowOf("notes.docx")).toContain("DOCX isn't accepted");
      expect(rowOf("loans2.csv")).toContain("Not one of the pipeline's files");
      expect(toastText()).toContain("Transactions_2026-09-30.csv: Sent to the pipeline");
      expect(toastText()).not.toContain("notes.docx");
    });

    it("shows the server's refusal on the file and in a toast", async () => {
      const { ApiError } = await import("../api");
      api.uploadFile.mockRejectedValue(new ApiError(400, "loans.csv is missing column(s) stage"));
      await show();
      await act(async () => pick([new File(["a"], "loans.csv")]));
      expect(rowOf("loans.csv")).toContain("missing column(s) stage");
      expect(toastText()).toContain("loans.csv wasn't sent: loans.csv is missing column(s) stage");
    });

    it("shows Sending… until the server answers", async () => {
      let answer;
      api.uploadFile.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
      await show();
      await act(async () => pick([new File(["a"], "fx_rates.csv")]));
      expect(rowOf("fx_rates.csv")).toContain("Sending…");
      await act(async () => answer({ message: "Sent to the pipeline as fx_rates.csv (1 rows)." }));
      expect(rowOf("fx_rates.csv")).toContain("Sent");
      expect(rowOf("fx_rates.csv")).not.toContain("Sending…");
    });

    it("names a file with no extension plainly, and reads the type from the last dot", async () => {
      await show();
      await act(async () => pick([new File(["a"], "README"), new File(["a"], "LOANS.CSV"), new File(["a"], "customers.csv.zip")]));
      expect(rowOf("README")).toContain("No file type (add .csv)");
      expect(rowOf("customers.csv.zip")).toContain("ZIP isn't accepted");
      expect(api.uploadFile).toHaveBeenCalledTimes(1);                                // LOANS.CSV only
    });

    it("refuses an empty file and one over 100 MB; exactly 100 MB is sent", async () => {
      await show();
      const huge = new File(["a"], "accounts.csv");
      Object.defineProperty(huge, "size", { value: 100 * 1024 ** 2 + 1 });
      const limit = new File(["a"], "branches.csv");
      Object.defineProperty(limit, "size", { value: 100 * 1024 ** 2 });
      await act(async () => pick([new File([], "customers.csv"), huge, limit]));
      expect(rowOf("customers.csv")).toContain("The file is empty");
      expect(rowOf("accounts.csv")).toContain("Larger than 100 MB");
      expect(api.uploadFile.mock.calls.map(([f]) => f.name)).toEqual(["branches.csv"]);
    });

    it("flags the same file added twice and sends it once", async () => {
      await show();
      await act(async () => pick([new File(["abc"], "loans.csv")]));
      await act(async () => pick([new File(["abc"], "loans.csv")]));
      const rows = within(screen.getByRole("list", { name: "Files" })).getAllByText("loans.csv");
      expect(rows).toHaveLength(2);
      expect(rows[0].closest("li").textContent).toContain("Already added");
      expect(api.uploadFile).toHaveBeenCalledTimes(1);
    });

    it("an answer that comes after leaving the page changes nothing", async () => {
      let answer;
      api.uploadFile.mockImplementation(() => new Promise((resolve) => { answer = resolve; }));
      let view;
      await act(async () => { view = render(<MemoryRouter><Ingestion /></MemoryRouter>); });
      await act(async () => pick([new File(["a"], "loans.csv")]));
      const errors = vi.spyOn(console, "error").mockImplementation(() => {});
      view.unmount();
      await act(async () => answer({ message: "late" }));
      expect(errors).not.toHaveBeenCalled();
      errors.mockRestore();
    });

    it("dropping files works like picking them, and dragging over the text inside doesn't flicker", async () => {
      await show();
      const zone = screen.getByText("Drag & drop files here").parentElement;
      fireEvent.dragOver(zone);
      const leave = createEvent.dragLeave(zone);          // jsdom drops relatedTarget from drag event options
      Object.defineProperty(leave, "relatedTarget", { value: screen.getByText("Drag & drop files here") });
      fireEvent(zone, leave);
      expect(zone.className).toContain("border-[var(--brand-yellow)]");            // still highlighted over a child
      await act(async () => fireEvent.drop(zone, { dataTransfer: { files: [new File(["a"], "fx_rates.csv")] } }));
      expect(within(screen.getByRole("list", { name: "Files" })).getByText("fx_rates.csv")).toBeTruthy();
      expect(zone.className).not.toContain("border-[var(--brand-yellow)]");
    });

    it("lists the eight files the pipeline reads", async () => {
      await show();
      const names = within(screen.getByLabelText("Files the pipeline reads")).getAllByText(/\.csv$/).map((e) => e.textContent);
      expect(names).toEqual(OVERVIEW.upload_files);
    });

    it("a file that would replace most of the data waits: Send anyway sends it confirmed, Don't send drops it", async () => {
      const { ApiError } = await import("../api");
      const WARNING = "customers.csv would remove 186 of the 214 customers the platform has now and add 372 new ones.";
      api.uploadFile.mockImplementation(async (file, { confirmed } = {}) => {
        if (!confirmed) throw new ApiError(409, WARNING);
        return { message: "Sent to the pipeline as customers.csv (400 rows)." };
      });
      await show();
      await act(async () => pick([new File(["a"], "customers.csv"), new File(["b"], "accounts.csv")]));
      expect(rowOf("customers.csv")).toContain(WARNING);
      expect(toastText()).toContain("customers.csv is waiting for you");
      await act(async () => fireEvent.click(within(within(screen.getByRole("list", { name: "Files" })).getByText("customers.csv").closest("li")).getByRole("button", { name: "Send anyway" })));
      expect(api.uploadFile).toHaveBeenLastCalledWith(expect.objectContaining({ name: "customers.csv" }), { confirmed: true });
      expect(rowOf("customers.csv")).toContain("Sent to the pipeline as customers.csv");
      await act(async () => fireEvent.click(within(within(screen.getByRole("list", { name: "Files" })).getByText("accounts.csv").closest("li")).getByRole("button", { name: "Don't send" })));
      expect(rowOf("accounts.csv")).toContain("Not sent");
      expect(api.uploadFile).toHaveBeenCalledTimes(3);                  // two first tries + one confirmed
    });

    it("someone who can't upload sees why, and a drop sends nothing", async () => {
      role = "analyst";
      await show();
      expect(screen.queryByRole("button", { name: "Browse files" })).toBeNull();
      expect(screen.getByText("Only the CFO or the Platform Administrator can upload files.")).toBeTruthy();
      const zone = screen.getByText("Drag & drop files here").parentElement;
      await act(async () => fireEvent.drop(zone, { dataTransfer: { files: [new File(["a"], "loans.csv")] } }));
      expect(api.uploadFile).not.toHaveBeenCalled();
      expect(screen.queryByRole("list", { name: "Files" })).toBeNull();
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
    expect(screen.queryByRole("button", { name: "Run All Sources" })).toBeNull();
    expect(within(sourceCard("Salesforce")).getByRole("button", { name: "Connect" }).disabled).toBe(true);
  });
});

describe("which pipeline file a name is", () => {
  const files = OVERVIEW.upload_files;
  it("matches the name, any case, with a date or other suffix after _ - . or space", () => {
    expect(pipelineFile("transactions.csv", files)).toBe("transactions.csv");
    expect(pipelineFile("Transactions_2026-09-30.csv", files)).toBe("transactions.csv");
    expect(pipelineFile("LOANS.CSV", files)).toBe("loans.csv");
    expect(pipelineFile("fx_rates-sep.csv", files)).toBe("fx_rates.csv");
    expect(pipelineFile("capital_positions 2026.csv", files)).toBe("capital_positions.csv");
  });
  it("refuses other names and other types", () => {
    expect(pipelineFile("loans2.csv", files)).toBeNull();
    expect(pipelineFile("my_loans.csv", files)).toBeNull();
    expect(pipelineFile("loans.json", files)).toBeNull();
    expect(pipelineFile("loans.csv.zip", files)).toBeNull();
    expect(pipelineFile(".csv", files)).toBeNull();
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
