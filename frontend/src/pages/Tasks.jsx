import { useMemo, useState } from "react";
import { api } from "../api";
import AssumptionBadge from "../components/AssumptionBadge";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import PageShell, { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import { useAuth } from "../auth";
import useAsync from "../hooks/useAsync";
import { KPI_BY_KEY } from "../kpi/kpiConfig";
import { formatDateTime, formatValue } from "../kpi/format";
import ApprovalChain from "../workflow/ApprovalChain";
import { TRANSACTION_FLAGS, alertType } from "../workflow/flagTypes";
import ReconciliationTaskPanel from "../reconciliation/ReconciliationTaskPanel";
import CaseReviewPanel from "../workflow/CaseReviewPanel";
import EntityMatchPanel from "../workflow/EntityMatchPanel";
import GroupReviewPanel from "../reconciliation/GroupReviewPanel";
import { Digest, TaskPolicy } from "../workflow/DigestAndPolicy";
import { byUrgency, daysLeftText, isOverdue, taskDue } from "../workflow/taskDue";
import { claimTask, completeTask, getVariables, searchTasks } from "../workflow/tasklistApi";

// Provenance columns stamped by Notebook 1 (specs/source-tagging.md): shown with the source record,
// but not offered as fields to correct - they say where the data came from, not what it says.
const SOURCE_TAG_FIELDS = new Set(["source_system", "source_country", "ingest_batch_id", "source_file"]);

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
function ReviewPanel({ task, user, onDone, onClose }) {
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
  const flagInfo = variables.recordType === "fraud" ? TRANSACTION_FLAGS[variables.flagLabel] : undefined;

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
      {flagInfo && (
        <p className="mt-2 text-sm text-ink">
          <span className="mr-2 rounded-full border border-hair px-2 py-0.5 text-xs font-medium">{flagInfo.type}</span>
          {flagInfo.reason}
        </p>
      )}

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
              {Object.keys(detail.source_row || {}).filter((f) => !SOURCE_TAG_FIELDS.has(f)).map((f) => <option key={f} value={f}>{f}</option>)}
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
            onClick={onClose}
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

const RECORD_TYPE_LABEL = {
  fraud_case: "Transaction case", data_quality: "Data quality", fraud: "Transaction alert", breach: "Breach", reconciliation: "Reconciliation",
  entity_match: "Possible duplicate", recon_group: "Core-system break",
};
const SEVERITY_LABEL = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

const SOURCE_TABLE_LABEL = {
  customers: "Customer", accounts: "Account", loans: "Loan", branches: "Branch",
  capital_positions: "Capital position", liquidity_daily: "Liquidity", fx_rates: "FX rate",
};

// limits.metric_name -> KPI tile, the same mapping as camunda/bridge/breach_check.py's KPI_COLUMN.
const BREACH_METRIC_KPI = {
  capital_adequacy_ratio: "car_pct", liquidity_coverage_ratio: "lcr_pct", npl_ratio: "npl_ratio_pct",
  dollarization_ratio: "dollarization_ratio_pct", net_interest_margin: "nim_pct",
  cost_to_income_ratio: "cost_to_income_pct", return_on_equity: "roe_pct", total_assets: "total_assets_usd",
};

/** What a task is about, in one cell: the transaction ID, "Loan LN0059" for a data-quality flag on
 * another table, or "Capital ratio 12.4% (limit 12.5%)" for a breach - a bank-wide KPI, which has
 * no transaction or account behind it. */
export function recordLabel(task) {
  const { sourceTable, recordKey } = task.vars;
  if (sourceTable === "transactions") return recordKey;
  // A CFO reconciliation item (specs/cfo-reconciliation-workflow.md) or a case of flags
  // (specs/task-cases.md): the bridge sets a one-line title.
  if (sourceTable === "pipeline_reconciliation") return task.vars.title || `Reconciliation item #${recordKey}`;
  if (sourceTable === "task_cases") return task.vars.title || `Case #${recordKey}`;
  if (sourceTable === "entity_match_candidates") return task.vars.title || `Possible duplicate #${recordKey}`;
  if (sourceTable === "reconciliation_groups") return task.vars.title || `Reconciliation group #${recordKey}`;
  if (sourceTable === "breaches") {
    const b = task.breach;
    const kpi = b && KPI_BY_KEY[BREACH_METRIC_KPI[b.metric_name]];
    if (!kpi) return `Breach #${recordKey}`;
    // The level decides which line was crossed (specs/breach-levels.md).
    if (b.level === "REGULATORY") return `${kpi.short} ${formatValue(kpi, b.actual_value)} (regulatory limit ${formatValue(kpi, b.regulatory_value)})`;
    return `${kpi.short} ${formatValue(kpi, b.actual_value)} (limit ${formatValue(kpi, b.threshold_value)})`;
  }
  return `${SOURCE_TABLE_LABEL[sourceTable] || sourceTable} ${recordKey}`;
}

async function loadTasks() {
  const tasks = await searchTasks({ state: "CREATED" });
  // account_id isn't a Camunda variable (only recordKey=transaction_id is, for fraud tasks) - one
  // batched Postgres lookup for the whole list instead of a call per row. Breach figures likewise
  // come from one /workflow/breaches call; if it fails the Record cell falls back to "Breach #id".
  const txnIds = [...new Set(tasks.filter((t) => t.vars.sourceTable === "transactions").map((t) => t.vars.recordKey))];
  const hasBreaches = tasks.some((t) => t.vars.sourceTable === "breaches");
  // Due days come from the task policy (specs/task-cases.md); without it, only cases show a due date.
  const [accountIds, breaches, policy] = await Promise.all([
    txnIds.length ? api.lookupAccountIds(txnIds) : {},
    hasBreaches ? api.breaches().catch(() => []) : [],
    api.taskPolicy().catch(() => []),
  ]);
  const breachById = Object.fromEntries(breaches.map((b) => [String(b.breach_id), b]));
  const dueDays = policy.find((p) => p.key === "task.due_days")?.value;
  return tasks
    .map((t) => {
      const breach = t.vars.sourceTable === "breaches" ? breachById[t.vars.recordKey] : undefined;
      return { ...t, accountId: accountIds[t.vars.recordKey] || t.vars.accountId, breach, severity: t.vars.severity || null, due: taskDue(t, dueDays, breach) };
    })
    .sort(byUrgency());
}

function TasksTable({ onSelect, selectedTaskId, refreshKey, completedIds }) {
  // refreshKey: bumped by the parent after a task is completed, so the list refetches in the
  // background. completedIds hides a just-completed task at once rather than waiting on that
  // refetch: a Tasklist search can take several seconds, and right after /complete it can still
  // return the task (Tasklist's Elasticsearch index catches up asynchronously).
  const { status, data, error, reload } = useAsync(loadTasks, [refreshKey]);
  const [typeFilter, setTypeFilter] = useState("");
  const [nameFilter, setNameFilter] = useState("");

  const filtered = useMemo(() => {
    if (!data) return [];
    return data.filter((t) => {
      if (completedIds.has(t.id)) return false;
      if (typeFilter && t.vars.recordType !== typeFilter) return false;
      if (nameFilter && !t.name.toLowerCase().includes(nameFilter.toLowerCase())) return false;
      return true;
    });
  }, [data, typeFilter, nameFilter, completedIds]);

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
          { key: "record", header: "Record", render: recordLabel },
          { key: "accountId", header: "Account ID", render: (t) => t.accountId || "—" },
          { key: "name", header: "Name" },
          { key: "group", header: "Group", render: (t) => (t.candidateGroups || []).join(", ") },
          { key: "type", header: "Type", render: (t) => alertType(t.vars) },
          { key: "severity", header: "Severity", render: (t) => SEVERITY_LABEL[t.severity] || "—" },
          { key: "due", header: "Due", render: (t) => (t.due ? `${t.due} · ${daysLeftText(t.due)}` : "—") },
        ]}
        rows={filtered}
        rowKey={(t) => t.id}
        rowFlag={(t) => (isOverdue(t.due) ? { kind: "loss", label: "Overdue" } : null)}
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
  const [completedIds, setCompletedIds] = useState(() => new Set());

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
      subtitle="Review and act on everything the bank's checks have flagged — transaction alerts, data-quality issues, and risk-limit breaches all land here."
      actions={<AssumptionBadge items={GROUP_ASSUMPTION} label="How access works today" heading="Demo limitation: team-level access only" />}
    >
      <Section id="tasks" title="My tasks" description="Everything currently waiting for review, across every team.">
        <TasksTable onSelect={selectTask} selectedTaskId={selectedTask?.id} refreshKey={refreshKey} completedIds={completedIds} />
        <TaskPolicy />
      </Section>

      <Digest />

      {selectedTask && (
        <Modal title="Review task" onClose={() => setSelectedTask(null)}>
          {(() => {
            const onDone = () => {
              const doneId = selectedTask.id;
              setCompletedIds((ids) => new Set(ids).add(doneId));
              setSelectedTask(null);
              setRefreshKey((k) => k + 1);
            };
            const Panel = { reconciliation: ReconciliationTaskPanel, fraud_case: CaseReviewPanel, entity_match: EntityMatchPanel, recon_group: GroupReviewPanel }[selectedTask.vars.recordType] || ReviewPanel;
            return <Panel task={selectedTask} user={user} onClose={() => setSelectedTask(null)} onDone={onDone} />;
          })()}
        </Modal>
      )}
    </PageShell>
  );
}
