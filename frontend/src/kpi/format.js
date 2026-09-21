const usdCompact = new Intl.NumberFormat("en-US", {
  style: "currency", currency: "USD", notation: "compact", minimumFractionDigits: 0, maximumFractionDigits: 2,
});

export function isNum(v) {
  return typeof v === "number" && Number.isFinite(v);
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

export function daysOld(iso, now = new Date()) {
  const today = Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate());
  return Math.round((today - parseDay(iso).getTime()) / 86_400_000);
}
