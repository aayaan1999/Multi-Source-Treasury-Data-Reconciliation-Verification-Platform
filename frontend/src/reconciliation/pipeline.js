// Helpers for the "Received vs kept, per source" section (specs/pipeline-reconciliation.md, FLOW-3).

const TOLERANCE = 0.005;   // same as the notebook's AMOUNT_TOLERANCE: smaller is float noise, not a gap

/** Bank-wide tables (FX rates, capital, liquidity) have no country; the pipeline tags them "Group". */
export function countryLabel(country) {
  return country === "Group" ? "Bank-wide (all countries)" : country;
}

export function fmtAmount(n) {
  return Number(n ?? 0).toLocaleString("en-US", { maximumFractionDigits: 2 });
}

/** One line per currency, biggest gap first (by size, either sign). Never summed across
 * currencies: USD + LBP means nothing. Row-only tables have no amounts -> []. */
export function currencyLines(amountsByCurrency) {
  return Object.entries(amountsByCurrency || {})
    .map(([currency, v]) => ({ currency, received: v.received, clean: v.clean, gap: v.gap }))
    .sort((a, b) => Math.abs(b.gap) - Math.abs(a.gap) || a.currency.localeCompare(b.currency));
}

/** The table's "Amount gap" cell: the biggest currency gap, plus how many others moved. */
export function gapSummary(amountsByCurrency) {
  const moved = currencyLines(amountsByCurrency).filter((l) => Math.abs(l.gap) > TOLERANCE);
  if (!moved.length) return "—";
  const first = `${moved[0].currency} ${fmtAmount(moved[0].gap)}`;
  return moved.length > 1 ? `${first} · +${moved.length - 1} more` : first;
}

// ---- Reconciliation tasks (specs/reconciliation-approvals.md) ------------------------------------

export const STATUS_LABEL = {
  OPEN: "Open",
  MATCHED: "Matched",
  WITH_TEAM: "With the team",
  AWAITING_CFO: "Waiting for CFO approval",
  DECIDED: "Decided",
  APPROVED: "Approved by the CFO",
  SUPERSEDED: "Replaced by a newer run",
  // the retired CFO-first process, for history
  WITH_CFO: "With CFO",
  ASSIGNED: "Assigned",
  SUBMITTED: "Awaiting CFO approval",
};

/** The Status cell: the step in words, with the decision once there is one. */
export function statusText(item) {
  const label = STATUS_LABEL[item.status] || item.status;
  const decision = { ACCEPT: "accepted", CORRECT: "corrected", DISMISS: "dismissed" }[item.decision];
  return decision && ["AWAITING_CFO", "DECIDED", "APPROVED"].includes(item.status) ? `${label} (${decision})` : label;
}

// Key columns identify a record, so they can't be corrected (same list as the backend's KEY_COLUMNS).
const KEY_COLUMNS = {
  branches: ["branch_id"], customers: ["customer_id"], accounts: ["account_id"], loans: ["loan_id"],
  transactions: ["transaction_id"], capital_positions: ["month"], liquidity_daily: ["date"], fx_rates: ["date", "currency_pair"],
};

/** Fields of a rejected record that a correction can be proposed for. */
export function correctableFields(recordData, sourceTable) {
  const keys = KEY_COLUMNS[sourceTable] || [];
  return Object.keys(recordData || {}).filter((f) => !keys.includes(f));
}
