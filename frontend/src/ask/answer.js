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

// ---- the AI assistant's chat answer (client demo deck, slide 12) ------------------------------------

/** Where "View records" goes for each approved query: the screen that shows the rows behind the answer. */
export const DRILL = {
  kpi_value: { to: "/", label: "Open summary" },
  country_breakdown: { to: "/", label: "Open summary" },
  branch_ranking: { to: "/performance", label: "View in Branch & segment" },
  segment_performance: { to: "/performance", label: "View in Branch & segment" },
  product_performance: { to: "/performance", label: "View in Branch & segment" },
  loan_breakdown: { to: "/portfolio", label: "View loans" },
  ifrs9_stages: { to: "/portfolio", label: "View loans" },
  top_exposures: { to: "/portfolio", label: "View loans" },
  loan_ageing: { to: "/portfolio", label: "View loans" },
  data_quality: { to: "/reconciliation", label: "View records" },
  limit_breaches: { to: "/audit-oversight", label: "View breaches" },
};

const isMeasure = (c) => NUMERIC_UNITS.has(c.unit) && c.key !== "rank";

/** The answer's shape: its name column (if any) and the measures, in table order. */
export function answerShape(answer) {
  const columns = answer.columns || [];
  return { name: columns.find((c) => c.unit === "text"), measures: columns.filter(isMeasure) };
}

/**
 * The one-line summary above an answer, as { lead, rest }: the lead is shown in bold. Built only from the
 * rows the database returned - never invented - and says which row comes first only when the answer is
 * sorted by a measure.
 */
export function summarise(answer) {
  const rows = answer.rows || [];
  const label = answer.understood?.label || "Answer";
  const { name, measures } = answerShape(answer);
  if (!rows.length) return { lead: "No rows", rest: `match these filters in ${label}.` };
  const first = rows[0];
  const values = (row, n) => measures.slice(0, n).map((m) => `${m.label} ${formatCell(row[m.key], m.unit, row)}`).join(", ");
  if (rows.length === 1) {
    const who = name ? `${first[name.key]}: ` : "";
    return { lead: `${label}:`, rest: `${who}${values(first, 3)}.` };
  }
  const order = answer.understood?.filters?.order;
  const count = `${formatNumber(rows.length, 0)} rows`;
  if (name && measures.length && (order === "desc" || order === "asc")) {
    return { lead: count, rest: `in ${label}. ${order === "desc" ? "Highest" : "Lowest"}: ${first[name.key]} at ${formatCell(first[measures[0].key], measures[0].unit, first)}.` };
  }
  return { lead: count, rest: `in ${label}.` };
}

/** Bars instead of a table when the answer is one measure across 2-12 named rows (e.g. branches by profit). */
export function barsFor(answer) {
  const rows = answer.rows || [];
  const { name, measures } = answerShape(answer);
  if (!name || measures.length !== 1 || rows.length < 2 || rows.length > 12) return null;
  const m = measures[0];
  if (!rows.every((r) => isNum(r[m.key]))) return null;
  const max = Math.max(...rows.map((r) => Math.abs(r[m.key]))) || 1;
  return rows.map((r) => ({ label: String(r[name.key]), value: formatCell(r[m.key], m.unit, r), share: Math.abs(r[m.key]) / max, negative: r[m.key] < 0 }));
}
