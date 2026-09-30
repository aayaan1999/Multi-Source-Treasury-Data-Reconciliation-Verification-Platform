import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { Loading, LoadError } from "../components/PageShell";
import useAsync from "../hooks/useAsync";
import { formatDateTime } from "../kpi/format";
import { completeTask, getVariables } from "../workflow/tasklistApi";
import { roleTitle } from "../access";
import ImportantTag from "./ImportantTag";
import { correctableFields, fmtAmount } from "./pipeline";
import { blockedReason, carryBadge, carryText, DECISION_PAST, DECISIONS, decisionLabel, sentBackText, stages, stepOf } from "./reconTask";

const BUTTON = "rounded-md border border-hair px-3.5 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60";
const PRIMARY = "rounded-md bg-accent px-3.5 py-1.5 text-sm font-medium text-on-accent transition hover:brightness-110 disabled:opacity-60";
const INPUT = "rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink";
const SYSTEM = { neon: "Core banking", salesforce: "CRM" };
const COMMENT_KEY = {
  reconciliation: (key) => ({ source_table: "pipeline_reconciliation", record_key: key, flag_label: "RECONCILIATION" }),
  recon_group: (key) => ({ source_table: "reconciliation_groups", record_key: key, flag_label: "RECON_GROUP" }),
  recon_run: (key) => ({ source_table: "reconciliation_runs", record_key: key, flag_label: "RECON_RUN" }),
};

const isNumber = (v) => v !== null && v !== undefined && String(v).trim() !== "" && Number.isFinite(Number(String(v).replace(/,/g, "")));
/** "619196.0900" -> "619196.09": the source value as a fixed value is filled in. */
export const plainValue = (v) => (isNumber(v) ? String(Number(String(v).replace(/,/g, ""))) : v ?? "");

async function load(task, kind, key) {
  const [vars, comments, detail] = await Promise.all([
    getVariables(task.id),
    api.exceptionComments(COMMENT_KEY[kind](key)),
    kind === "reconciliation"
      ? Promise.all([api.pipelineRecords(key), api.pipelineCorrections(key)]).then(([r, corrections]) => ({ ...r, corrections }))
      : kind === "recon_group" ? api.reconGroup(key) : api.reconRunDetail(key),
  ]);
  return { vars, comments, detail };
}

// How each state of a step looks: its numbered marker, and the colour of its status line.
const MARKER = {
  done: { background: "color-mix(in srgb, var(--good) 14%, transparent)", color: "var(--good)", borderColor: "var(--good)" },
  current: { background: "var(--series-1)", color: "var(--on-accent)", borderColor: "var(--series-1)", boxShadow: "0 0 0 4px var(--series-1-soft)" },
  pending: {},
  skipped: { borderStyle: "dashed", opacity: 0.6 },
};
const STATUS_COLOR = { done: "var(--good)", current: "var(--ink)", pending: undefined, skipped: undefined };

/** The step tracker: each stage numbered and joined by a line, with who acts at it and where it stands -
 * done, happening now, still to come (and why the CFO is needed) or not needed. */
function Progress({ items }) {
  return (
    <ol className="grid gap-4 sm:grid-cols-3 sm:gap-0" aria-label="Steps">
      {items.map((s, i) => (
        <li key={s.label} aria-current={s.state === "current" ? "step" : undefined} className="flex gap-3 sm:flex-col sm:gap-2 sm:pr-4">
          <div className="flex items-center">
            <span
              aria-hidden
              className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full border border-hair text-xs font-semibold text-ink2"
              style={MARKER[s.state]}
            >
              {s.state === "done" ? "✓" : i + 1}
            </span>
            {i < items.length - 1 && (
              <span aria-hidden className="ml-2 hidden h-0.5 flex-1 rounded-full sm:block"
                style={{ background: s.state === "done" ? "var(--good)" : "var(--axis)", opacity: s.state === "done" ? 0.6 : 1 }} />
            )}
          </div>
          <div className={s.state === "skipped" ? "opacity-60" : undefined}>
            <p className={`text-sm font-semibold ${s.state === "current" ? "text-ink" : "text-ink2"}`}>{s.label}</p>
            <p className="text-xs text-ink2">{s.who}</p>
            <p className={`mt-1 text-xs ${s.state === "current" ? "font-medium" : ""}`} style={{ color: STATUS_COLOR[s.state] }}>{s.detail}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

/** One rejected row, every field shown, the one that failed the check highlighted. */
function RowValues({ data, bad }) {
  if (!data) return <span className="text-ink2">—</span>;
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5">
      {Object.entries(data).map(([k, v]) => (
        <span key={k} className={k === bad ? "font-semibold" : "text-ink2"} style={k === bad ? { color: "var(--critical)" } : undefined}>
          {k}: {v === null || v === "" ? "(empty)" : String(v)}
        </span>
      ))}
    </span>
  );
}

/** Enter the right value for one field of one rejected row (a pipeline gap, at team review). */
function CorrectionForm({ reconId, sourceTable, records, onSaved }) {
  const byKey = Object.fromEntries(records.filter((r) => r.record_data).map((r) => [r.record_key, r]));
  const [recordKey, setRecordKey] = useState(Object.keys(byKey).length === 1 ? Object.keys(byKey)[0] : "");
  const [field, setField] = useState(Object.keys(byKey).length === 1 ? Object.values(byKey)[0].bad_field || "" : "");
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const record = byKey[recordKey];
  const fields = correctableFields(record?.record_data, sourceTable);
  const current = record && field ? record.record_data[field] : undefined;

  async function save(e) {
    e.preventDefault();
    setError("");
    if (!recordKey || !field || !value.trim()) return setError("Pick the row and the field, and enter the right value.");
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
    <form onSubmit={save} className="card mt-3 rounded-xl border border-hair bg-surface p-4" aria-label="Enter a corrected value">
      <p className="mb-2 text-sm text-ink2">To correct our data, enter the right value for each wrong field. It loads in the next run once the CFO approves.</p>
      <div className="flex flex-wrap items-center gap-2">
        <select value={recordKey} onChange={(e) => { setRecordKey(e.target.value); setField(byKey[e.target.value]?.bad_field || ""); }} aria-label="Row" className={INPUT}>
          <option value="">Row…</option>
          {Object.keys(byKey).map((k) => <option key={k} value={k}>{k}</option>)}
        </select>
        <select value={field} onChange={(e) => setField(e.target.value)} aria-label="Field" className={INPUT} disabled={!recordKey}>
          <option value="">Field…</option>
          {fields.map((f) => <option key={f} value={f}>{f}</option>)}
        </select>
        <input value={value} onChange={(e) => setValue(e.target.value)} placeholder="Right value" aria-label="Right value" className={`${INPUT} min-w-[9rem] flex-1`} />
        <button type="submit" disabled={busy} className={BUTTON}>{busy ? "Saving…" : "Save value"}</button>
      </div>
      {field && <p className="mt-2 text-sm text-ink2">Now: {current === null || current === undefined || current === "" ? "(empty)" : String(current)}</p>}
      {error && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
    </form>
  );
}

function Fixes({ corrections, emptyText }) {
  return (
    <DataTable
      caption="Fixes"
      columns={[
        { key: "record_key", header: "Record" },
        { key: "field_name", header: "Field" },
        { key: "old_value", header: "Now", render: (c) => c.old_value ?? "(empty)" },
        { key: "new_value", header: "Fixed to" },
        { key: "status", header: "Status", render: (c) => (c.status === "APPROVED" ? `Approved by ${c.approved_by_name}` : "Waiting for the CFO") },
      ]}
      rows={corrections}
      rowKey={(c) => c.correction_id}
      emptyText={emptyText}
    />
  );
}

/**
 * The popup for every reconciliation task (specs/reconciliation-approvals.md): a pipeline gap or a group of
 * core-system breaks at team review or CFO approval, or a run at sign-off. It says what happened and what
 * to decide, shows the rows behind it, and completes the Tasklist task with the decision; Camunda moves the
 * process on and the bridge workers save it (refusing, with a reason, an approval or sign-off by the wrong
 * person - checked here first too).
 */
export default function ReconTaskPanel({ task, user, onDone, onClose }) {
  const kind = task.vars.recordType;
  const key = String(task.vars.recordKey);
  const step = stepOf(task);
  const { status, data, error, reload } = useAsync(() => load(task, kind, key), [task.id]);
  const [comment, setComment] = useState("");
  const [postedComment, setPostedComment] = useState("");
  const [picked, setPicked] = useState(() => new Set());
  const [edits, setEdits] = useState({});
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");

  if (status === "loading") return <Loading what="the task" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const { vars, comments, detail } = data;

  const isRun = kind === "recon_run";
  const isGroup = kind === "recon_group";
  const subject = isRun ? detail : isGroup ? detail : detail.item;
  const summary = detail.summary || {};
  const openBreaks = isGroup ? detail.breaks.filter((b) => b.status === "OPEN") : [];
  const missingRecord = isGroup && detail.mismatch_type !== "VALUE_MISMATCH";
  const corrections = (isRun ? [] : detail.corrections) || [];
  const proposed = corrections.filter((c) => c.status === "PROPOSED");
  const canLeaveOut = isGroup && step === "TEAM" && openBreaks.length > 1;
  const canSendBackTasks = isRun && step === "SIGNOFF";
  // Sign-off with tasks still open (past the cut-off): the decided ones are signed off, the open ones carried.
  const decidedTasks = isRun ? detail.tasks.filter((t) => t.decided).length : 0;
  const waitingForMe = isRun ? detail.tasks.filter((t) => t.awaiting_cfo).length : 0;
  const openTasks = isRun ? detail.tasks.length - decidedTasks - waitingForMe : 0;
  const blocked = blockedReason(step, user, {
    decidedBy: subject.decided_by,
    deciders: isRun ? detail.tasks.map((t) => t.decided_by).filter(Boolean) : [],
  });
  const refusal = { TEAM: vars.decisionError, CFO: vars.approvalError, SIGNOFF: vars.signoffError }[step];
  // Sent back to the team: the task's own variables, else what the item or group row records.
  const sentBack = sentBackText(vars.sentBackAt ? vars : {
    sentBackAt: subject.sent_back_at, sentBackByName: subject.sent_back_by_name, sentBackFrom: subject.sent_back_from, sentBackNote: subject.sent_back_note,
  });

  function toggle(id) {
    setPicked((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  async function act(variables, { needsComment, check } = {}) {
    setFormError("");
    const text = comment.trim();
    if (blocked) return setFormError(blocked);
    if (needsComment && !text) return setFormError(needsComment);
    const problem = check?.();
    if (problem) return setFormError(problem);
    setBusy(true);
    try {
      // Posted once: a retry after a failed completion doesn't add the same comment again.
      if (text && text !== postedComment) {
        await api.addExceptionComment({ ...COMMENT_KEY[kind](key), comment_text: text });
        setPostedComment(text);
      }
      await completeTask(task.id, variables);
      onDone();
    } catch (err) {
      setFormError(err.message);
    } finally {
      setBusy(false);
    }
  }

  // A group's fixed values: what the reviewer typed, else the source system's value.
  const fixedValue = (b) => edits[b.exception_id] ?? plainValue(b.source_value);
  const kept = openBreaks.filter((b) => !picked.has(b.exception_id));
  const fixProblem = () => {
    for (const b of kept) {
      const v = String(fixedValue(b)).trim();
      if (!v) return `Enter the fixed value for ${b.entity_type} ${b.entity_id}.`;
      if (isNumber(b.canonical_value) && !isNumber(v)) return `${b.field_name} is a number: enter a number for ${b.entity_type} ${b.entity_id}.`;
      const same = isNumber(b.canonical_value) ? Number(v.replace(/,/g, "")) === Number(b.canonical_value) : v === b.canonical_value;
      if (same) return `The fixed value for ${b.entity_type} ${b.entity_id} is the same as ours: change it, or leave the record out.`;
    }
    return null;
  };

  const decide = (decision) => act(
    {
      decision, decidedByUserId: user.user_id, excludedIds: isGroup ? [...picked] : [],
      ...(isGroup && decision === "CORRECT" ? { correctedValues: Object.fromEntries(kept.map((b) => [b.exception_id, String(fixedValue(b)).trim()])) } : {}),
    },
    {
      needsComment: "Say why in a comment (for example, what caused the difference).",
      check: () => {
        if (decision === "CORRECT" && !isGroup && !proposed.length) return "Enter the right value for at least one row first (below), then choose Assign to CFO.";
        if (decision === "CORRECT" && missingRecord) return "A missing record can't be corrected from here: accept or dismiss it.";
        if (isGroup && openBreaks.length && picked.size >= openBreaks.length) return "Leave at least one record in the group, or there's nothing to decide.";
        if (isGroup && decision === "CORRECT") return fixProblem();
        return null;
      },
    },
  );

  const decisionText = subject.decision && `${subject.decided_by_name || "The team"} decided: ${DECISION_PAST[subject.decision]}`;
  const system = SYSTEM[detail.source_system] || "Source";

  return (
    <>
      <h3 className="text-base font-semibold tracking-tight text-ink">
        {task.vars.title || task.name}
        {!isRun && subject.cfo_required && <ImportantTag reason={subject.cfo_reason} />}
      </h3>
      {!isRun && subject.cfo_required && step === "TEAM" && (
        <p className="mt-1 text-sm text-ink2">Whatever you decide, this task goes to the CFO for approval next.</p>
      )}

      <div className="card mt-3 rounded-xl border border-hair bg-surface p-4 text-sm">
        <p className="font-medium text-ink">{summary.headline}</p>
        {summary.reasons?.length > 0 && (
          <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink">{summary.reasons.map((r) => <li key={r}>{r}</li>)}</ul>
        )}
        {summary.money && <p className="mt-2 text-ink">{summary.money}</p>}
        <p className="mt-3 text-ink2">
          <strong className="text-ink">Your job: </strong>
          {step === "TEAM" && summary.job}
          {step === "CFO" && `${decisionText}. The CFO approves this because of ${vars.cfoReason || subject.cfo_reason || "its importance"}. Check it, then approve, or send it back to the team with a reason.`}
          {step === "SIGNOFF" && summary.job}
        </p>
      </div>

      {!isRun && carryText(subject) && (
        <p role="note" className="mt-3 rounded-lg border p-3 text-sm font-medium"
          style={{ color: subject.escalated_at ? "var(--critical)" : "var(--warning)", borderColor: subject.escalated_at ? "var(--critical)" : "var(--warning)" }}>
          {carryText(subject)}
        </p>
      )}
      {step === "TEAM" && sentBack && (
        <p role="note" className="mt-3 rounded-lg border p-3 text-sm font-medium" style={{ color: "var(--critical)", borderColor: "var(--critical)" }}>{sentBack}</p>
      )}
      {refusal && <p role="alert" className="mt-3 rounded-lg border border-hair p-3 text-sm" style={{ color: "var(--critical)" }}>Not saved: {refusal}</p>}

      <div className="card mt-4 rounded-xl border border-hair bg-surface p-4">
        <Progress items={stages(kind, step, { cfoRequired: subject.cfo_required, cfoReason: vars.cfoReason || subject.cfo_reason })} />
        {!isRun && detail.run && <p className="mt-3 text-xs text-ink2">Part of the {detail.run.name}: {detail.run.decided} of {detail.run.tasks} tasks decided.</p>}
      </div>

      {kind === "reconciliation" && (
        <>
          <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Rows we couldn't load</h4>
          {detail.records_available ? (
            <DataTable
              caption="Rows we couldn't load"
              columns={[
                { key: "record_key", header: "Row" },
                { key: "description", header: "Why it was rejected" },
                { key: "record_data", header: "What arrived", render: (r) => <RowValues data={r.record_data} bad={r.bad_field} /> },
              ]}
              rows={detail.records}
              rowKey={(r) => `${r.record_key}:${r.flag_label}`}
              emptyText={detail.item.note ? "No rows arrived." : "No rejected rows."}
            />
          ) : (
            <p className="card rounded-xl border border-hair bg-surface p-4 text-sm text-ink2">This item is from an older run; its rows are no longer kept.</p>
          )}
          {step === "TEAM" && <CorrectionForm reconId={Number(key)} sourceTable={detail.item.source_table} records={detail.records} onSaved={reload} />}
          <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Fixes</h4>
          <Fixes corrections={corrections} emptyText={step === "TEAM" ? "No values entered. Only needed for Assign to CFO." : "No fixes proposed."} />
        </>
      )}

      {isGroup && (
        <>
          <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Records that differ</h4>
          <DataTable
            caption="Records that differ"
            columns={[
              ...(canLeaveOut ? [{
                key: "leave_out", header: "Leave out",
                render: (b) => <input type="checkbox" aria-label={`Leave out ${b.entity_id}`} checked={picked.has(b.exception_id)} onChange={() => toggle(b.exception_id)} disabled={b.status !== "OPEN"} />,
              }] : []),
              { key: "entity_id", header: "Record", render: (b) => `${b.entity_type} ${b.entity_id}` },
              { key: "field_name", header: "Field", render: (b) => b.field_name || "(whole record)" },
              { key: "source_value", header: system, render: (b) => b.source_value ?? (b.mismatch_type === "MISSING_IN_SOURCE" ? "(missing)" : "—") },
              { key: "canonical_value", header: "Ours", render: (b) => b.canonical_value ?? (b.mismatch_type === "MISSING_IN_CANONICAL" ? "(missing)" : "—") },
              {
                key: "diff", header: "Difference", align: "right",
                render: (b) => {
                  const d = Number(b.source_value) - Number(b.canonical_value);
                  return b.source_value != null && b.canonical_value != null && Number.isFinite(d) ? `${d > 0 ? "+" : ""}${fmtAmount(d)}` : "—";
                },
              },
              { key: "times_seen", header: "Seen", align: "right", render: (b) => `${b.times_seen}×${b.recurring ? " (recurring)" : ""}` },
              ...(step === "TEAM" && !missingRecord ? [{
                key: "fixed", header: "Fixed value",
                render: (b) => (
                  <input
                    value={fixedValue(b)}
                    onChange={(e) => setEdits((all) => ({ ...all, [b.exception_id]: e.target.value }))}
                    disabled={b.status !== "OPEN" || picked.has(b.exception_id)}
                    aria-label={`Fixed value for ${b.entity_id}`}
                    className={`${INPUT} w-32`}
                    style={edits[b.exception_id] !== undefined && edits[b.exception_id] !== plainValue(b.source_value) ? { borderColor: "var(--series-1)" } : undefined}
                  />
                ),
              }] : []),
            ]}
            rows={detail.breaks}
            rowKey={(b) => b.exception_id}
          />
          {step === "TEAM" && !missingRecord && (
            <p className="mt-2 text-sm text-ink2">
              Assign to CFO proposes fixing each record kept in the group to its <strong className="text-ink">Fixed value</strong>. {system}'s value is
              filled in; change any that should be something else. The CFO approves the fixes before they're applied.
            </p>
          )}
          {corrections.length > 0 && (
            <>
              <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Fixes</h4>
              <Fixes corrections={corrections} emptyText="" />
            </>
          )}
        </>
      )}

      {isRun && (
        <>
          <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Every task in this run</h4>
          <DataTable
            caption="Every task in this run"
            columns={[
              ...(canSendBackTasks ? [{
                key: "send_back", header: "Send back",
                render: (t) => (t.decided
                  ? <input type="checkbox" aria-label={`Send back ${t.title}`} checked={picked.has(`${t.kind}:${t.id}`)} onChange={() => toggle(`${t.kind}:${t.id}`)} />
                  : null),
              }] : []),
              { key: "title", header: "Task", render: (t) => (
                <span>{t.title}{t.cfo_required && <ImportantTag />}{t.carried_count > 0 && <span className="ml-2 text-xs text-ink2">{carryBadge({ carried_count: t.carried_count, escalated: t.escalated })}</span>}</span>
              ) },
              { key: "decision", header: "Decision", render: (t) => (t.decision && t.decided ? DECISION_PAST[t.decision]
                : t.awaiting_cfo ? <span style={{ color: "var(--critical)" }}>Waiting for your approval</span>
                : <span style={{ color: "var(--warning)" }}>Open: carried to the next day</span>) },
              { key: "decided_by_name", header: "Decided by", render: (t) => t.decided_by_name || "—" },
              { key: "approved_by_name", header: "CFO approval", render: (t) => (t.cfo_required || t.approved_by_name ? t.approved_by_name || "Waiting" : "Not needed") },
              { key: "fixes", header: "Fixes", align: "right", render: (t) => t.fixes || "—" },
            ]}
            rows={detail.tasks}
            rowKey={(t) => `${t.kind}:${t.id}`}
            emptyText="Nothing to review in this run."
          />
        </>
      )}

      <h4 className="mb-2 mt-5 text-sm font-medium text-ink2">Comments</h4>
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

      <h4 className="mb-2 text-sm font-medium text-ink2">{step === "TEAM" ? "Decision" : step === "CFO" ? "Approval" : "Sign-off"}</h4>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        {blocked && <p className="mb-3 text-sm font-medium" style={{ color: "var(--critical)" }}>{blocked}</p>}
        {step === "TEAM" && ["approver", "admin"].includes(user.role) && (
          <p className="mb-3 text-sm text-ink2">You're signed in as {roleTitle(user)}. If you decide this task, someone else has to approve it and sign off the run.</p>
        )}
        <input
          type="text"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          placeholder={step === "TEAM" ? "Comment (required): why, e.g. fee batch confirmed with core banking operations"
            : step === "CFO" ? "Comment (required to send back)"
            : openTasks > 0 ? "Note (required): why the open tasks are carried over, or why tasks are sent back" : "Note (required to send back)"}
          aria-label="Comment"
          className={`${INPUT} mb-3 w-full px-3`}
        />
        {formError && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
        <div className="flex flex-wrap items-center gap-2">
          <button type="button" onClick={onClose} disabled={busy} className={BUTTON}>Cancel</button>
          {step === "TEAM" && DECISIONS.map(([decision, one, group, meaning]) => (
            <button key={decision} type="button" title={meaning} disabled={busy || (decision === "CORRECT" && missingRecord)}
              onClick={() => decide(decision)} className={decision === "ACCEPT" ? PRIMARY : BUTTON}>
              {decisionLabel(one, group, picked.size, isGroup ? openBreaks.length : 1)}
            </button>
          ))}
          {step === "CFO" && (
            <>
              <button type="button" disabled={busy || !!blocked} className={BUTTON}
                onClick={() => act({ cfoDecision: "SEND_BACK", sentBackByUserId: user.user_id, sendBackNote: comment.trim() }, { needsComment: "Say why you're sending it back." })}>
                Send back to the team
              </button>
              <button type="button" disabled={busy || !!blocked} className={PRIMARY}
                onClick={() => act({ cfoDecision: "APPROVE", approvedByUserId: user.user_id })}>
                Approve
              </button>
            </>
          )}
          {step === "SIGNOFF" && (
            <>
              <button type="button" disabled={busy || !!blocked} className={BUTTON}
                onClick={() => act(
                  { signoffDecision: "SEND_BACK", sentBackByUserId: user.user_id, sendBackNote: comment.trim(),
                    sendBackTasks: [...picked].map((p) => ({ kind: p.split(":")[0], id: Number(p.split(":")[1]) })) },
                  { needsComment: "Say why the tasks are being sent back.", check: () => (picked.size ? null : "Tick the tasks to send back.") },
                )}>
                Send back {picked.size ? `${picked.size} task${picked.size === 1 ? "" : "s"}` : "tasks"}
              </button>
              <button type="button" disabled={busy || !!blocked || picked.size > 0 || waitingForMe > 0} className={PRIMARY}
                onClick={() => act({ signoffDecision: "SIGN_OFF", signedByUserId: user.user_id, signNote: comment.trim() },
                  openTasks > 0 ? { needsComment: `Say why the ${openTasks} open task${openTasks === 1 ? " is" : "s are"} carried over to the next day.` } : {})}>
                {openTasks > 0 ? `Sign off ${decidedTasks} decided, carry ${openTasks}` : "Sign off the run"}
              </button>
            </>
          )}
        </div>
      </div>
    </>
  );
}
