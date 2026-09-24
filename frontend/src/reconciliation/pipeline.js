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
