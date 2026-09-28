import { formatDay, formatNumber, formatPercentValue, formatUsd, isNum } from "../kpi/format";

// Ask a Question (specs/ask-a-question.md): the pure parts of the answer card, kept out of the
// component so they can be tested on their own.

/** One table cell, formatted by its column's unit ("row": the unit comes from the row itself). */
export function formatCell(value, unit, row) {
  const u = unit === "row" ? row?.unit : unit;
  if (value === null || value === undefined) return "—";
  if (u === "usd") return formatUsd(value);
  if (u === "pct") return formatPercentValue(value, 1);
  if (u === "count") return formatNumber(value, 0);
  if (u === "number") return isNum(value) ? formatNumber(value, Number.isInteger(value) ? 0 : 2) : String(value);
  if (u === "date") return /^\d{4}-\d{2}-\d{2}$/.test(value) ? formatDay(value) : String(value);
  return String(value);
}

export const NUMERIC_UNITS = new Set(["usd", "pct", "count", "number", "row"]);

const PERIOD_KEYS = ["date_from", "date_to", "period_label"];

/**
 * The filters to re-run with after a chip is removed (value === null) or changed to another option.
 * Removing the period goes back to the latest data; choosing "All measures" (value "") drops the metric.
 */
export function refinedFilters(filters, key, value) {
  const next = { ...filters };
  if (key === "period") {
    PERIOD_KEYS.forEach((k) => delete next[k]);
    return next;
  }
  if (value === null || value === "") delete next[key];
  else next[key] = value;
  if (key === "metric" && !value) delete next.order;   // an order only means something for one measure
  return next;
}
