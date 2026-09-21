// Screen 3 helpers: report-calendar urgency and how a stored figure is printed on the form.
// Days-left depends on today's date, so it is worked out here in the browser (the API returns raw due dates).

export const STATUS_LABEL = {
  NOT_STARTED: "Not started",
  DRAFT: "Draft",
  IN_REVIEW: "Under review",
  UNDER_REVIEW: "Under review",
  APPROVED: "Approved",
  SUBMITTED: "Submitted",
};

export const RED_DAYS = 5;
export const AMBER_DAYS = 10;

export const statusLabel = (status) => STATUS_LABEL[String(status ?? "").toUpperCase()] ?? String(status ?? "—");
const isSubmitted = (r) => String(r.status).toUpperCase() === "SUBMITTED";
const isPending = (r) => ["DRAFT", "IN_REVIEW", "UNDER_REVIEW", "APPROVED"].includes(String(r.status).toUpperCase());

/** Whole days from `today` to a "YYYY-MM-DD" due date (negative = overdue). Uses UTC midnights so daylight saving can't shift it. */
export function daysLeft(dueDate, today = new Date()) {
  if (!dueDate) return null;
  const [y, m, d] = String(dueDate).slice(0, 10).split("-").map(Number);
  const due = Date.UTC(y, m - 1, d);
  const now = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Math.round((due - now) / 86400000);
}

/** Submitted is green whatever the date; otherwise overdue or under 5 days is red, under 10 amber, the rest green. */
export function urgency(row, today = new Date()) {
  if (isSubmitted(row)) return "good";
  const left = daysLeft(row.due_date, today);
  if (left === null) return "unknown";
  if (left < RED_DAYS) return "action";
  if (left < AMBER_DAYS) return "watch";
  return "good";
}

export function daysLeftText(row, today = new Date()) {
  if (isSubmitted(row)) return "Submitted";
  const left = daysLeft(row.due_date, today);
  if (left === null) return "No due date";
  if (left < 0) return `${-left} day${left === -1 ? "" : "s"} overdue`;
  if (left === 0) return "Due today";
  return `${left} day${left === 1 ? "" : "s"} left`;
}

/** The four numbers above the calendar. "Due this month" counts reports whose due date falls in today's month. */
export function calendarCounts(rows, today = new Date()) {
  const sameMonth = (r) => {
    const [y, m] = String(r.due_date ?? "").split("-").map(Number);
    return y === today.getFullYear() && m === today.getMonth() + 1;
  };
  return {
    dueThisMonth: rows.filter(sameMonth).length,
    submitted: rows.filter(isSubmitted).length,
    pendingApproval: rows.filter(isPending).length,
    overdue: rows.filter((r) => !isSubmitted(r) && (daysLeft(r.due_date, today) ?? 0) < 0).length,
  };
}

/** A stored figure as printed on the form: whole units with thousands separators and negatives in brackets, or a percentage. */
export function formatLine(unit, value) {
  if (value === null || value === undefined || value === "") return "—";
  const n = Number(value);
  if (!Number.isFinite(n)) return "—";
  if (unit === "percent") return `${n.toFixed(2)}%`;
  const whole = Math.round(Math.abs(n));
  const text = whole.toLocaleString("en-US");
  return n < 0 && whole !== 0 ? `(${text})` : text;
}

/** Change against the prior period, or the honest reason there isn't one. */
export function formatChange(row) {
  if (row.change === null || row.change === undefined) return "N/A";
  const sign = row.change < 0 ? "−" : "+";
  const abs = Math.abs(Number(row.change));
  const body = row.unit === "percent" ? `${abs.toFixed(2)} pts` : formatLine("currency", abs);
  return row.change_pct === null || row.change_pct === undefined ? `${sign}${body}` : `${sign}${body} (${sign}${Math.abs(row.change_pct).toFixed(1)}%)`;
}
