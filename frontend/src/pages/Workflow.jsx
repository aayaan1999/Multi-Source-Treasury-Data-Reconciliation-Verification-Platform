import { useMemo, useState } from "react";
import { api } from "../api";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import PageShell, { Loading, LoadError, Notice } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import { useAuth } from "../auth";
import useAsync from "../hooks/useAsync";
import ApprovalChain from "../workflow/ApprovalChain";
import { CANDIDATE_GROUPS, claimTask, completeTask, getVariables, searchTasks } from "../workflow/tasklistApi";

const GROUP_ASSUMPTION = [
  "This is a demo limitation: tasks are routed to a team (Fraud, Compliance, or Operations), not to a specific person's login yet.",
  "Right now, every signed-in user can see and act on tasks for all three teams, rather than only their own.",
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
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">
        {variables.flagLabel} on {variables.sourceTable} ({variables.recordKey})
      </h3>
      {variables.description && <p className="mt-0.5 text-sm text-ink2">{variables.description}</p>}

      <div className="card mb-4 mt-4 rounded-xl border border-hair bg-surface p-4">
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
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={onDone}
            disabled={busy}
            className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:opacity-60"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={submitOutcome}
            disabled={busy}
            className="rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60"
          >
            {busy ? "Submitting…" : "Submit decision"}
          </button>
        </div>
      </div>
    </>
  );
}

const RECORD_TYPE_LABEL = { data_quality: "Data quality", fraud: "Fraud", breach: "Breach" };

async function loadTasks() {
  const tasks = await searchTasks({ state: "CREATED" });
  // account_id isn't a Camunda variable (only recordKey=transaction_id is, for fraud tasks) - one
  // batched Postgres lookup for the whole list instead of a call per row.
  const txnIds = [...new Set(tasks.filter((t) => t.vars.sourceTable === "transactions").map((t) => t.vars.recordKey))];
  const accountIds = txnIds.length ? await api.lookupAccountIds(txnIds) : {};
  return tasks.map((t) => ({ ...t, accountId: accountIds[t.vars.recordKey] }));
}

function TasksSection({ onSelect, selectedTaskId }) {
  const { status, data, error, reload } = useAsync(loadTasks, []);
  const [typeFilter, setTypeFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.filter((t) => {
      if (typeFilter && t.vars.recordType !== typeFilter) return false;
      if (nameFilter && !t.name.toLowerCase().includes(nameFilter.toLowerCase())) return false;
      return true;
    });
  }, [data, typeFilter, nameFilter]);

  if (status === "loading") return <Loading what="your tasks" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  return (
    <>
      <div className="mb-3 flex flex-wrap items-center gap-3">
        <input
          type="text"
          value={nameFilter}
          onChange={(e) => setNameFilter(e.target.value)}
          placeholder="Filter by name"
          className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink"
        />
        <select
          value={typeFilter}
          onChange={(e) => setTypeFilter(e.target.value)}
          className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40"
        >
          <option value="">All types</option>
          {Object.entries(RECORD_TYPE_LABEL).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select>
      </div>
      <DataTable
        caption="My tasks"
        columns={[
          { key: "transactionId", header: "Transaction ID", render: (t) => (t.vars.sourceTable === "transactions" ? t.vars.recordKey : "—") },
          { key: "accountId", header: "Account ID", render: (t) => t.accountId || "—" },
          { key: "name", header: "Name" },
          { key: "group", header: "Group", render: (t) => (t.candidateGroups || []).join(", ") },
          { key: "completionDate", header: "Modified At", title: "Tasklist only records a change once the task is completed - open tasks show —", render: (t) => fmtDateTime(t.completionDate) },
          { key: "type", header: "Type", render: (t) => RECORD_TYPE_LABEL[t.vars.recordType] || t.vars.recordType },
        ]}
        rows={filtered}
        rowKey={(t) => t.id}
        selectedKey={selectedTaskId}
        onRowClick={(t) => onSelect(t)}
        emptyText="Nothing waiting for review right now. New items appear here automatically as they're flagged."
      />
    </>
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
      subtitle="Review and act on everything the bank's checks have flagged — fraud alerts, data-quality issues, and risk-limit breaches all land here."
      actions={<AssumptionBadge items={GROUP_ASSUMPTION} label="How access works today" heading="Demo limitation: team-level access only" />}
    >
      <Section id="tasks" title="My tasks" description="Everything currently waiting for review, across every team.">
        <TasksSection onSelect={selectTask} selectedTaskId={selectedTask?.id} />
      </Section>

      {selectedTask && (
        <Modal title="Review task" onClose={() => setSelectedTask(null)}>
          <ReviewPanel task={selectedTask} user={user} onDone={() => setSelectedTask(null)} />
        </Modal>
      )}

      <Section id="breaches" title="Breach alerts" description="Regulatory and risk limits that have been crossed. Each new breach is detected automatically and becomes a task above; this section is the full history.">
        <BreachAlerts />
      </Section>

      <Section id="audit" title="Audit trail" description="A permanent record of every comment and decision made on this screen. Nothing here can be edited or deleted.">
        <AuditTrail />
      </Section>

      <Section id="stats" title="Management view" description="How review is going: on-time vs late, how long reviews take, and how old the open breaches are.">
        <ManagementStats />
      </Section>
    </PageShell>
  );
}
