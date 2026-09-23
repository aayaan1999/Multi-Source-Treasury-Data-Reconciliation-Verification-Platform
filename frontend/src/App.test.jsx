import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import App from "./App";
import { AuthProvider } from "./auth";

const USER = { user_id: 1, name: "Demo Analyst", email: "analyst@bankx.demo", role: "analyst" };

const YESTERDAY = {
  calculation_date: "2026-09-20", car_pct: 12.0, lcr_pct: 140, npl_ratio_pct: 4.0, nim_pct: 2.6,
  cost_to_income_pct: 55, roe_pct: 9, total_assets_usd: 5_000_000, dollarization_ratio_pct: 60,
  assumptions_applied: [],
};
const TODAY = {
  calculation_date: "2026-09-21", car_pct: 12.4, lcr_pct: 142, npl_ratio_pct: 5.8, nim_pct: 2.4,
  cost_to_income_pct: 48, roe_pct: 11, total_assets_usd: 5_250_000, dollarization_ratio_pct: 45,
  assumptions_applied: [
    "DEPOSIT_RATE_BY_TYPE placeholder (nim_pct)",
    "REGION_CURRENCY placeholder (cost_to_income_pct, roe_pct)",
    "tier1_capital-as-equity proxy (roe_pct)",
  ],
};

function breakdownFor(key) {
  return {
    key, calculation_date: TODAY.calculation_date, value: TODAY[key],
    previous_value: YESTERDAY[key], previous_calculation_date: YESTERDAY.calculation_date,
    formula: "NPL ratio = Loans 90+ days past due ÷ Total loans outstanding × 100, all converted to USD",
    components: [
      { label: "Loans 90+ days past due (USD)", value: 500000, formatted: "$500,000" },
      { label: "Total loans outstanding (USD)", value: 2098462, formatted: "$2,098,462" },
    ],
    fx_notes: [],
    mismatch_note: null,
    assumptions_applied: [],
    history_series: [],
  };
}

// Routes a fetch call by URL to a canned response.
function stubApi({ latest = TODAY, history = [YESTERDAY, TODAY], latestStatus = 200, login } = {}) {
  const calls = [];
  const respond = (status, body) => ({ ok: status < 400, status, json: async () => body });
  const fetchMock = vi.fn(async (url, init = {}) => {
    calls.push({ url, method: init.method || "GET", body: init.body });
    if (url.endsWith("/auth/login")) return login ? login(init) : respond(200, { access_token: "tok", token_type: "bearer", user: USER });
    if (url.endsWith("/kpi-summary/latest")) return respond(latestStatus, latestStatus === 200 ? latest : { detail: latestStatus === 404 ? "No KPI data loaded yet" : "Database unavailable" });
    if (url.includes("/kpi-summary/history")) return respond(200, history);
    const breakdownMatch = url.match(/kpi-summary\/([^/]+)\/breakdown/);
    if (breakdownMatch) return respond(200, breakdownFor(breakdownMatch[1]));
    return respond(404, { detail: "unexpected" });
  });
  vi.stubGlobal("fetch", fetchMock);
  return { calls, fetchMock };
}

function signIn() {
  localStorage.setItem("bdp_token", "tok");
  localStorage.setItem("bdp_user", JSON.stringify(USER));
}

function renderApp(path = "/") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AuthProvider>
        <App />
      </AuthProvider>
    </MemoryRouter>,
  );
}

const tiles = () => within(screen.getByRole("list", { name: "Key indicators" })).getAllByRole("listitem");
const tile = (label) => tiles().find((t) => within(t).queryByText(label));

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-09-21T09:00:00Z"));
});
afterEach(() => vi.useRealTimers());

describe("sign in", () => {
  it("sends signed-out visitors to the sign-in page", async () => {
    stubApi();
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  it("signs in, stores the session and lands on the dashboard", async () => {
    const { calls } = stubApi();
    const user = userEvent.setup();
    renderApp("/");
    await user.type(await screen.findByLabelText(/email/i), "analyst@bankx.demo");
    await user.type(screen.getByLabelText("Password"), "secret");
    await user.click(screen.getByRole("button", { name: "Sign in" }));

    expect(await screen.findByRole("list", { name: "Key indicators" })).toBeInTheDocument();
    expect(JSON.parse(calls.find((c) => c.url.endsWith("/auth/login")).body)).toEqual({ email: "analyst@bankx.demo", password: "secret" });
    expect(localStorage.getItem("bdp_token")).toBe("tok");
    expect(screen.getByText(/Demo Analyst/)).toBeInTheDocument();
  });

  it("shows the server's message for a wrong password and stays on the form", async () => {
    stubApi({ login: async () => ({ ok: false, status: 401, json: async () => ({ detail: "Incorrect email or password" }) }) });
    const user = userEvent.setup();
    renderApp("/login");
    await user.type(await screen.findByLabelText(/email/i), "analyst@bankx.demo");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Incorrect email or password");
    expect(localStorage.getItem("bdp_token")).toBeNull();
  });

  it("signs out when the API says the token is no longer valid", async () => {
    signIn();
    stubApi({ latestStatus: 401 });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(localStorage.getItem("bdp_token")).toBeNull();
  });
});

describe("executive summary", () => {
  beforeEach(signIn);

  it("renders all 8 tiles with value, change since the previous day, and status", async () => {
    stubApi();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });
    expect(tiles()).toHaveLength(8);

    const car = tile("Capital ratio (CAR)");
    expect(within(car).getByText("12.4%")).toBeInTheDocument();
    expect(within(car).getByText("+0.4 pts")).toBeInTheDocument();
    expect(within(car).getByText(/vs 20 Sep/)).toBeInTheDocument();
    expect(within(car).getByText("Action needed")).toBeInTheDocument();

    expect(within(tile("Liquidity ratio (LCR)")).getByText("On track")).toBeInTheDocument();
    expect(within(tile("Total assets")).getByText("$5.25M")).toBeInTheDocument();
    expect(within(tile("Total assets")).getByText("No limit set")).toBeInTheDocument();
  });

  it("marks exactly the three assumption-based tiles, and names the assumption on hover", async () => {
    stubApi();
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });

    expect(screen.getAllByRole("button", { name: /assumption/i })).toHaveLength(3);
    expect(within(tile("Capital ratio (CAR)")).queryByRole("button")).toBeNull();

    await user.hover(within(tile("Net interest margin")).getByRole("button", { name: /assumption/i }));
    expect(await screen.findByRole("tooltip")).toHaveTextContent("DEPOSIT_RATE_BY_TYPE placeholder (nim_pct)");

    await user.unhover(within(tile("Net interest margin")).getByRole("button", { name: /assumption/i }));
    await user.hover(within(tile("Return on equity")).getByRole("button", { name: /assumption/i }));
    const roeTip = await screen.findByRole("tooltip");
    expect(roeTip).toHaveTextContent("REGION_CURRENCY placeholder");
    expect(roeTip).toHaveTextContent("tier1_capital-as-equity proxy");
    expect(roeTip).toHaveTextContent("not verified accounting");
  });

  it("makes every tile a link to its own KPI detail page", async () => {
    stubApi();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });
    expect(within(tile("Bad loans (NPL ratio)")).getByRole("link")).toHaveAttribute("href", "/kpi/npl_ratio_pct");
    expect(within(tile("Capital ratio (CAR)")).getByRole("link")).toHaveAttribute("href", "/kpi/car_pct");
  });

  it("generates the alert strip from the actual values and links each line to its KPI detail page", async () => {
    stubApi();
    renderApp("/");
    const worst = await screen.findByRole("link", { name: /Capital ratio at 12.4% — only 0.4 points above the regulatory minimum of 12.0%/ });
    expect(worst).toHaveAttribute("href", "/kpi/car_pct");
    expect(screen.getByRole("link", { name: /Bad loans at 5.8% — 0.8 points over the internal limit of 5.0%/ })).toBeInTheDocument();
  });

  it("is honest about a single day of history", async () => {
    stubApi({ history: [TODAY] });
    renderApp("/");
    expect(await screen.findByText(/1 day of history so far/)).toBeInTheDocument();
    expect(within(tile("Capital ratio (CAR)")).getByText("No earlier period yet")).toBeInTheDocument();
  });

  it("lets you look at an earlier date, updating tiles and alerts together", async () => {
    stubApi();
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });

    await user.selectOptions(screen.getByLabelText("Date"), "2026-09-20");
    expect(within(tile("Capital ratio (CAR)")).getByText("12.0%")).toBeInTheDocument();
    expect(within(tile("Capital ratio (CAR)")).getByText("No earlier period yet")).toBeInTheDocument();
    expect(screen.getByText(/Data as of 20 Sep/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Capital ratio at 12.0% — only 0.0 points above/ })).toBeInTheDocument();
  });

  it("offers a table view with every trend value", async () => {
    stubApi();
    const user = userEvent.setup();
    renderApp("/");
    await user.click(await screen.findByRole("button", { name: "Show as table" }));
    const table = screen.getByRole("table");
    expect(within(table).getByText("21 Sept 2026")).toBeInTheDocument();
    expect(within(table).getByText("20 Sept 2026")).toBeInTheDocument();
    expect(within(table).getAllByText("12.4%")).toHaveLength(1);
  });

  it("warns when the data is stale", async () => {
    stubApi({ latest: { ...TODAY, calculation_date: "2026-09-15" }, history: [{ ...TODAY, calculation_date: "2026-09-15" }] });
    renderApp("/");
    expect(await screen.findByText(/These numbers are 6 days old/)).toBeInTheDocument();
  });

  it("does not call an older date 'stale' when the user chose to look at it", async () => {
    const old = { ...YESTERDAY, calculation_date: "2026-09-16" };
    stubApi({ history: [old, TODAY] });
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });
    await user.selectOptions(screen.getByLabelText("Date"), "2026-09-16");
    expect(screen.getByText(/Data as of 16 Sep/)).toBeInTheDocument();
    expect(screen.queryByText(/days old/)).toBeNull();
  });

  it("shows a friendly empty state before the first pipeline run", async () => {
    stubApi({ latestStatus: 404 });
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "No numbers yet" })).toBeInTheDocument();
  });

  it("shows the server error and can retry", async () => {
    const { fetchMock } = stubApi({ latestStatus: 503 });
    const user = userEvent.setup();
    renderApp("/");
    expect(await screen.findByText("Database unavailable")).toBeInTheDocument();

    const before = fetchMock.mock.calls.length;
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(fetchMock.mock.calls.length).toBeGreaterThan(before);
  });

  it("clicking a tile opens that KPI's own detail page with a real component breakdown, not another screen", async () => {
    stubApi();
    const user = userEvent.setup();
    renderApp("/");
    await screen.findByRole("list", { name: "Key indicators" });
    await user.click(within(tile("Bad loans (NPL ratio)")).getByRole("link"));
    expect(await screen.findByRole("heading", { name: "Bad loans (NPL ratio)" })).toBeInTheDocument();
    expect(screen.getByText(/NPL ratio = Loans 90\+ days past due/)).toBeInTheDocument();
    expect(screen.getByText("$500,000")).toBeInTheDocument();
  });
});
