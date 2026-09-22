const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 2,
});

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
}

// Whole dollars with thousands separators, for tables and tooltips. Compact form ($1.6M) for tiles and axes.
const usdFull = new Intl.NumberFormat("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export function formatUsd(v) {
  return isNum(v) ? usdFull.format(v) : "—";
}

export function formatUsdCompact(v) {
  return isNum(v) ? usdCompact.format(v) : "—";
}

export function formatNumber(v, digits = 0) {
  return isNum(v) ? v.toLocaleString("en-US", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

export function formatPercentValue(v, digits = 1) {
  return isNum(v) ? `${v.toFixed(digits)}%` : "—";
}

export function formatValue(kpi, v) {
  if (!isNum(v)) return "—";
  return kpi.unit === "usd" ? usdCompact.format(v) : `${v.toFixed(1)}%`;
}

// Plain "12.0%" for limits and gaps, without the compact currency handling.
export function formatPct(v) {
  return isNum(v) ? `${v.toFixed(1)}%` : "—";
}

export function formatPoints(v) {
  return `${Math.abs(v).toFixed(1)} ${Math.abs(v).toFixed(1) === "1.0" ? "point" : "points"}`;
}

const dateFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric", timeZone: "UTC" });
const shortFmt = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

// API dates are plain 'YYYY-MM-DD' calendar dates: parse as UTC so the day never shifts with the viewer's timezone.
export function parseDay(iso) {
  return new Date(`${iso}T00:00:00Z`);
}

export function formatDay(iso) {
  return dateFmt.format(parseDay(iso));
}

export function formatDayShort(iso) {
  return shortFmt.format(parseDay(iso));
}

// Full timestamps (Tasklist/audit_log ISO datetimes), not the plain calendar dates above.
export function formatDateTime(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

export function daysOld(iso, now = new Date()) {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((today - parseDay(iso).getTime()) / 86_400_000);
}
