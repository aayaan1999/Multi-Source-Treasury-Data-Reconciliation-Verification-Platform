import { useState } from "react";
import { api } from "../api";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import { completeTask } from "./tasklistApi";

const FIELDS = [
  ["customer_id", "Customer ID"], ["name", "Name"], ["segment", "Segment"], ["branch_name", "Branch"],
  ["country", "Country"], ["onboard_date", "Onboarded"], ["risk_rating", "Risk rating"],
];

function loansText(loans) {
  if (!loans?.length) return "No loans";
  return loans.map((l) => `${l.loan_count} loan${l.loan_count === 1 ? "" : "s"}, ${Number(l.outstanding).toLocaleString("en-US")} ${l.currency}`).join("; ");
}

/**
 * Review popup for a possible duplicate (specs/entity-matching.md): the two customer records side by
 * side with why they were matched, and a person's decision. "Same company" links them so their
 * exposure is added up; "Different companies" means the pair is never raised again. Nothing is merged
 * or changed in the customer records themselves.
 */
export default function EntityMatchPanel({ task, user, onDone, onClose }) {
  const candidateId = task.vars.recordKey;
  const commentKey = { source_table: "entity_match_candidates", record_key: String(candidateId), flag_label: "POSSIBLE_DUPLICATE" };
  const { status, data, error, reload } = useAsync(
    () => Promise.all([api.entityMatch(candidateId), api.exceptionComments(commentKey)]),
    [task.id],
  );
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the two records" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const [pair, comments] = data;
  const [a, b] = pair.customers;

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
      <h3 className="text-sm font-semibold tracking-tight text-ink">Are these the same company?</h3>
      <p className="mt-0.5 text-sm text-ink2">
        Match score {Math.round(pair.score * 100)}% · {pair.reasons.join(" · ")}
      </p>

      <div className="card mt-4 overflow-x-auto rounded-xl border border-hair bg-surface">
        <table className="w-full text-sm" aria-label="The two records">
          <thead>
            <tr className="border-b border-hair text-left text-ink2">
              <th className="px-4 py-2.5 font-medium" />
              <th className="px-4 py-2.5 font-medium">Record 1</th>
              <th className="px-4 py-2.5 font-medium">Record 2</th>
            </tr>
          </thead>
          <tbody>
            {FIELDS.map(([key, label]) => (
              <tr key={key} className="border-b border-hair last:border-0">
                <th scope="row" className="px-4 py-2 text-left font-normal text-ink2">{label}</th>
                <td className="px-4 py-2 text-ink">{a?.[key] ?? "—"}</td>
                <td className="px-4 py-2 text-ink">{b?.[key] ?? "—"}</td>
              </tr>
            ))}
            <tr>
              <th scope="row" className="px-4 py-2 text-left font-normal text-ink2">Loans</th>
              <td className="px-4 py-2 text-ink">{loansText(a?.loans)}</td>
              <td className="px-4 py-2 text-ink">{loansText(b?.loans)}</td>
            </tr>
          </tbody>
        </table>
      </div>
      {pair.customers.length < 2 && (
        <p className="mt-2 text-sm text-ink2">One of the records is no longer in the data; it may have been corrected at the source.</p>
      )}

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
        <p className="mb-3 text-sm text-ink2">
          "Same company" adds the two records' exposure together from the next data refresh. Neither record is changed.
        </p>
        <input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder="Comment (required), e.g. how you checked"
          aria-label="Comment"
          className="mb-3 w-full rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
        />
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:opacity-60">Cancel</button>
          <button type="button" onClick={() => decide("REJECTED")} disabled={busy} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60">Different companies</button>
          <button type="button" onClick={() => decide("APPROVED")} disabled={busy} className="rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60">Same company</button>
        </div>
      </div>
    </>
  );
}
