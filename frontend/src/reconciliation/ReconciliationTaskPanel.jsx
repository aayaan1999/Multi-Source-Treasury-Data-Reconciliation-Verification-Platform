import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import { completeTask } from "../workflow/tasklistApi";
import { correctableFields, currencyLines, fmtAmount, statusText, taskStep } from "./pipeline";

const STEP_LABELS = [
  ["CFO_REVIEW", "CFO review"],
  ["ASSIGNEE_UPDATE", "Update values"],
  ["CFO_FINAL_REVIEW", "CFO final review"],
  ["APPROVED", "Approved"],
];

const BUTTON = "rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60";
const PRIMARY = "rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60";
const INPUT = "rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink";

function StepChain({ step }) {
  const current = STEP_LABELS.findIndex(([key]) => key === step);
  return (
    <ol className="flex flex-wrap items-center gap-1" aria-label="Reconciliation steps">
      {STEP_LABELS.map(([key, label], i) => (
        <li key={key} className="flex items-center gap-1">
          {i > 0 && <span aria-hidden className="mx-1 h-px w-6 bg-hair" />}
          <span
            aria-current={i === current ? "step" : undefined}
            className={`rounded-full border border-hair px-2.5 py-1 text-xs font-medium ${i === current ? "text-white" : "text-ink2"}`}
            style={i === current ? { background: "var(--series-1)" } : i < current ? { color: "var(--good)" } : undefined}
          >
            {label}
          </span>
        </li>
      ))}
    </ol>
  );
}

/** Propose a value for one field of one rejected record (CFO handling it directly, or the assignee). */
function CorrectionForm({ reconId, sourceTable, records, onSaved }) {
  const byKey = Object.fromEntries(records.filter((r) => r.record_data).map((r) => [r.record_key, r.record_data]));
  const [recordKey, setRecordKey] = useState("");
  const [field, setField] = useState("");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const fields = correctableFields(byKey[recordKey], sourceTable);
  const current = recordKey && field ? byKey[recordKey][field] : undefined;

  async function save(e) {
    e.preventDefault();
    setError("");
    if (!recordKey || !field || !value.trim()) return setError("Pick the record and field, and enter the corrected value.");
    setBusy(true);
    try {
      await api.proposeCorrection(reconId, { record_key: recordKey, field_name: field, new_value: value });
      setValue("");
      onSaved();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  if (!Object.keys(byKey).length) return null;
  return (
    <form onSubmit={save} className="card mt-3 rounded-xl border border-hair bg-surface p-4" aria-label="Propose a correction">
      <div className="flex flex-wrap items-center gap-2">
        <select value={recordKey} onChange={(e) => { setRecordKey(e.target.value); setField(""); }} aria-label="Record" className={INPUT}>
          <option value="">Record…</option>
          {Object.keys(byKey).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Field" className={INPUT} disabled={!recordKey}>
          <option value="">Field…</option>
          {fields.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Corrected value" aria-label="Corrected value" className={`${INPUT} min-w-[9rem] flex-1`} />
        <button type="submit" disabled={busy} className={BUTTON}>{busy ? "Saving…" : "Save correction"}</button>
      </div>
      {field && <p className="mt-2 text-sm text-ink2">Current value: {current === null || current === undefined ? "(empty)" : String(current)}</p>}
      {error && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
    </form>
  );
}

/**
 * Review popup for a reconciliation-review task (specs/cfo-reconciliation-workflow.md): the item, the
 * rejected records behind it, the proposed corrections, comments, and the actions of the current
 * step. Each action saves to our database, completes the Tasklist task (Camunda moves the process
 * on), then records the step (status + audit). Approval itself is written by the outcome worker.
 */
export default function ReconciliationTaskPanel({ task, user, onDone, onClose }) {
  const reconId = Number(task.vars.recordKey);
  const step = taskStep(task);
  const commentKey = { source_table: "pipeline_reconciliation", record_key: String(reconId), flag_label: "RECONCILIATION" };
  const { status, data, error, reload } = useAsync(async () => {
    const [detail, corrections, comments, people] = await Promise.all([
      api.pipelineRecords(reconId), api.pipelineCorrections(reconId), api.exceptionComments(commentKey), api.assignees(),
    ]);
    return { detail, corrections, comments, people };
  }, [task.id]);

  const [comment, setComment] = useState("");
  const [postedComment, setPostedComment] = useState("");
  const [assignee, setAssignee] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the reconciliation item" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;

  const { detail, corrections, comments, people } = data;
  const { item, records } = detail;
  const canCorrect = step === "CFO_REVIEW" || step === "ASSIGNEE_UPDATE";

  async function act(kind) {
    setFormError("");
    const text = comment.trim();
    if (kind === "REASSIGN" && !assignee) return setFormError("Pick who to reassign it to.");
    if (kind !== "REASSIGN" && !text) return setFormError("A comment is required before taking this action.");
    setBusy(true);
    try {
      // Posted once: a retry after a failed step doesn't add the same comment again.
      if (text && text !== postedComment) {
        await api.addExceptionComment({ ...commentKey, comment_text: text });
        setPostedComment(text);
      }
      // Camunda first: if Tasklist refuses, nothing is recorded as done.
      if (kind === "APPROVE") {
        await completeTask(task.id, step === "CFO_REVIEW"
          ? { cfoDecision: "APPROVE", approvedByUserId: user.user_id }
          : { finalDecision: "APPROVE", approvedByUserId: user.user_id });
      } else if (kind === "REASSIGN") {
        await completeTask(task.id, { cfoDecision: "REASSIGN", assigneeUserId: Number(assignee) });
        await api.pipelineEvent(reconId, { event: "REASSIGNED", assignee_user_id: Number(assignee), comment: text || undefined });
      } else if (kind === "SUBMIT") {
        await completeTask(task.id, {});
        await api.pipelineEvent(reconId, { event: "SUBMITTED", comment: text });
      } else if (kind === "RETURN") {
        await completeTask(task.id, { finalDecision: "RETURN" });
        await api.pipelineEvent(reconId, { event: "RETURNED", comment: text });
      }
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const lines = currencyLines(item.amounts_by_currency).filter((l) => Math.abs(l.gap) > 0.005);

  return (
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">
        {item.source_system} · {item.source_country} · {item.source_table}
      </h3>
      <p className="mt-0.5 text-sm text-ink2">
        {item.received_rows} rows received, {item.clean_rows} kept, {item.rejected_rows} rejected
        {lines.length > 0 && ` · gap ${lines.map((l) => `${l.currency} ${fmtAmount(l.gap)}`).join(", ")}`}
        {" · "}{statusText(item)}
      </p>

      <div className="card mb-4 mt-4 rounded-xl border border-hair bg-surface p-4">
        <StepChain step={step} />
        {step === "ASSIGNEE_UPDATE" && item.assigned_to && item.assigned_to !== user.user_id && (
          <p className="mt-2 text-sm text-ink2">
            Assigned to {item.assigned_to_name}. In the demo every login can see every task.
          </p>
        )}
      </div>

      <h3 className="mb-2 text-sm font-medium text-ink2">Rejected records</h3>
      {detail.records_available ? (
        <DataTable
          caption="Rejected records"
          columns={[
            { key: "record_key", header: "Record" },
            { key: "flag_label", header: "Check" },
            { key: "description", header: "Why it was rejected" },
          ]}
          rows={records}
          rowKey={(r) => `${r.record_key}:${r.flag_label}`}
          emptyText="No rejected records."
        />
      ) : (
        <p className="card rounded-xl border border-hair bg-surface p-4 text-sm text-ink2">
          This item is from an older run; record-level detail is kept for the latest run only.
        </p>
      )}
      {canCorrect && <CorrectionForm reconId={reconId} sourceTable={item.source_table} records={records} onSaved={reload} />}

      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Corrections</h3>
      <DataTable
        caption="Corrections"
        columns={[
          { key: "record_key", header: "Record" },
          { key: "field_name", header: "Field" },
          { key: "old_value", header: "Was", render: (c) => c.old_value ?? "(empty)" },
          { key: "new_value", header: "Corrected to" },
          { key: "entered_by_name", header: "By" },
          { key: "status", header: "Status" },
        ]}
        rows={corrections}
        rowKey={(c) => c.correction_id}
        emptyText={canCorrect ? "No corrections yet. Propose one above." : "No corrections were proposed."}
      />

      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Comments</h3>
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

      <h3 className="mb-2 text-sm font-medium text-ink2">Action</h3>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={step === "CFO_REVIEW" ? "Comment (required to approve; optional instructions when reassigning)" : "Comment (required)"}
          aria-label="Comment"
          className={`${INPUT} mb-3 w-full px-3`}
        />
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={BUTTON}>Cancel</button>
          {step === "CFO_REVIEW" && (
            <>
              <select value={assignee} onChange={(e) => setAssignee(e.target.value)} aria-label="Reassign to" className={INPUT}>
                <option value="">Reassign to…</option>
                {people.map((p) => <option key={p.user_id} value={p.user_id}>{p.name} ({p.role})</option>)}
              </select>
              <button type="button" onClick={() => act("REASSIGN")} disabled={busy} className={BUTTON}>Reassign</button>
              <button type="button" onClick={() => act("APPROVE")} disabled={busy} className={PRIMARY}>Approve</button>
            </>
          )}
          {step === "ASSIGNEE_UPDATE" && (
            <button type="button" onClick={() => act("SUBMIT")} disabled={busy} className={PRIMARY}>Submit to CFO</button>
          )}
          {step === "CFO_FINAL_REVIEW" && (
            <>
              <button type="button" onClick={() => act("RETURN")} disabled={busy} className={BUTTON}>Return to assignee</button>
              <button type="button" onClick={() => act("APPROVE")} disabled={busy} className={PRIMARY}>Approve</button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
