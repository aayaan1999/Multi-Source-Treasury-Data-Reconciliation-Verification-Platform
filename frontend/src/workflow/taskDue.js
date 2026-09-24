// Deadlines and ordering for the Tasks list (specs/task-cases.md sections 4-5). Due days come from
// the task policy (GET /workflow/policy, app_settings['task.due_days']).

const SEVERITY_RANK = { HIGH: 0, MEDIUM: 1, LOW: 2 };
const DAY_MS = 86400000;

function addDays(iso, days) {
  const d = new Date(iso);
  return new Date(Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() + days)).toISOString().slice(0, 10);
}

/** A task's due date (YYYY-MM-DD), or null when there's nothing to go on. A case carries its own
 * (dueDate variable); other tasks are due N days after they were created. */
export function taskDue(task, dueDays, breach) {
  if (task.vars.dueDate) return task.vars.dueDate;
  if (breach?.due_date) return breach.due_date;             // set by the breach check (specs/breach-levels.md)
  if (!task.creationDate || !dueDays) return null;
  const days = {
    data_quality: dueDays.DATA_QUALITY,
    reconciliation: dueDays.RECONCILIATION,
    breach: breach?.resolution_days,
    fraud: dueDays.MEDIUM,                    // a single-flag task from before cases
    entity_match: dueDays.DUPLICATE,
    recon_group: dueDays.RECON_GROUP,
  }[task.vars.recordType];
  return Number.isFinite(days) ? addDays(task.creationDate, days) : null;
}

export function isOverdue(due, today = new Date()) {
  if (!due) return false;
  const startOfToday = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  return Date.parse(`${due}T00:00:00Z`) < startOfToday;
}

/** Overdue first, then most severe, then soonest due; undated last. */
export function byUrgency(today = new Date()) {
  return (a, b) =>
    isOverdue(b.due, today) - isOverdue(a.due, today)
    || (SEVERITY_RANK[a.severity] ?? 3) - (SEVERITY_RANK[b.severity] ?? 3)
    || (a.due ? Date.parse(a.due) : Infinity) - (b.due ? Date.parse(b.due) : Infinity)
    || 0;
}

export function daysLeftText(due, today = new Date()) {
  if (!due) return "—";
  const startOfToday = Date.UTC(today.getFullYear(), today.getMonth(), today.getDate());
  const days = Math.round((Date.parse(`${due}T00:00:00Z`) - startOfToday) / DAY_MS);
  if (days < 0) return `${-days} day${days === -1 ? "" : "s"} overdue`;
  if (days === 0) return "Due today";
  return `${days} day${days === 1 ? "" : "s"} left`;
}
