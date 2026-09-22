import { useMemo, useState } from "react";
import { api } from "../api";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import PageShell, { Loading, LoadError, Notice } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import { useAuth } from "../auth";
import useAsync from "../hooks/useAsync";
import ApprovalChain from "../workflow/ApprovalChain";
import { CANDIDATE_GROUPS, claimTask, completeTask, getTask, getVariables, searchTasks } from "../workflow/tasklistApi";

const GROUP_ASSUMPTION = [
  "This POC has no Identity/Keycloak login, so Tasklist tasks are only routed to candidate groups, never to individual users.",
  "Every logged-in demo user can see and act on all three groups (fraud-investigation, compliance, operations) rather than being scoped to one.",
];

function fmtDateTime(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

function KeyValueTable({ row }) {
  if (!row) return <p className="text-sm text-ink2">No underlying source row found (it may have been removed since the flag was raised).</p>;
  return (
    <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
      {Object.entries(row).map(([k, v]) => (
        <div key={k}>
          <dt className="text-ink2">{k}</dt>
          <dd className="font-medium text-ink">{v === null ? "—" : String(v)}</dd>
        </div>
      ))}
    </dl>
  );
}

/** Full record detail + comment thread + Approve/Reject/Corrected actions for one selected task. */
function ReviewPanel({ task, user, onDone }) {
  const { status, data, error, reload } = useAsync(async () => {
    const variables = await getVariables(task.id);
    const [detail, comments] = await Promise.all([
      api.exceptionDetail({
        record_type: variables.recordType,
        source_table: variables.sourceTable,
        record_key: variables.recordKey,
        flag_label: variables.flagLabel,
      }),
      api.exceptionComments({ source_table: variables.sourceTable, record_key: variables.recordKey, flag_label: variables.flagLabel }),
    ]);
    return { variables, detail, comments };
  }, [task.id]);

  const [commentText, setCommentText] = useState("");
  const [outcome, setOutcome] = useState("");
  const [correctedValue, setCorrectedValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the record" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;

  const { variables, detail, comments } = data;

  async function submitComment(e) {
    e.preventDefault();
    if (!commentText.trim()) return;
    setBusy(true);
    try {
      await api.addExceptionComment({
        source_table: variables.sourceTable, record_key: variables.recordKey, flag_label: variables.flagLabel,
        comment_text: commentText,
      });
      setCommentText("");
      reload();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function submitOutcome() {
    setFormError("");
    if (!outcome) return setFormError("Pick an outcome: Approved, Rejected or Corrected.");
    if (!commentText.trim()) return setFormError("A comment is required before taking this action.");
    if (outcome === "CORRECTED" && !correctedValue.trim()) return setFormError("Enter the corrected value (JSON).");
    setBusy(true);
    try {
      // Mandatory comment first (specs/screen-06-report-workflow.md section 2.3), then complete
      // the Tasklist task (the actual workflow action - CLAUDE.md's Workflow Engine Decision),
      // then mirror the completion into audit_log. If the Tasklist call fails, the comment still
      // stands (a reasonable reviewer note) but the task stays open - surfaced via formError.
      await api.addExceptionComment({
        source_table: variables.sourceTable, record_key: variables.recordKey, flag_label: variables.flagLabel,
        comment_text: commentText,
      });
      await completeTask(task.id, {
        outcome, correctedValue: outcome === "CORRECTED" ? correctedValue : "", reviewedByUserId: user.user_id,
      });
      await api.logTaskCompletion({
        source_table: variables.sourceTable, record_key: variables.recordKey, flag_label: variables.flagLabel,
        outcome, camunda_task_id: task.id,
      });
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <Section
      id="review"
      title={`Reviewing ${variables.flagLabel} on ${variables.sourceTable} (${variables.recordKey})`}
      description={variables.description}
      action={<button type="button" onClick={onDone} className="rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 hover:border-accent/40 hover:bg-page hover:text-ink">Back to my tasks</button>}
    >
      <div className="card mb-4 rounded-xl border border-hair bg-surface p-4">
        <ApprovalChain candidateGroup={task.candidateGroups?.[0]} taskState={task.taskState} />
      </div>

      <h3 className="mb-2 text-sm font-medium text-ink2">Source record</h3>
      <div className="card mb-5 rounded-xl border border-hair bg-surface p-4">
        <KeyValueTable row={detail.source_row} />
      </div>

      <h3 className="mb-2 text-sm font-medium text-ink2">Comments</h3>
      <ul className="mb-3 space-y-2">
        {comments.length === 0 && <p className="text-sm text-ink2">No comments yet.</p>}
        {comments.map((c) => (
          <li key={c.comment_id} className="card rounded-lg border border-hair bg-surface p-3 text-sm">
            <div className="mb-1 flex items-center justify-between text-xs text-ink2">
              <span className="font-medium text-ink">{c.author}</span>
              <span>{fmtDateTime(c.created_at)}</span>
            </div>
            {c.comment_text}
          </li>
        ))}
      </ul>

      <form onSubmit={submitComment} className="mb-5 flex gap-2">
        <input
          type="text"
          value={commentText}
          onChange={(e) => setCommentText(e.target.value)}
          placeholder="Add a comment (required before Approve/Reject/Corrected)"
          className="flex-1 rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
        />
        <button type="submit" disabled={busy} className="rounded-md border border-hair px-3 py-1.5 text-sm text-ink hover:border-accent/40 hover:bg-page disabled:opacity-60">
          Post
        </button>
      </form>

      <h3 className="mb-2 text-sm font-medium text-ink2">Action</h3>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {["APPROVED", "REJECTED", "CORRECTED"].map((o) => (
            <button
              key={o}
              type="button"
              onClick={() => setOutcome(o)}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                outcome === o ? "border-accent bg-accent text-white" : "border-hair text-ink hover:border-accent/40 hover:bg-page"
              }`}
            >
              {o[0] + o.slice(1).toLowerCase()}
            </button>
          ))}
        </div>
        {outcome === "CORRECTED" && (
          <input
            type="text"
            value={correctedValue}
            onChange={(e) => setCorrectedValue(e.target.value)}
            placeholder='Corrected value, JSON e.g. {"risk_rating": "B"}'
            className="mb-3 w-full rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
          />
        )}
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <button
          type="button"
          onClick={submitOutcome}
          disabled={busy}
          className="rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60"
        >
          {busy ? "Submitting…" : "Submit decision"}
        </button>
      </div>
    </Section>
  );
}

function TasksSection({ onSelect, selectedTaskId }) {
  const { status, data, error, reload } = useAsync(() => searchTasks({ state: "CREATED" }), []);
  if (status === "loading") return <Loading what="your tasks" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  return (
    <DataTable
      caption="My tasks"
      columns={[
        { key: "name", header: "Task" },
        { key: "group", header: "Group", render: (t) => (t.candidateGroups || []).join(", ") },
        { key: "creationDate", header: "Created", render: (t) => fmtDateTime(t.creationDate) },
        { key: "processInstanceKey", header: "Process instance" },
      ]}
      rows={data}
      rowKey={(t) => t.id}
      selectedKey={selectedTaskId}
      onRowClick={(t) => onSelect(t)}
      emptyText="Nothing waiting for review. New exceptions appear here once the bridge worker (camunda/bridge/poll_worker.py) starts a process instance for them."
    />
  );
}

function BreachAlerts() {
  const { status, data, error, reload } = useAsync(() => api.breaches({ status: "OPEN" }), []);
  if (status === "loading") return <Loading what="breach alerts" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  return (
    <DataTable
      caption="Open breaches"
      columns={[
        { key: "metric_name", header: "Metric" },
        { key: "actual_value", header: "Actual", align: "right" },
        { key: "threshold_value", header: "Threshold", align: "right" },
        { key: "detected_at", header: "Detected", render: (b) => fmtDateTime(b.detected_at) },
        { key: "assigned_to_name", header: "Assigned to", render: (b) => b.assigned_to_name || "Unassigned" },
      ]}
      rows={data}
      rowKey={(b) => b.breach_id}
      rowFlag={() => ({ kind: "watch", label: "Open" })}
      emptyText="No open breaches."
    />
  );
}

function AuditTrail() {
  const [objectId, setObjectId] = useState("");
  const { status, data, error, reload } = useAsync(() => api.auditLog({ object_id: objectId || undefined, limit: 100 }), [objectId]);
  return (
    <>
      <div className="mb-3">
        <input
          type="text"
          value={objectId}
          onChange={(e) => setObjectId(e.target.value)}
          placeholder="Filter by object id (source_table:record_key:flag_label)"
          className="w-full max-w-md rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink sm:w-auto"
        />
      </div>
      {status === "loading" ? (
        <Loading what="the audit trail" />
      ) : status === "error" && !data ? (
        <LoadError error={error} onRetry={reload} />
      ) : (
        <DataTable
          caption="Audit trail"
          columns={[
            { key: "timestamp", header: "When", render: (a) => fmtDateTime(a.timestamp) },
            { key: "user_name", header: "Who", render: (a) => a.user_name || "—" },
            { key: "action", header: "Action" },
            { key: "object_id", header: "Record" },
            { key: "new_value", header: "New value" },
          ]}
          rows={data}
          rowKey={(a) => a.log_id}
          emptyText="No audit events yet."
        />
      )}
    </>
  );
}

function ManagementStats() {
  const { status, data } = useAsync(() => api.workflowStats(), []);
  if (status !== "ready") return null;
  const { submissions, open_breaches_by_age, avg_turnaround_seconds } = data;
  const total = (submissions.on_time || 0) + (submissions.late || 0);
  const onTimePct = total ? Math.round((submissions.on_time / total) * 100) : null;
  const turnaround = avg_turnaround_seconds != null ? `${(avg_turnaround_seconds / 3600).toFixed(1)}h` : "—";
  return (
    <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Workflow management summary">
      <StatBox label="On-time submissions" value={onTimePct != null ? `${onTimePct}%` : "—"} hint={`${submissions.on_time || 0} on time, ${submissions.late || 0} late`} />
      <StatBox label="Overdue, not submitted" value={submissions.overdue_open || 0} status={submissions.overdue_open > 0 ? "action" : "good"} />
      <StatBox label="Avg. turnaround" value={turnaround} hint="First comment or event to decision" />
      <StatBox
        label="Open breaches"
        value={Object.values(open_breaches_by_age).reduce((a, b) => a + b, 0)}
        hint={Object.entries(open_breaches_by_age).map(([k, v]) => `${v} ${k}`).join(", ") || "None open"}
      />
    </ul>
  );
}

export default function Workflow() {
  const { user } = useAuth();
  const [selectedTask, setSelectedTask] = useState(null);

  async function selectTask(task) {
    try {
      await claimTask(task.id, String(user.user_id));
    } catch {
      /* claiming is best-effort for the POC - a task already claimed by someone else still opens for review */
    }
    setSelectedTask(task);
  }

  return (
    <PageShell
      title="Report workflow"
      subtitle="Task queue, review and approval for flagged exceptions - routed and tracked by Camunda 8, not this application."
      actions={<AssumptionBadge items={GROUP_ASSUMPTION} label="Candidate-group assumption" heading="No per-user task routing in this POC" />}
    >
      <Section id="tasks" title="My tasks" description="Open tasks across all three candidate groups (see the assumption badge above).">
        <TasksSection onSelect={selectTask} selectedTaskId={selectedTask?.id} />
      </Section>

      {selectedTask && <ReviewPanel task={selectedTask} user={user} onDone={() => setSelectedTask(null)} />}

      <Section id="breaches" title="Breach alerts" description="Open limit breaches from limits/breaches (specs/screen-06-report-workflow.md section 2.4). Auto-creating a Camunda task per new breach is not yet built - this lists what's already in Postgres.">
        <BreachAlerts />
      </Section>

      <Section id="audit" title="Audit trail" description="Insert-only log of every comment and task completion (audit_log).">
        <AuditTrail />
      </Section>

      <Section id="stats" title="Management view" description="On-time vs late submissions, turnaround, open breaches by age.">
        <ManagementStats />
      </Section>
    </PageShell>
  );
}
