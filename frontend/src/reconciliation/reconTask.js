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
  if (!CFO_ROLES.includes(user?.role)) return "Only the CFO (the approver login) or an admin can do this step.";
  if (step === "CFO" && decidedBy === user.user_id) return "You made this decision, so a different person has to approve it.";
  if (step === "SIGNOFF") {
    const mine = deciders.filter((id) => id === user.user_id).length;
    if (mine) return `You decided ${mine} task${mine === 1 ? "" : "s"} in this run, so a different person has to sign it off.`;
  }
  return null;
}

/** The three stages as the progress line shows them, with who acts and where this task is. */
export function stages(kind, step, { cfoRequired, cfoReason, teamName = "Operations" } = {}) {
  if (kind === "recon_run") {
    return [
      { label: "Every task decided", who: "Team and CFO", state: "done" },
      { label: "Run sign-off", who: "CFO", state: "current" },
      { label: "Run closed", who: "", state: "pending" },
    ];
  }
  const cfoNeeded = step === "CFO" || cfoRequired;
  return [
    { label: "Team review", who: teamName, state: step === "TEAM" ? "current" : "done" },
    {
      label: "CFO approval",
      who: cfoNeeded ? "CFO" : "Not needed unless a fix is proposed",
      note: step === "CFO" ? cfoReason : cfoRequired ? cfoReason : null,
      state: step === "CFO" ? "current" : cfoNeeded ? "pending" : "skipped",
    },
    { label: "Run sign-off", who: "CFO", state: "pending" },
  ];
}
