import { isNum } from "./format";

// "good" | "watch" | "action" | "none" (no limits configured) | "unknown" (no value)
export function statusOf(kpi, value) {
  if (!isNum(value)) return "unknown";
  if (kpi.red == null || kpi.amber == null) return "none";
  if (kpi.direction === "higher") {
    if (value < kpi.red) return "action";
    if (value < kpi.amber) return "watch";
    return "good";
  }
  if (value >= kpi.red) return "action";
  if (value >= kpi.amber) return "watch";
  return "good";
}

export const STATUS_META = {
  good: { label: "On track", color: "var(--good)" },
  watch: { label: "Watch", color: "var(--warning)" },
  action: { label: "Action needed", color: "var(--critical)" },
  none: { label: "No limit set", color: "var(--neutral-bar)" },
  unknown: { label: "No data", color: "var(--neutral-bar)" },
};

// Change since the previous period. Ratios move in percentage points; total assets in relative %.
// tone says whether the move is good/bad for the bank (direction x whether up is good), so an arrow
// pointing up on NPL reads as bad without relying on colour alone (the UI adds a "worse" label).
export function computeDelta(kpi, current, previous) {
  if (!isNum(current) || !isNum(previous)) return null;
  const diff = kpi.unit === "usd" ? (previous === 0 ? 0 : ((current - previous) / Math.abs(previous)) * 100) : current - previous;
  if (Math.abs(diff) < 0.05) return { direction: "flat", tone: "neutral", text: "no change" };
  const direction = diff > 0 ? "up" : "down";
  const improved = kpi.direction === "higher" ? diff > 0 : diff < 0;
  const magnitude = Math.abs(diff).toFixed(1);
  const sign = diff > 0 ? "+" : "−";
  const text = kpi.unit === "usd" ? `${sign}${magnitude}%` : `${sign}${magnitude} pts`;
  return { direction, tone: improved ? "good" : "bad", text };
}
