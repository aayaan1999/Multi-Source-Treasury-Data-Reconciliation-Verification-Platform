import { useMemo, useState } from "react";
import { api } from "../api";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import PageShell, { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import { useAuth } from "../auth";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import ApprovalChain from "../workflow/ApprovalChain";
import { claimTask, completeTask, getVariables, searchTasks } from "../workflow/tasklistApi";

const GROUP_ASSUMPTION = [
  "This is a demo limitation: tasks are routed to a team (Fraud, Compliance, or Operations), not to a specific person's login yet.",
  "Right now, every signed-in user can see and act on tasks for all three teams, rather than only their own.",
];

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
  const [correctedField, setCorrectedField] = useState("");
  const [correctedFieldValue, setCorrectedFieldValue] = useState("");
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
    if (outcome === "CORRECTED" && (!correctedField || !correctedFieldValue.trim())) {
      return setFormError("Pick the field to correct and enter its new value.");
    }
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
      // Built here, not typed by the reviewer: review_outcomes.corrected_value is jsonb, read
      // back by Databricks to patch the real {table}_clean row (specs/bidirectional-sync.md).
      // Field comes from a dropdown of the record's own columns, not free text, so it can't name
      // a field that doesn't exist on the row.
      const correctedValue = outcome === "CORRECTED" ? JSON.stringify({ [correctedField]: correctedFieldValue }) : "";
      await completeTask(task.id, { outcome, correctedValue, reviewedByUserId: user.user_id });
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
              <span>{formatDateTime(c.created_at)}</span>
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
          <div className="mb-3 flex flex-wrap gap-2">
            <select
              value={correctedField}
              onChange={(e) => setCorrectedField(e.target.value)}
              className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40"
            >
              <option value="">Field to correct…</option>
              {Object.keys(detail.source_row || {}).map((f) => <option key={f} value={f}>{f}</option>)}
            </select>
            <input
              type="text"
              value={correctedFieldValue}
              onChange={(e) => setCorrectedFieldValue(e.target.value)}
              placeholder="New value"
              className="min-w-[10rem] flex-1 rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
            />
          </div>
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

function TasksTable({ onSelect, selectedTaskId, refreshKey }) {
  // refreshKey: bumped by the parent after a task is completed, so the list drops the
  // just-completed task instead of waiting for a full page reload.
  const { status, data, error, reload } = useAsync(loadTasks, [refreshKey]);
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
          { key: "completionDate", header: "Modified At", title: "Tasklist only records a change once the task is completed - open tasks show —", render: (t) => formatDateTime(t.completionDate) },
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

export default function Tasks() {
  const { user } = useAuth();
  const [selectedTask, setSelectedTask] = useState(null);
  const [refreshKey, setRefreshKey] = useState(0);

  async function selectTask(task) {
    try {
      await claimTask(task.id);
    } catch {
      /* claiming is best-effort for the POC - a task already claimed by someone else still opens for review */
    }
    setSelectedTask(task);
  }

  return (
    <PageShell
      title="Tasks"
      eyebrow="Review queue"
      subtitle="Review and act on everything the bank's checks have flagged — fraud alerts, data-quality issues, and risk-limit breaches all land here."
      actions={<AssumptionBadge items={GROUP_ASSUMPTION} label="How access works today" heading="Demo limitation: team-level access only" />}
    >
      <Section id="tasks" title="My tasks" description="Everything currently waiting for review, across every team.">
        <TasksTable onSelect={selectTask} selectedTaskId={selectedTask?.id} refreshKey={refreshKey} />
      </Section>

      {selectedTask && (
        <Modal title="Review task" onClose={() => setSelectedTask(null)}>
          <ReviewPanel
            task={selectedTask}
            user={user}
            onDone={() => {
              setSelectedTask(null);
              setRefreshKey((k) => k + 1);
            }}
          />
        </Modal>
      )}
    </PageShell>
  );
}
