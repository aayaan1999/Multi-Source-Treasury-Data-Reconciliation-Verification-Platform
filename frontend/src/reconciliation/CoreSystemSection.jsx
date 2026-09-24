import { useState } from "react";
import { api } from "../api";
import { useAuth } from "../auth";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { fmtAmount } from "./pipeline";

const MISMATCH_LABEL = {
  VALUE_MISMATCH: "Value mismatch",
  MISSING_IN_CANONICAL: "Missing in our data",
  MISSING_IN_SOURCE: "Missing in source system",
};
const STATUS_LABEL = { OPEN: "Open", ACCEPTED: "Accepted", CORRECTED: "Corrected", DISMISSED: "Dismissed", AUTO_ACCEPTED: "Cleared automatically" };
const TYPE_TABS = [["", "All types"], ...Object.entries(MISMATCH_LABEL)];
const BUTTON = "rounded-md border border-hair px-3 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page disabled:opacity-60";
const INPUT = "rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink";

function fmtDateTime(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

/** Whole days a break has been open, from when it was first seen. */
export function ageDays(firstSeen, now = new Date()) {
  if (!firstSeen) return null;
  return Math.max(0, Math.floor((now - new Date(firstSeen)) / 86400000));
}

export function ageBucket(days) {
  if (days == null) return "—";
  return days <= 7 ? "0-7 days" : days <= 30 ? "8-30 days" : "30+ days";
}

/** The filtered breaks as CSV text, for the reconciliation team or auditors. */
export function toCsv(rows, columns) {
  const cell = (v) => {
    const s = v == null ? "" : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  return [columns.map(([, header]) => cell(header)).join(","), ...rows.map((r) => columns.map(([key]) => cell(r[key])).join(","))].join("\n");
}

function download(filename, text) {
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv" }));
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

/** The latest run: what it found and cleared, what's open, and its sign-off (preparer, then a second person). */
function RunPanel() {
  const { user } = useAuth() || {};
  const { status, data, error, reload } = useAsync(() => api.reconRun(), []);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  if (status === "loading") return <Loading what="the latest run" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  if (!data.run_date) return <p className="mt-4 text-sm text-ink2">No comparison with the core system has run yet.</p>;

  const signoff = data.signoff;
  const canSign = ["approver", "admin"].includes(user?.role) && signoff?.status === "SUBMITTED" && signoff.prepared_by !== user?.user_id;
  const canSubmit = !signoff || signoff.status === "RETURNED";

  async function send(call) {
    setFormError("");
    setBusy(true);
    try {
      await call();
      setNote("");
      reload();
    } catch (e) {
      setFormError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <ul className="mt-6 grid grid-cols-2 gap-5 lg:grid-cols-4" aria-label="Latest run">
        <StatBox label="Breaks in the latest run" value={data.breaks_seen} hint={`Run of ${data.run_date}`} />
        <StatBox label="Cleared automatically" value={data.auto_cleared} hint="Formatting only" />
        <StatBox label="Open groups" value={data.groups_open} hint="One task each, in Tasks" status={data.groups_open ? "watch" : "good"} />
        <StatBox label="Important, open" value={data.important_open} hint={`${data.recurring_open} recurring break(s) open`} status={data.important_open ? "action" : "good"} />
      </ul>
      <div className="card mt-4 rounded-xl border border-hair bg-surface p-4 text-sm" aria-label="Run sign-off">
        <p className="text-ink">
          <strong>Sign-off:</strong>{" "}
          {!signoff && "not submitted yet."}
          {signoff?.status === "SUBMITTED" && `submitted by ${signoff.prepared_by_name}${signoff.prepare_note ? ` ("${signoff.prepare_note}")` : ""}, waiting for a second person.`}
          {signoff?.status === "SIGNED_OFF" && `signed off by ${signoff.signed_by_name} (prepared by ${signoff.prepared_by_name}).`}
          {signoff?.status === "RETURNED" && `returned by ${signoff.signed_by_name}: "${signoff.sign_note}". Fix and resubmit.`}
        </p>
        {(canSubmit || canSign) && (
          <div className="mt-3 flex flex-wrap items-center gap-2">
            <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" aria-label="Sign-off note" className={`${INPUT} min-w-[14rem] flex-1`} />
            {canSubmit && <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.submitReconRun({ note: note || undefined }))}>Submit for sign-off</button>}
            {canSign && (
              <>
                <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.signOffReconRun({ decision: "RETURN", note }))}>Return</button>
                <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.signOffReconRun({ decision: "SIGN_OFF", note: note || undefined }))}>Sign off</button>
              </>
            )}
          </div>
        )}
        {formError && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
      </div>
    </>
  );
}

function GroupsTable() {
  const { status, data, error, reload } = useAsync(() => api.reconGroups(), []);
  if (status === "loading") return <Loading what="the groups" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  return (
    <DataTable
      caption="Groups of breaks"
      columns={[
        { key: "pattern", header: "Cause", render: (g) => `${g.entity_type} ${g.field_name || ""} ${g.pattern}`.replace(/\s+/g, " ") },
        { key: "break_count", header: "Breaks", align: "right" },
        { key: "total_difference", header: "Total difference", align: "right", render: (g) => (g.total_difference == null ? "—" : fmtAmount(g.total_difference)) },
        { key: "important", header: "Kind", render: (g) => (g.important ? "Important, on its own" : g.requires_second_approval ? "Bulk, needs second approval" : "Bulk") },
        { key: "status", header: "Status", render: (g) => (g.status === "CLOSED" ? `Decided: ${g.decision?.toLowerCase()}` : "Open: decide in Tasks") },
        { key: "due_date", header: "Due" },
      ]}
      rows={data}
      rowKey={(g) => g.group_id}
      rowFlag={(g) => (g.important && g.status !== "CLOSED" ? { kind: "loss", label: "Important" } : null)}
      emptyText="No groups yet: open breaks are grouped when the task bridge next runs."
    />
  );
}

/** Admin override (the one route outside Tasks): resolve a single break, audited like any decision. */
function AdminResolve({ row, onDone }) {
  const [status, setStatus] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  async function submit() {
    setError("");
    if (!status) return setError("Pick Accept, Correct or Dismiss.");
    try {
      await api.resolveReconciliation(row.exception_id, { status, resolution_note: note || undefined });
      onDone();
    } catch (e) {
      setError(e.message);
    }
  }
  return (
    <div className="card mt-4 rounded-xl border border-hair bg-surface p-4">
      <p className="mb-2 text-sm text-ink2">Admin override: decisions normally happen in the group's task.</p>
      <div className="flex flex-wrap items-center gap-2">
        {[["ACCEPTED", "Accept"], ["CORRECTED", "Correct"], ["DISMISSED", "Dismiss"]].map(([v, l]) => (
          <button key={v} type="button" onClick={() => setStatus(v)} className={status === v ? "rounded-md bg-accent px-3 py-1.5 text-sm text-white" : BUTTON}>{l}</button>
        ))}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" aria-label="Override note" className={`${INPUT} flex-1`} />
        <button type="button" onClick={submit} className={BUTTON}>Resolve</button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
    </div>
  );
}

/**
 * "Our data vs the core banking system" (specs/reconciliation-groups.md, client point 1): the latest
 * run and its sign-off, the groups (decided in Tasks), and every break with filters, age and export.
 * Read-only apart from sign-off and the admin override: decisions happen in the group tasks.
 */
export default function CoreSystemSection() {
  const { user } = useAuth() || {};
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [recurringOnly, setRecurringOnly] = useState(false);
  const [selected, setSelected] = useState(null);
  const { status, data, error, reload } = useAsync(() => api.reconciliationExceptions({ limit: 5000 }), []);

  const rows = (data || [])
    .filter((r) => (!statusFilter || r.status === statusFilter) && (!typeFilter || r.mismatch_type === typeFilter) && (!recurringOnly || r.recurring))
    .map((r) => ({ ...r, age: ageDays(r.first_seen || r.detected_at) }));

  const exportColumns = [
    ["entity_type", "Record type"], ["entity_id", "Record"], ["field_name", "Field"], ["mismatch_type", "Type"],
    ["source_value", "Core system"], ["canonical_value", "Ours"], ["status", "Status"], ["resolved_rule", "Cleared by rule"],
    ["group_id", "Group"], ["first_seen", "First seen"], ["last_seen", "Last seen"], ["times_seen", "Times seen"], ["recurring", "Recurring"],
  ];

  return (
    <>
      <RunPanel />

      <Section id="groups" title="Groups" description="Breaks with the same cause are decided together, as one task in Tasks. Important breaks (missing records, key fields, large amounts) are always on their own.">
        <GroupsTable />
      </Section>

      <div role="tablist" aria-label="Filter by mismatch type" className="mt-8 flex flex-wrap gap-1 border-b border-hair pb-2.5">
        {TYPE_TABS.map(([value, label]) => (
          <button
            key={value || "all"}
            type="button"
            role="tab"
            aria-selected={typeFilter === value}
            onClick={() => setTypeFilter(value)}
            className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition-all ${typeFilter === value ? "bg-accent font-medium text-white" : "text-ink2 hover:bg-page hover:text-ink"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <Section
        id="exceptions"
        title="All breaks"
        description="Every difference found, with how long it has been open. Click a row for its details."
        action={
          <div className="flex flex-wrap items-center gap-3">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Status" className={INPUT}>
              <option value="">All statuses</option>
              {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-sm text-ink2">
              <input type="checkbox" checked={recurringOnly} onChange={(e) => setRecurringOnly(e.target.checked)} />
              Recurring only
            </label>
            <button type="button" className={BUTTON} disabled={!rows.length} onClick={() => download("reconciliation-breaks.csv", toCsv(rows, exportColumns))}>Export CSV</button>
          </div>
        }
      >
        {status === "loading" && <Loading what="the breaks" />}
        {status === "error" && !data && <LoadError error={error} onRetry={reload} />}
        {data && (
          <DataTable
            caption="Reconciliation exceptions"
            columns={[
              { key: "entity", header: "Record", render: (r) => `${r.entity_type} ${r.entity_id}` },
              { key: "field_name", header: "Field", render: (r) => r.field_name || "(whole record)" },
              { key: "mismatch_type", header: "Type", render: (r) => MISMATCH_LABEL[r.mismatch_type] || r.mismatch_type },
              { key: "source_value", header: "Core system" },
              { key: "canonical_value", header: "Ours" },
              { key: "status", header: "Status", render: (r) => STATUS_LABEL[r.status] || r.status },
              { key: "age", header: "Open for", render: (r) => (r.status === "OPEN" ? `${r.age} d (${ageBucket(r.age)})` : "—") },
              { key: "times_seen", header: "Seen", align: "right", render: (r) => `${r.times_seen ?? 1}×${r.recurring ? " · recurring" : ""}` },
            ]}
            rows={rows}
            rowKey={(r) => r.exception_id}
            rowFlag={(r) => (r.recurring && r.status === "OPEN" ? { kind: "watch", label: "Recurring" } : null)}
            selectedKey={selected?.exception_id}
            onRowClick={setSelected}
            emptyText="No breaks for this filter."
          />
        )}
      </Section>

      {selected && (
        <Modal title="Break details" onClose={() => setSelected(null)}>
          <h3 className="text-sm font-semibold tracking-tight text-ink">
            {selected.entity_type} {selected.entity_id}{selected.field_name ? ` — ${selected.field_name}` : ""}
          </h3>
          <dl className="card mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-xl border border-hair bg-surface p-4 text-sm sm:grid-cols-3">
            <div><dt className="text-ink2">Core system value</dt><dd className="font-medium text-ink">{selected.source_value ?? "—"}</dd></div>
            <div><dt className="text-ink2">Our value</dt><dd className="font-medium text-ink">{selected.canonical_value ?? "—"}</dd></div>
            <div><dt className="text-ink2">Status</dt><dd className="font-medium text-ink">{STATUS_LABEL[selected.status] || selected.status}</dd></div>
            <div><dt className="text-ink2">First seen</dt><dd className="font-medium text-ink">{fmtDateTime(selected.first_seen)}</dd></div>
            <div><dt className="text-ink2">Last seen</dt><dd className="font-medium text-ink">{fmtDateTime(selected.last_seen)}</dd></div>
            <div><dt className="text-ink2">Seen</dt><dd className="font-medium text-ink">{selected.times_seen ?? 1} time(s){selected.recurring ? ", recurring" : ""}</dd></div>
          </dl>
          <p className="mt-3 text-sm text-ink2">
            {selected.resolved_rule && `Cleared automatically by rule ${selected.resolved_rule}. `}
            {selected.group_id && `Part of group #${selected.group_id}${selected.status === "OPEN" ? ": decide it in Tasks." : "."}`}
            {!selected.group_id && selected.status === "OPEN" && "Not grouped yet: it joins a group when the task bridge next runs."}
            {selected.resolved_by_name && ` Resolved by ${selected.resolved_by_name}${selected.resolution_note ? `: ${selected.resolution_note}` : ""}.`}
          </p>
          {user?.role === "admin" && selected.status === "OPEN" && (
            <AdminResolve row={selected} onDone={() => { setSelected(null); reload(); }} />
          )}
        </Modal>
      )}
    </>
  );
}
