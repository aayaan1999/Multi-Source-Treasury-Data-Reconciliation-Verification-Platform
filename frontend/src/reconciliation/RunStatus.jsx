import { Link } from "react-router-dom";
import { api } from "../api";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";

/** Where a run's sign-off stands, in words. */
export function signoffText(run) {
  if (run.status === "SIGNED_OFF") {
    const carried = run.carried_tasks ? `: ${run.signed_tasks} task${run.signed_tasks === 1 ? "" : "s"} signed off, ${run.carried_tasks} carried to the next day` : "";
    return `Signed off by ${run.signed_by_name} on ${formatDateTime(run.signed_at)}${carried}${run.sign_note ? ` ("${run.sign_note}")` : ""}.`;
  }
  const left = run.tasks - run.decided;
  if (run.status === "IN_SIGNOFF") {
    return left ? `Past the 08:00 cut-off: waiting for the CFO to sign off the decided tasks; the ${left} still open will be carried over.`
      : "Every task is decided: waiting for the CFO's sign-off in Tasks.";
  }
  return `Sign-off starts once every task is decided, or at 08:00 the next morning with the open ones carried over (${left} to go${run.awaiting_cfo ? `, ${run.awaiting_cfo} of them waiting for CFO approval` : ""}).`;
}

/**
 * Each shown source's current run and its sign-off (specs/reconciliation-approvals.md). Read-only: tasks
 * are decided and the run signed off in Tasks, where Camunda runs the steps.
 */
export default function RunStatus({ sources }) {
  const { status, data, error, reload } = useAsync(() => api.reconRuns(), []);
  if (status === "loading") return <Loading what="the runs" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const runs = data.filter((r) => !sources || sources.includes(r.source_system));
  if (!runs.length) return null;
  return (
    <div className="mt-4 grid gap-3">
      {runs.map((run) => (
        <div key={run.run_id} className="card rounded-xl border border-hair bg-surface p-4 text-sm" aria-label={`Run: ${run.name}`}>
          <h3 className="font-semibold tracking-tight text-ink">{run.name[0].toUpperCase() + run.name.slice(1)}</h3>
          <p className="mt-1 text-ink">
            {run.tasks ? `${run.decided} of ${run.tasks} task${run.tasks === 1 ? "" : "s"} decided.` : "Nothing to review in this run."}{" "}
            {signoffText(run)}
          </p>
          {run.carried_in > 0 && (
            <p className="mt-1 font-medium" style={{ color: run.escalated ? "var(--critical)" : "var(--warning)" }}>
              {run.carried_in} task{run.carried_in === 1 ? "" : "s"} carried over from an earlier sign-off, now a high priority
              {run.escalated ? `; ${run.escalated} escalated after being carried 3 times` : ""}.
            </p>
          )}
          {run.sent_back > 0 && (
            <p className="mt-1 font-medium" style={{ color: "var(--critical)" }}>
              {run.sent_back} task{run.sent_back === 1 ? "" : "s"} sent back by the CFO, waiting for the team.
            </p>
          )}
          {run.status !== "SIGNED_OFF" && (
            <p className="mt-1 text-ink2">
              The team decides each task, the CFO approves the important ones, then the CFO signs off the whole run: all in{" "}
              <Link to="/tasks" className="text-accent underline">Tasks</Link>.
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
