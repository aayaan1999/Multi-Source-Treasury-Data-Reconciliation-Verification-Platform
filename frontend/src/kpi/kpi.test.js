import { describe, expect, it } from "vitest";
import { buildAlerts } from "./alerts";
import { daysOld, formatDay, formatValue } from "./format";
import { KPIS, KPI_BY_KEY } from "./kpiConfig";
import { computeDelta, statusOf } from "./status";

const HEALTHY = {
  calculation_date: "2026-09-21",
  car_pct: 18, lcr_pct: 150, npl_ratio_pct: 2, nim_pct: 3.5, cost_to_income_pct: 40, roe_pct: 14,
  total_assets_usd: 5_000_000, dollarization_ratio_pct: 30, assumptions_applied: [],
};
const NOW = new Date("2026-09-21T09:00:00Z");

describe("statusOf", () => {
  const car = KPI_BY_KEY.car_pct; // higher is better: amber < 15, red < 12.5
  it("higher-is-better KPIs turn amber then red as they fall", () => {
    expect(statusOf(car, 15)).toBe("good");
    expect(statusOf(car, 14.9)).toBe("watch");
    expect(statusOf(car, 12.5)).toBe("watch");
    expect(statusOf(car, 12.4)).toBe("action");
  });
  const npl = KPI_BY_KEY.npl_ratio_pct; // lower is better: amber >= 3, red >= 5
  it("lower-is-better KPIs turn amber then red as they rise (limit itself counts)", () => {
    expect(statusOf(npl, 2.9)).toBe("good");
    expect(statusOf(npl, 3)).toBe("watch");
    expect(statusOf(npl, 5)).toBe("action");
  });
  it("has no status without limits or without a value", () => {
    expect(statusOf(KPI_BY_KEY.total_assets_usd, 1)).toBe("none");
    expect(statusOf(car, null)).toBe("unknown");
    expect(statusOf(car, NaN)).toBe("unknown");
  });
});

describe("computeDelta", () => {
  it("reports ratio moves in percentage points and judges them by direction", () => {
    expect(computeDelta(KPI_BY_KEY.car_pct, 13.5, 13.1)).toEqual({ direction: "up", tone: "good", text: "+0.4 pts" });
    expect(computeDelta(KPI_BY_KEY.npl_ratio_pct, 6, 5.2)).toEqual({ direction: "up", tone: "bad", text: "+0.8 pts" });
    expect(computeDelta(KPI_BY_KEY.npl_ratio_pct, 4, 5)).toEqual({ direction: "down", tone: "good", text: "−1.0 pts" });
  });
  it("reports total assets as a relative % change", () => {
    expect(computeDelta(KPI_BY_KEY.total_assets_usd, 1_100_000, 1_000_000)).toEqual({ direction: "up", tone: "good", text: "+10.0%" });
  });
  it("calls tiny moves flat and has nothing to say without a previous value", () => {
    expect(computeDelta(KPI_BY_KEY.car_pct, 13.01, 13)).toMatchObject({ direction: "flat", tone: "neutral" });
    expect(computeDelta(KPI_BY_KEY.car_pct, 13, undefined)).toBeNull();
  });
});

describe("formatting", () => {
  it("formats ratios and compact currency, and dashes for missing values", () => {
    expect(formatValue(KPI_BY_KEY.car_pct, 12.44)).toBe("12.4%");
    expect(formatValue(KPI_BY_KEY.total_assets_usd, 4_200_000)).toBe("$4.2M");
    expect(formatValue(KPI_BY_KEY.car_pct, null)).toBe("—");
  });
  it("treats API dates as calendar days regardless of timezone", () => {
    expect(formatDay("2026-09-21")).toBe("21 Sept 2026");
    expect(daysOld("2026-09-18", NOW)).toBe(3);
    expect(daysOld("2026-09-21", NOW)).toBe(0);
  });
});

describe("buildAlerts", () => {
  it("writes the source document's example sentence from real values", () => {
    const alerts = buildAlerts({ ...HEALTHY, car_pct: 12.4 }, { now: NOW });
    expect(alerts[0]).toMatchObject({ tone: "critical", to: "/scenario" });
    expect(alerts[0].text).toBe("Capital ratio at 12.4% — only 0.4 points above the regulatory minimum of 12.0%");
  });

  it("changes its wording when the numbers change (nothing is hardcoded)", () => {
    const below = buildAlerts({ ...HEALTHY, car_pct: 11.2 }, { now: NOW })[0].text;
    expect(below).toBe("Capital ratio at 11.2% — 0.8 points below the regulatory minimum of 12.0%");
    const over = buildAlerts({ ...HEALTHY, npl_ratio_pct: 5.8 }, { now: NOW })[0].text;
    expect(over).toBe("Bad loans at 5.8% — 0.8 points over the internal limit of 5.0%");
  });

  it("puts the worst first: action, then watch, then good news", () => {
    const alerts = buildAlerts({ ...HEALTHY, car_pct: 12.4, lcr_pct: 110 }, { now: NOW });
    expect(alerts.map((a) => a.tone).slice(0, 2)).toEqual(["critical", "warning"]);
  });

  it("pads a healthy bank to at least three lines and never exceeds five", () => {
    const calm = buildAlerts(HEALTHY, { now: NOW });
    expect(calm.length).toBe(3);
    expect(calm.every((a) => a.tone === "good")).toBe(true);

    const bad = { ...HEALTHY, car_pct: 10, lcr_pct: 90, npl_ratio_pct: 9, nim_pct: 1, cost_to_income_pct: 70, roe_pct: 2 };
    expect(buildAlerts(bad, { now: NOW }).length).toBe(5);
  });

  it("flags stale data as the first line", () => {
    const alerts = buildAlerts({ ...HEALTHY, calculation_date: "2026-09-15" }, { now: NOW });
    expect(alerts[0]).toMatchObject({ key: "stale", tone: "warning", to: null });
    expect(alerts[0].text).toContain("6 days old");
  });

  it("skips the stale warning when asked (browsing an older date on purpose)", () => {
    const alerts = buildAlerts({ ...HEALTHY, calculation_date: "2026-09-15" }, { now: NOW, checkStale: false });
    expect(alerts.some((a) => a.key === "stale")).toBe(false);
  });

  it("labels assumption-based KPIs so they are not presented as verified", () => {
    const alerts = buildAlerts({ ...HEALTHY, roe_pct: 3 }, { now: NOW });
    expect(alerts.find((a) => a.key === "roe_pct").text).toMatch(/\(assumption-based\)$/);
  });

  it("gives every KPI a drill-down route", () => {
    expect(KPIS.every((k) => k.drill.startsWith("/"))).toBe(true);
  });
});
