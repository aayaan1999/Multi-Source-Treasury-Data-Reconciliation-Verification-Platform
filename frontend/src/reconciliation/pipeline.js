// Helpers for the "Received vs kept, per source" section (specs/pipeline-reconciliation.md, FLOW-3).

const TOLERANCE = 0.005;   // same as the notebook's AMOUNT_TOLERANCE: smaller is float noise, not a gap

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

// ---- CFO workflow (specs/cfo-reconciliation-workflow.md, FLOW-5) -----------------------------

// The three user tasks in camunda/process/reconciliation-review.bpmn, by element id or name.
const STEPS = {
  UserTask_CfoReview: "CFO_REVIEW", "CFO review": "CFO_REVIEW",
  UserTask_AssigneeUpdate: "ASSIGNEE_UPDATE", "Update values": "ASSIGNEE_UPDATE",
  UserTask_CfoFinalReview: "CFO_FINAL_REVIEW", "CFO final review": "CFO_FINAL_REVIEW",
};

/** Which step of the reconciliation-review process a Tasklist task is. */
export function taskStep(task) {
  return STEPS[task.taskDefinitionId] || STEPS[task.name] || null;
}

export const STATUS_LABEL = {
  OPEN: "Open",
  MATCHED: "Matched",
  WITH_CFO: "With CFO",
  ASSIGNED: "Assigned",
  SUBMITTED: "Awaiting CFO approval",
  APPROVED: "Approved",
};

/** The Status cell: the workflow step in words, with who it's assigned to. */
export function statusText(item) {
  const label = STATUS_LABEL[item.status] || item.status;
  return item.status === "ASSIGNED" && item.assigned_to_name ? `${label}: ${item.assigned_to_name}` : label;
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
