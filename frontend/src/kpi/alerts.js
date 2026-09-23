import { KPIS } from "./kpiConfig";
import { daysOld, formatDayShort, formatPct, formatPoints, formatValue } from "./format";
import { statusOf } from "./status";

// Words for the placeholder-assumption KPIs, so an alert never presents them as verified accounting.
const ASSUMPTION_KEYS = new Set(["nim_pct", "cost_to_income_pct", "roe_pct"]);

// Exported so the KPI detail page can quote the same "distance to the limit" phrasing the alert
// strip uses, instead of a differently-worded duplicate.
export function sentence(kpi, value, status) {
  const v = formatValue(kpi, value);
  const name = kpi.short;
  if (status === "good" || status === "none") return `${name} comfortable at ${v}`;

  if (kpi.limit != null) {
    // gap > 0 means on the safe side of the limit
    const gap = kpi.direction === "higher" ? value - kpi.limit : kpi.limit - value;
    const line = `the ${kpi.limitLabel} of ${formatPct(kpi.limit)}`;
    if (gap < 0) {
      return `${name} at ${v} — ${formatPoints(gap)} ${kpi.direction === "higher" ? "below" : "over"} ${line}`;
    }
    return `${name} at ${v} — only ${formatPoints(gap)} ${kpi.direction === "higher" ? "above" : "under"} ${line}`;
  }
  const edge = formatPct(kpi.red);
  return status === "action"
    ? `${name} at ${v} — beyond the action limit of ${edge}`
    : `${name} at ${v} — approaching the action limit of ${edge}`;
}

/**
 * 3-5 plain-language lines generated from the KPI values against the configured thresholds
 * (never hardcoded strings): worst first, padded with good news so the strip is never empty.
 * Each line carries the route to the detail screen behind it.
 */
export function buildAlerts(row, { now = new Date(), maxLines = 5, minLines = 3, checkStale = true } = {}) {
  const lines = [];

  // Only the newest data can be "stale"; someone deliberately browsing an old date already knows it's old.
  if (checkStale && row?.calculation_date) {
    const age = daysOld(row.calculation_date, now);
    if (age >= 2) {
      lines.push({
        tone: "warning", key: "stale", to: null,
        text: `These numbers are ${age} days old — last calculated ${formatDayShort(row.calculation_date)}`,
      });
    }
  }

  const ranked = KPIS.map((kpi) => {
    const value = row?.[kpi.key];
    const status = statusOf(kpi, value);
    return { kpi, value, status };
  });

  const toLine = ({ kpi, value, status }) => ({
    tone: status === "action" ? "critical" : status === "watch" ? "warning" : "good",
    key: kpi.key,
    to: `/kpi/${kpi.key}`,
    text: sentence(kpi, value, status) + (ASSUMPTION_KEYS.has(kpi.key) ? " (assumption-based)" : ""),
  });

  const worse = ranked.filter((r) => r.status === "action").map(toLine);
  const watch = ranked.filter((r) => r.status === "watch").map(toLine);
  const good = ranked.filter((r) => r.status === "good").map(toLine);

  lines.push(...worse, ...watch);
  for (const g of good) {
    if (lines.length >= minLines) break;
    lines.push(g);
  }
  return lines.slice(0, maxLines);
}
