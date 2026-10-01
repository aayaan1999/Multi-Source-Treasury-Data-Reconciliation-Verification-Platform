// When a task was created, for the Tasks list's "Created" column and date filter.

/** Tasklist's creationDate ("2026-09-30T13:40:11.452+0000") as a Date. The "+0000" offset isn't ISO 8601,
 * and not every browser reads it, so it becomes "+00:00" first. Null when missing or unreadable. */
export function createdAt(task) {
  const raw = task?.creationDate;
  if (!raw) return null;
  const d = new Date(String(raw).replace(/([+-]\d{2})(\d{2})$/, "$1:$2"));
  return Number.isNaN(d.getTime()) ? null : d;
}

/** The calendar day the task was created on, in the viewer's own time zone ("2026-09-30"). */
export function createdDay(task) {
  const d = createdAt(task);
  if (!d) return null;
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

/** Whether a task was created between two days ("YYYY-MM-DD", either may be empty), both included.
 * A task with no creation date only passes when no range is set. */
export function createdBetween(task, from, to) {
  if (!from && !to) return true;
  const day = createdDay(task);
  if (!day) return false;
  return (!from || day >= from) && (!to || day <= to);
}
