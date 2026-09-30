// Helpers for reconciliation tasks (specs/reconciliation-approvals.md): pipeline gaps and core-system break
// groups on the reconciliation-task process, and run sign-offs on reconciliation-run-signoff.

export const RECON_KINDS = ["reconciliation", "recon_group", "recon_run"];

// The user tasks of both processes, by element id or name.
const STEPS = {
  UserTask_TeamReview: "TEAM", "Team review": "TEAM",
  UserTask_CfoApproval: "CFO", "CFO approval": "CFO",
  UserTask_RunSignoff: "SIGNOFF", "Run sign-off": "SIGNOFF",
};

/** Which step a Tasklist task is: TEAM, CFO or SIGNOFF. */
export function stepOf(task) {
  return STEPS[task.taskDefinitionId] || STEPS[task.name] || null;
}

// The team's three decisions: [key, button, what it means].
export const DECISIONS = [
  ["ACCEPT", "Accept", "The difference is explained and fine as it is."],
  ["CORRECT", "Correct our data", "Our copy is wrong: fix it (the CFO approves every fix)."],
  ["DISMISS", "Dismiss", "Not a real problem."],
];
export const DECISION_PAST = { ACCEPT: "accepted", CORRECT: "corrected", DISMISS: "dismissed" };
export const CFO_ROLES = ["approver", "admin"];

/** "Accept all", or "Accept all except 3" once records are left out of a group. */
export function decisionLabel(label, leftOut, total) {
  if (total <= 1) return label;
  return leftOut ? `${label} all except ${leftOut}` : `${label} all`;
}

/** Why this person can't approve or sign off, or null when they can. */
export function blockedReason(step, user, { decidedBy, deciders = [] } = {}) {
  if (step === "TEAM") return null;
  if (!CFO_ROLES.includes(user?.role)) return "Only the CFO or the Platform Administrator can do this step.";
  if (step === "CFO" && decidedBy === user.user_id) return "You made this decision, so a different person has to approve it.";
  if (step === "SIGNOFF") {
    const mine = deciders.filter((id) => id === user.user_id).length;
    if (mine) return `You decided ${mine} task${mine === 1 ? "" : "s"} in this run, so a different person has to sign it off.`;
  }
  return null;
}

/** The three stages as the step tracker shows them: who acts at each, whether it's done, happening now,
 * still to come or not needed, and one line saying so (why the CFO is needed, when sign-off starts). */
export function stages(kind, step, { cfoRequired, cfoReason, teamName = "Operations team" } = {}) {
  if (kind === "recon_run") {
    return [
      { label: "Tasks decided", who: "Team, and the CFO for important ones", state: "done", detail: "Every task in the run is decided" },
      { label: "Run sign-off", who: "CFO", state: "current", detail: "Signing off now" },
      { label: "Run closed", who: "Decisions final", state: "pending", detail: "After sign-off" },
    ];
  }
  const cfoNeeded = step === "CFO" || cfoRequired;
  const why = cfoReason ? `Required because of ${cfoReason}` : "Required";
  return [
    { label: "Team review", who: teamName, state: step === "TEAM" ? "current" : "done", detail: step === "TEAM" ? "Deciding now" : "Decided" },
    {
      label: "CFO approval",
      who: "CFO",
      state: step === "CFO" ? "current" : cfoNeeded ? "pending" : "skipped",
      detail: step === "CFO" ? `Approving now. ${why}` : cfoNeeded ? why : "Not needed, unless a data fix is proposed",
    },
    { label: "Run sign-off", who: "CFO", state: "pending", detail: "Once every task in the run is decided" },
  ];
}
