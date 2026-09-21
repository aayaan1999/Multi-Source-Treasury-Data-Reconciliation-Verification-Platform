import { isNum } from "../kpi/format";

// PLACEHOLDER: the regulatory single-borrower limit (exposure as a % of capital) is jurisdiction-specific and comes
// from the client's regulator. 25% is the common Basel-style large-exposure limit, used here only so the "over limit"
// highlight has something to test against. Confirm, then move it into a settings table.
export const SINGLE_BORROWER_LIMIT_PCT = 25;

// The internal NPL limit shown as the reference on the (cut) bad-loan trend panel: same figure as Screen 1's NPL limit.
export const NPL_REFERENCE_LIMIT_PCT = 5;

export const IFRS_STAGES = {
  1: "Stage 1 — healthy",
  2: "Stage 2 — worrying",
  3: "Stage 3 — already bad",
};

// days_past_due ranges per ageing bucket, exactly as notebooks/06 assigns them (`< 30` -> "1-30", `< 60` -> "31-60", ...).
// NOTE: that means a loan at exactly 30, 60, 90 or 180 days falls into the NEXT bucket, so the labels read one day
// early. If the notebook's boundaries are corrected to `<=`, update this map to match.
export const AGEING_RANGES = {
  Current: [0, 0],
  "1-30": [1, 29],
  "31-60": [30, 59],
  "61-90": [60, 89],
  "90-180": [90, 179],
  "180+": [180, null],
};

// Loans 31-90 days late aren't officially bad yet, but most become bad next quarter: the buckets to watch.
export const AGEING_WATCH = new Set(["31-60", "61-90"]);

export const LTV_UNCOVERED = ">100%";

const sum = (rows, key) => rows.reduce((total, r) => total + (isNum(r[key]) ? r[key] : 0), 0);

/** The five boxes at the top of Screen 2, derived from the loan-stage summary and the product breakdown. */
export function topStrip(stages, productBreakdown) {
  const grossLoans = sum(stages, "outstanding_usd");
  const provisions = sum(stages, "provisions_usd");
  const nplAmount = sum(productBreakdown, "bad_loan_outstanding_usd");
  return {
    grossLoans,
    nplAmount,
    nplRatio: grossLoans > 0 ? (nplAmount / grossLoans) * 100 : null,
    coverageRatio: nplAmount > 0 ? (provisions / nplAmount) * 100 : null,
    provisions,
    // needs the year's provision *charge* over average gross loans; the pipeline holds only today's balances
    costOfRisk: null,
  };
}

/** "Top 20 borrowers = X% of gross loans" — a number risk committees always want. */
export function concentration(topExposures, grossLoans) {
  const top = sum(topExposures, "outstanding_usd");
  return { count: topExposures.length, pct: grossLoans > 0 ? (top / grossLoans) * 100 : null };
}

/** Coverage below ~50% means the bank hasn't faced up to its losses yet (source document). */
export function coverageStatus(coveragePct) {
  if (!isNum(coveragePct)) return "unknown";
  return coveragePct < 50 ? "watch" : "good";
}

export const FILTER_KEYS = ["product", "segment", "branch", "currency", "stage", "customer", "ageing", "ltv", "bad"];

/** Filters live in the URL (?product=Corporate&bad=1) so a Screen 1 tile click, a bookmark or a refresh all land in the same view. */
export function parseFilters(searchParams) {
  const filters = {};
  for (const key of FILTER_KEYS) {
    const value = searchParams.get(key);
    if (value) filters[key] = value;
  }
  if (searchParams.get("filter") === "npl") filters.bad = "1"; // the link Screen 1's NPL tile uses
  return filters;
}

/** Turns the filters into the query the loans endpoint understands. */
export function loanParams(filters) {
  const params = {};
  if (filters.product) params.product = filters.product;
  if (filters.segment) params.segment = filters.segment;
  if (filters.branch) params.branch_id = filters.branch;
  if (filters.currency) params.currency = filters.currency;
  if (filters.stage) params.stage = filters.stage;
  if (filters.customer) params.customer_id = filters.customer;
  if (filters.ltv) params.ltv_bucket = filters.ltv;
  let min = null;
  let max = null;
  if (filters.ageing && AGEING_RANGES[filters.ageing]) [min, max] = AGEING_RANGES[filters.ageing];
  if (filters.bad) min = Math.max(min ?? 0, 90); // bad loan = 90+ days past due
  if (min !== null) params.min_days_past_due = min;
  if (max !== null) params.max_days_past_due = max;
  return params;
}

/** Human-readable chips for whatever is currently filtered. */
export function describeFilters(filters, branchNames = {}) {
  const chips = [];
  if (filters.product) chips.push(["product", `Product: ${filters.product}`]);
  if (filters.segment) chips.push(["segment", `Segment: ${filters.segment}`]);
  if (filters.branch) chips.push(["branch", `Branch: ${branchNames[filters.branch] ?? filters.branch}`]);
  if (filters.currency) chips.push(["currency", `Currency: ${filters.currency}`]);
  if (filters.stage) chips.push(["stage", IFRS_STAGES[filters.stage] ?? `Stage ${filters.stage}`]);
  if (filters.customer) chips.push(["customer", `Customer: ${filters.customer}`]);
  if (filters.ageing) chips.push(["ageing", `Days late: ${filters.ageing}`]);
  if (filters.ltv) chips.push(["ltv", `LTV: ${filters.ltv}`]);
  if (filters.bad) chips.push(["bad", "Bad loans only (90+ days late)"]);
  return chips;
}
