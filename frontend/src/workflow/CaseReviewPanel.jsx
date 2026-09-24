import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import { TRANSACTION_FLAGS } from "./flagTypes";
import { daysLeftText } from "./taskDue";
import { completeTask } from "./tasklistApi";

const SEVERITY_LABEL = { HIGH: "High", MEDIUM: "Medium", LOW: "Low" };

/**
 * Review popup for a case (specs/task-cases.md): every flag on one account and day, with its
 * transaction and why it was flagged, and one decision for all of them. Same order as the other
 * panels: mandatory comment, then the Tasklist completion, then the audit mirror.
 */
export default function CaseReviewPanel({ task, user, onDone, onClose }) {
  const caseId = task.vars.recordKey;
  const commentKey = { source_table: "task_cases", record_key: String(caseId), flag_label: task.vars.flagLabel };
  const { status, data, error, reload } = useAsync(
    () => Promise.all([api.caseDetail(caseId), api.exceptionComments(commentKey)]),
    [task.id],
  );
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the case" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const [kase, comments] = data;

  async function decide(outcome) {
    setFormError("");
    if (!comment.trim()) return setFormError("A comment is required before taking this action.");
    setBusy(true);
    try {
      await api.addExceptionComment({ ...commentKey, comment_text: comment });
      await completeTask(task.id, { outcome, correctedValue: "", reviewedByUserId: user.user_id });
      await api.logTaskCompletion({ ...commentKey, outcome, camunda_task_id: task.id });
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">{task.vars.title || `Case #${caseId}`}</h3>
      <p className="mt-0.5 text-sm text-ink2">
        {SEVERITY_LABEL[kase.severity]} severity · due {kase.due_date} ({daysLeftText(kase.due_date)}) · one decision applies to all {kase.flag_count} flags
      </p>

      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Flags in this case</h3>
      <DataTable
        caption="Flags in this case"
        columns={[
          { key: "transaction_id", header: "Transaction" },
          { key: "date", header: "Date" },
          { key: "amount", header: "Amount", align: "right", render: (f) => (f.amount == null ? "—" : `${Number(f.amount).toLocaleString("en-US")} ${f.currency}`) },
          { key: "channel", header: "Channel" },
          { key: "rule", header: "Why", render: (f) => TRANSACTION_FLAGS[f.flag_label]?.reason || f.flag_label },
          { key: "description", header: "Detail" },
        ]}
        rows={kase.flags}
        rowKey={(f) => `${f.transaction_id}:${f.flag_label}`}
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

      <h3 className="mb-2 text-sm font-medium text-ink2">Decision</h3>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Comment (required)"
          aria-label="Comment"
          className="mb-3 w-full rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
        />
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:opacity-60">Cancel</button>
          <button type="button" onClick={() => decide("REJECTED")} disabled={busy} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60">Reject all</button>
          <button type="button" onClick={() => decide("APPROVED")} disabled={busy} className="rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60">Approve all</button>
        </div>
      </div>
    </>
  );
}
