import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "../App";
import { AuthProvider } from "../auth";
import { calendarCounts, daysLeft, daysLeftText, formatChange, formatLine, urgency } from "../reports/calendar";

const USER = { user_id: 1, name: "Demo Analyst", email: "analyst@bankx.demo", role: "analyst" };
const TODAY = new Date(2026, 8, 21); // 21 Sep 2026 (local)

describe("report calendar rules", () => {
  const row = (due, status = "DRAFT") => ({ due_date: due, status });
  it("counts whole days, negative when overdue", () => {
    expect(daysLeft("2026-09-24", TODAY)).toBe(3);
    expect(daysLeft("2026-09-19", TODAY)).toBe(-2);
    expect(daysLeft(null, TODAY)).toBeNull();
  });
  it("red under 5 days or overdue, amber under 10, green otherwise, submitted always green", () => {
    expect(urgency(row("2026-09-24"), TODAY)).toBe("action");
    expect(urgency(row("2026-09-19"), TODAY)).toBe("action");
    expect(urgency(row("2026-09-26"), TODAY)).toBe("watch");
    expect(urgency(row("2026-10-15"), TODAY)).toBe("good");
    expect(urgency(row("2026-09-01", "SUBMITTED"), TODAY)).toBe("good");
  });
  it("words the days left", () => {
    expect(daysLeftText(row("2026-09-19"), TODAY)).toBe("2 days overdue");
    expect(daysLeftText(row("2026-09-21"), TODAY)).toBe("Due today");
    expect(daysLeftText(row("2026-09-22"), TODAY)).toBe("1 day left");
    expect(daysLeftText(row("2026-09-01", "SUBMITTED"), TODAY)).toBe("Submitted");
  });
  it("counts the four summary boxes", () => {
    const rows = [row("2026-09-25"), row("2026-09-30", "SUBMITTED"), row("2026-10-20", "UNDER_REVIEW"), row("2026-09-19", "APPROVED")];
    expect(calendarCounts(rows, TODAY)).toEqual({ dueThisMonth: 3, submitted: 1, pendingApproval: 3, overdue: 1 });
  });
  it("prints figures as on the form", () => {
    expect(formatLine("currency", 207000000)).toBe("207,000,000");
    expect(formatLine("currency", -8000000)).toBe("(8,000,000)");
    expect(formatLine("percent", "12.5")).toBe("12.50%");
    expect(formatLine("currency", null)).toBe("—");
    expect(formatChange({ change: null })).toBe("N/A");
    expect(formatChange({ change: -1.5, unit: "percent", change_pct: -10 })).toBe("−1.50 pts (−10.0%)");
  });
});

const SNAPSHOT = {
  calculation_date: "2026-09-21",
  loans_by_currency: { LBP: 400e6, USD: 900e6, SAR: 100e6 },
  loans_by_rate_type: { fixed: 300e6, floating: 1100e6 },
  deposits_by_type: { Current: 600e6, Savings: 300e6, "Term deposit": 100e6 },
  deposits_by_rate_type: { fixed: 100e6, floating: 900e6 },
  tier1_capital_usd: 207e6, tier2_capital_usd: 39e6, risk_weighted_assets_usd: 1985e6,
  hqla_usd: 515e6, net_outflows_30d_usd: 356e6, current_npl_pct: 6, current_coverage_pct: 3.6,
};

const CALENDAR = [
  { report_instance_id: 1, name: "Capital Adequacy", frequency: "Quarterly", period: "2026-Q3", status: "DRAFT", due_date: "2026-10-15", owner_department: "Finance", has_lines: true },
  { report_instance_id: 2, name: "FX Position", frequency: "Monthly", period: "2026-08", status: "APPROVED", due_date: "2026-09-19", owner_department: "Treasury", has_lines: false },
];

const line = (line_code, label, value, extra = {}) => ({ line_code, label, value, prior_value: null, section: line_code[0], line_kind: "input", unit: "currency", is_demo_input: false, ...extra });
const REPORT = (blocked = false) => ({
  report: { report_instance_id: 1, name: "Capital Adequacy", frequency: "Quarterly", period: "2026-Q3", status: "DRAFT", due_date: "2026-10-15" },
  available: true,
  sections: [
    { section: "A", title: "CAPITAL", lines: [line("A.1", "Paid-up capital", 150e6, { is_demo_input: true }), line("A.5", "TIER 1 CAPITAL", 207e6, { line_kind: "subtotal" })] },
    { section: "C", title: "RATIOS", lines: [line("C.2", "Total capital ratio", 12.39, { unit: "percent", line_kind: "ratio" })] },
  ],
  validation: [
    { rule_key: "TIER_TOTAL", name: "Tier totals agree", severity: "BLOCKING", passed: !blocked, level: blocked ? "fail" : "pass", message: "Tier 1 + Tier 2 = total" },
    { rule_key: "CAPITAL_BUFFER", name: "Capital buffer", severity: "COMMENT_REQUIRED", passed: false, level: "warn", message: "Only 0.39 points above the minimum" },
  ],
  blocked,
  comparison: [{ line_code: "A.1", label: "Paid-up capital", unit: "currency", current: 150e6, prior: null, change: null, change_pct: null, needs_explanation: false }],
});
const DRILL = { line_code: "A.5", label: "TIER 1 CAPITAL", value: 207e6, unit: "currency", is_demo_input: false, formula_text: "Latest month Tier 1", source_tables: ["capital_positions"], filters_applied: "month = 2026-07", record_count: 1, calculated_at: "2026-09-21T08:00:00Z", notes: null, detail_link: null };

function stub(overrides = {}) {
  const calls = [];
  const ok = (body) => ({ ok: true, status: 200, json: async () => body });
  const fetchMock = vi.fn(async (url, init = {}) => {
    calls.push(`${init.method || "GET"} ${url}`);
    for (const [suffix, body] of Object.entries({
      "/scenario/snapshot": SNAPSHOT, "/scenario/saved": [], "/reports": CALENDAR, "/reports/1": REPORT(),
      "/reports/1/drill/A.5": DRILL, ...overrides,
    })) if (url.endsWith(suffix)) return ok(body);
    return { ok: false, status: 404, json: async () => ({ detail: "unexpected" }) };
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function renderAt(path) {
  localStorage.setItem("bdp_token", "tok");
  localStorage.setItem("bdp_user", JSON.stringify(USER));
  return render(<MemoryRouter initialEntries={[path]}><AuthProvider><App /></AuthProvider></MemoryRouter>);
}

describe("Screen 4: scenario modelling", () => {
  beforeEach(() => stub());

  it("fetches the snapshot once and never calls the backend on slider moves", async () => {
    const calls = stub();
    renderAt("/scenario");
    await screen.findByRole("group", { name: "Preset scenarios" });
    const before = calls.length;
    fireEvent.change(screen.getByRole("slider", { name: "Currency devaluation" }), { target: { value: "30" } });
    fireEvent.change(screen.getByRole("slider", { name: "Deposit outflow" }), { target: { value: "20" } });
    expect(calls.length).toBe(before);
    expect(calls.filter((c) => c.endsWith("/scenario/snapshot"))).toHaveLength(1);
  });

  it("a preset moves the sliders and the results", async () => {
    renderAt("/scenario");
    const user = userEvent.setup();
    await screen.findByRole("group", { name: "Preset scenarios" });
    const car = () => within(screen.getByRole("list", { name: "Results after stress" })).getByLabelText("Capital ratio after stress").textContent;
    const base = car();
    await user.click(screen.getByRole("button", { name: "Severe" }));
    expect(screen.getByRole("button", { name: "Severe" })).toHaveAttribute("aria-pressed", "true");
    expect(car()).not.toBe(base);
  });

  it("says when the snapshot is incomplete instead of guessing", async () => {
    stub({ "/scenario/snapshot": { calculation_date: "2026-09-21" } });
    renderAt("/scenario");
    expect(await screen.findByText("The snapshot is incomplete")).toBeInTheDocument();
  });

  it("lists every assumption", async () => {
    renderAt("/scenario");
    expect(await screen.findByText(/Assumptions behind this model/)).toBeInTheDocument();
    expect(screen.getByText("Not modelled")).toBeInTheDocument();
  });
});

describe("Screen 3: regulatory reporting", () => {
  it("shows the calendar; only reports with a return can be opened", async () => {
    stub();
    renderAt("/reports");
    const table = await screen.findByRole("table", { name: "Report calendar" });
    expect(within(table).getAllByRole("link", { name: /Capital Adequacy|Open/ }).length).toBeGreaterThan(0);
    expect(within(table).queryByRole("link", { name: "FX Position" })).toBeNull();
    expect(within(table).getByText("Not built yet")).toBeInTheDocument();
    expect(screen.getByRole("list", { name: "Reporting summary" })).toBeInTheDocument();
  });

  it("opens a return, shows demo inputs, and drills a figure into its calculation", async () => {
    const calls = stub();
    renderAt("/reports/1");
    const user = userEvent.setup();
    await screen.findByRole("region", { name: /Section A/ });
    expect(screen.getByText("Demo input")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /A\.5 TIER 1 CAPITAL.*207,000,000/ }));
    const panel = await screen.findByRole("complementary", { name: /How A\.5 was calculated/ });
    expect(await within(panel).findByText("Latest month Tier 1")).toBeInTheDocument();
    expect(within(panel).getByText("capital_positions")).toBeInTheDocument();
    expect(calls.some((c) => c.endsWith("/reports/1/drill/A.5"))).toBe(true);
  });

  it("shows validation results and the honest no-prior-period message", async () => {
    stub();
    renderAt("/reports/1");
    expect(await screen.findByText("Explanation required")).toBeInTheDocument();
    expect(screen.getByText(/N\/A — no prior period yet/)).toBeInTheDocument();
    expect(screen.queryByText(/cannot be approved or submitted/)).toBeNull();
  });

  it("blocks visibly when a blocking check fails", async () => {
    stub({ "/reports/1": REPORT(true) });
    renderAt("/reports/1");
    expect(await screen.findByText(/cannot be approved or submitted/)).toBeInTheDocument();
    expect(screen.getByText("Blocks submission")).toBeInTheDocument();
  });

  it("says so when a report has no return yet", async () => {
    stub({ "/reports/1": { ...REPORT(), available: false, sections: [], validation: [], comparison: [] } });
    renderAt("/reports/1");
    expect(await screen.findByText("This return hasn't been built yet")).toBeInTheDocument();
  });
});
