// Who sees what (specs/user-roles.md). The table itself lives on the server (backend/app/roles.py) and
// comes with the signed-in user as `user.access`; these helpers read it.

// Route -> screen key, as the server names them.
const SCREEN_OF_PATH = [
  ["/kpi/", "summary"], ["/portfolio", "portfolio"], ["/performance", "performance"], ["/scenario", "scenario"],
  ["/reports", "reports"], ["/reconciliation", "reconciliation"], ["/tasks", "tasks"], ["/audit-oversight", "audit"],
  ["/ingestion", "ingestion"], ["/ask", "ask"],
];

export function screenOf(path) {
  if (path === "/") return "summary";
  return SCREEN_OF_PATH.find(([prefix]) => path.startsWith(prefix))?.[1] || null;
}

/** "full", "read", or undefined when this person doesn't use the screen. */
export function screenAccess(user, screen) {
  return user?.access?.screens?.[screen];
}

export function canSee(user, path) {
  const screen = screenOf(path);
  return !screen || Boolean(screenAccess(user, screen));
}

export function homeOf(user) {
  return user?.access?.home || "/";
}

/** Where sign-in takes you: Data ingestion for everyone who uses it, else your home screen. */
export function landingOf(user) {
  return canSee(user, "/ingestion") ? "/ingestion" : homeOf(user);
}

export function roleTitle(user) {
  return user?.access?.title || user?.role || "";
}

// Record types that are reconciliation tasks on the reconciliation-task / run sign-off processes.
const STEPPED = new Set(["reconciliation", "recon_group", "recon_run"]);

/** Whether a Tasklist task belongs in this person's list: by record type, and for reconciliation tasks by
 * the step's group (operations = team review; cfo = CFO approval and run sign-off). */
export function isMyTask(user, task) {
  const rule = user?.access?.tasks || {};
  if (rule.all) return true;
  const type = task.vars?.recordType;
  const groups = task.candidateGroups || [];
  if ((rule.groups || []).some((g) => groups.includes(g)) && (STEPPED.has(type) || !rule.types)) return true;
  if (STEPPED.has(type)) return false;
  return (rule.types || []).includes(type);
}
