import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import { completeTask, getVariables } from "../workflow/tasklistApi";
import { fmtAmount } from "./pipeline";

export const DECISIONS = [
  ["ACCEPT", "Accept", "the difference is explained and fine"],
  ["CORRECT", "Correct our data", "our copy is wrong and will be fixed"],
  ["DISMISS", "Dismiss", "not a real difference"],
];
const DECISION_WORD = Object.fromEntries(DECISIONS.map(([k, label]) => [k, label]));

/** "Accept all", or "Accept all except 3" once breaks are left out. */
export function decisionLabel(label, leftOut, total) {
  if (total === 1) return label;
  return leftOut ? `${label} all except ${leftOut}` : `${label} all`;
}

function step(task) {
  return task.taskDefinitionId === "UserTask_SecondApproval" || task.name === "Second approval" ? "SECOND_APPROVAL" : "REVIEW";
}

/**
 * Review popup for a group of core-system reconciliation breaks (specs/reconciliation-groups.md):
 * the group's summary and every break in it; one decision for all of them, leaving out (carving
 * out) any that need their own look. A large bulk decision then goes to a second approver, who sees
 * what was decided and approves or returns it.
 */
export default function GroupReviewPanel({ task, user, onDone, onClose }) {
  const groupId = task.vars.recordKey;
  const commentKey = { source_table: "reconciliation_groups", record_key: String(groupId), flag_label: "RECON_GROUP" };
  const current = step(task);
  const { status, data, error, reload } = useAsync(
    () => Promise.all([
      api.reconGroup(groupId),
      api.exceptionComments(commentKey),
      current === "SECOND_APPROVAL" ? getVariables(task.id) : Promise.resolve({}),
    ]),
    [task.id],
  );
  const [leftOut, setLeftOut] = useState(() => new Set());
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the group" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const [group, comments, vars] = data;
  const open = group.breaks.filter((b) => b.status === "OPEN");
  const canCarveOut = !group.important && open.length > 1;

  function toggle(id) {
    setLeftOut((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function act(variables) {
    setFormError("");
    if (!comment.trim()) return setFormError("A comment is required before taking this action.");
    if (current === "REVIEW" && leftOut.size >= open.length) return setFormError("Leave at least one break in the group, or it has nothing to decide.");
    setBusy(true);
    try {
      await api.addExceptionComment({ ...commentKey, comment_text: comment });
      await completeTask(task.id, variables);
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  const summary = [
    `${group.break_count} break${group.break_count === 1 ? "" : "s"}`,
    group.total_difference != null ? `total difference ${fmtAmount(group.total_difference)}` : null,
    group.largest_difference != null && group.break_count > 1 ? `largest ${fmtAmount(group.largest_difference)}` : null,
    `due ${group.due_date}`,
  ].filter(Boolean).join(" · ");

  return (
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">{task.vars.title || `Group #${groupId}`}</h3>
      <p className="mt-0.5 text-sm text-ink2">{summary}</p>
      {group.important && (
        <p className="mt-2 text-sm font-medium" style={{ color: "var(--critical)" }}>
          Important break: decided on its own, never in bulk (missing record, key field, or a large amount).
        </p>
      )}
      {group.requires_second_approval && (
        <p className="mt-2 text-sm text-ink2">This is a large bulk decision: a second person (the CFO) approves it before it takes effect.</p>
      )}

      {current === "SECOND_APPROVAL" && (
        <div className="card mt-4 rounded-xl border border-hair bg-surface p-4 text-sm text-ink">
          The reviewer chose <strong>{DECISION_WORD[vars.decision] || vars.decision}</strong> for this group
          {vars.excludedIds?.length ? `, leaving out ${vars.excludedIds.length} break(s) for their own review` : ""}.
        </div>
      )}

      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Breaks in this group</h3>
      <DataTable
        caption="Breaks in this group"
        columns={[
          ...(current === "REVIEW" && canCarveOut ? [{
            key: "leave_out", header: "Leave out",
            render: (b) => (
              <input type="checkbox" aria-label={`Leave out ${b.entity_id}`} checked={leftOut.has(b.exception_id)} onChange={() => toggle(b.exception_id)} disabled={b.status !== "OPEN"} />
            ),
          }] : []),
          { key: "entity_id", header: "Record" },
          { key: "field_name", header: "Field", render: (b) => b.field_name || "(whole record)" },
          { key: "source_value", header: "Core system", render: (b) => b.source_value ?? "—" },
          { key: "canonical_value", header: "Ours", render: (b) => b.canonical_value ?? "—" },
          { key: "times_seen", header: "Seen", align: "right", render: (b) => `${b.times_seen}×${b.recurring ? " (recurring)" : ""}` },
          { key: "status", header: "Status" },
        ]}
        rows={group.breaks}
        rowKey={(b) => b.exception_id}
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
          placeholder="Comment (required), e.g. the cause: late fee batch confirmed with core banking ops"
          aria-label="Comment"
          className="mb-3 w-full rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
        />
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onClose} disabled={busy} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:opacity-60">Cancel</button>
          {current === "REVIEW" && DECISIONS.map(([key, label, meaning], i) => (
            <button
              key={key}
              type="button"
              title={meaning}
              disabled={busy}
              onClick={() => act({ decision: key, excludedIds: [...leftOut], decidedByUserId: user.user_id })}
              className={i === 0
                ? "rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60"
                : "rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60"}
            >
              {decisionLabel(label, leftOut.size, open.length)}
            </button>
          ))}
          {current === "SECOND_APPROVAL" && (
            <>
              <button type="button" disabled={busy} onClick={() => act({ approvalDecision: "RETURN" })} className="rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60">Return to reviewer</button>
              <button type="button" disabled={busy} onClick={() => act({ approvalDecision: "APPROVE", approvedByUserId: user.user_id })} className="rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-white transition hover:brightness-110 disabled:opacity-60">Approve</button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
