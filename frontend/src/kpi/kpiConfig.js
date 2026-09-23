// The 8 Executive Summary KPIs (specs/screen-01-executive-summary.md).
//
// THRESHOLDS ARE DEMO PLACEHOLDERS. The source document says each KPI's red/amber limit lives in an
// adjustable settings table (every regulator sets its own floors) but gives no numbers and no such
// table exists yet. The values below are illustrative, anchored on the few figures the document
// mentions (CAR minimum ~12%, NPL "usually 3-5%", cost-to-income "above 60%", LCR 100% Basel floor).
// Confirm with whoever owns the source document, then move them into a settings table.
//
// direction: "higher" = higher is better (status turns amber below `amber`, red below `red`);
//            "lower"  = lower is better  (amber at/above `amber`, red at/above `red`).
// limit/limitLabel: the regulatory or internal line drawn on the trend chart and quoted in alerts.

export const KPIS = [
  {
    key: "car_pct", label: "Capital ratio (CAR)", short: "Capital ratio", unit: "pct",
    direction: "higher", amber: 15, red: 12.5, limit: 12, limitLabel: "regulatory minimum",
    hint: "Do we have enough of our own money as a cushion?",
  },
  {
    key: "lcr_pct", label: "Liquidity ratio (LCR)", short: "Liquidity", unit: "pct",
    direction: "higher", amber: 120, red: 100, limit: 100, limitLabel: "regulatory minimum",
    hint: "If lots of people withdrew money tomorrow, could we pay them?",
  },
  {
    key: "npl_ratio_pct", label: "Bad loans (NPL ratio)", short: "Bad loans", unit: "pct",
    direction: "lower", amber: 3, red: 5, limit: 5, limitLabel: "internal limit",
    hint: "What share of our loans aren't being repaid?",
  },
  {
    key: "nim_pct", label: "Net interest margin", short: "Net interest margin", unit: "pct",
    direction: "higher", amber: 2.5, red: 1.5,
    hint: "What do we earn on loans, after paying depositors?",
  },
  {
    key: "cost_to_income_pct", label: "Cost-to-income", short: "Cost-to-income", unit: "pct",
    direction: "lower", amber: 50, red: 60, limit: 60, limitLabel: "management watch line",
    hint: "How much do we spend to earn each dollar?",
  },
  {
    key: "roe_pct", label: "Return on equity", short: "Return on equity", unit: "pct",
    direction: "higher", amber: 10, red: 5,
    hint: "What return are shareholders getting?",
  },
  {
    key: "total_assets_usd", label: "Total assets", short: "Total assets", unit: "usd",
    direction: "higher", // no limits: shown for the trend only
    hint: "How big are we?",
  },
  {
    key: "dollarization_ratio_pct", label: "Dollarization ratio", short: "Dollarization", unit: "pct",
    direction: "lower", amber: 50, red: 70, limit: 70, limitLabel: "internal limit",
    hint: "How much of our deposits are in foreign currency?",
  },
];

// The ratios drawn in the trend panels (source doc: "three or four most important ratios").
export const TREND_KEYS = ["car_pct", "lcr_pct", "npl_ratio_pct", "dollarization_ratio_pct"];

export const KPI_BY_KEY = Object.fromEntries(KPIS.map((k) => [k.key, k]));
