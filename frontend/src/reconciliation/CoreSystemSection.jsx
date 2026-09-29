import { useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api";
import { useAuth } from "../auth";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { fmtAmount } from "./pipeline";

// The systems our data is compared with: filter label, what their values are called, and in sentences.
export const SYSTEMS = {
  neon: { name: "Core banking system", label: "Core system", long: "the core banking system" },
  salesforce: { name: "CRM (Salesforce)", label: "CRM", long: "the CRM (Salesforce)" },
};
const SOURCE_KEYS = Object.keys(SYSTEMS);
const systemOf = (key) => SYSTEMS[key] || { name: key, label: key, long: key };

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
/** The latest run of one source and its sign-off (a run is signed off per source). */
function SignOff({ run, reload }) {
  const { user } = useAuth() || {};
  const system = systemOf(run.source_system);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [formError, setFormError] = useState("");
  const signoff = run.signoff;
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
    <div className="card rounded-xl border border-hair bg-surface p-4 text-sm" aria-label={`Run sign-off: ${system.name}`}>
      {/* The sign-off is for the whole run of one source, not one group: say so, and what it covers. */}
      <h3 className="font-semibold tracking-tight text-ink">{system.name}: sign-off for the whole run of {run.run_date}</h3>
      <p className="mt-1 text-ink2">
        Covers every group and break from this comparison with {system.long} ({run.breaks_seen} break(s)), not one group. Each
        group is decided in its own task; this is the final check that the run as a whole is finished.{" "}
        {run.groups_open
          ? `${run.groups_open} group(s) still open${run.important_open ? `, ${run.important_open} of them important (a note is required to submit)` : ""}.`
          : "All groups are decided."}
      </p>
      <p className="mt-2 text-ink">
        <strong>Status:</strong>{" "}
        {!signoff && "not submitted yet."}
        {signoff?.status === "SUBMITTED" && `submitted by ${signoff.prepared_by_name}${signoff.prepare_note ? ` ("${signoff.prepare_note}")` : ""}, waiting for a second person.`}
        {signoff?.status === "SIGNED_OFF" && `signed off by ${signoff.signed_by_name} (prepared by ${signoff.prepared_by_name}).`}
        {signoff?.status === "RETURNED" && `returned by ${signoff.signed_by_name}: "${signoff.sign_note}". Fix and resubmit.`}
      </p>
      {(canSubmit || canSign) && (
        <div className="mt-3 flex flex-wrap items-center gap-2">
          <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" aria-label={`Sign-off note: ${system.name}`} className={`${INPUT} min-w-[14rem] flex-1`} />
          {canSubmit && <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.submitReconRun({ source_system: run.source_system, note: note || undefined }))}>Submit for sign-off</button>}
          {canSign && (
            <>
              <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.signOffReconRun({ source_system: run.source_system, decision: "RETURN", note }))}>Return</button>
              <button type="button" className={BUTTON} disabled={busy} onClick={() => send(() => api.signOffReconRun({ source_system: run.source_system, decision: "SIGN_OFF", note: note || undefined }))}>Sign off</button>
            </>
          )}
        </div>
      )}
      {formError && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{formError}</p>}
    </div>
  );
}

const sum = (runs, key) => runs.reduce((total, r) => total + (r[key] || 0), 0);

/** Latest run per source: summary boxes for the sources shown (added up for "All sources") and each one's sign-off. */
function RunPanel({ source }) {
  const { status, data, error, reload } = useAsync(() => Promise.all(SOURCE_KEYS.map((key) => api.reconRun(key))), []);
  if (status === "loading") return <Loading what="the latest runs" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const runs = data.filter((r) => r.run_date && (!source || r.source_system === source));
  if (!runs.length) {
    return <p className="mt-4 text-sm text-ink2">No comparison with {source ? systemOf(source).long : "any source system"} has run yet.</p>;
  }
  const hint = runs.length === 1 ? `Run of ${runs[0].run_date}` : `Latest run of ${runs.length} sources`;
  return (
    <>
      <ul className="mt-6 grid grid-cols-2 gap-5 lg:grid-cols-4" aria-label="Latest run">
        <StatBox label="Breaks in the latest run" value={sum(runs, "breaks_seen")} hint={hint} />
        <StatBox label="Cleared automatically" value={sum(runs, "auto_cleared")} hint="Formatting only" />
        <StatBox label="Open groups" value={sum(runs, "groups_open")} hint="One task each, in Tasks" status={sum(runs, "groups_open") ? "watch" : "good"} />
        <StatBox label="Important, open" value={sum(runs, "important_open")} hint={`${sum(runs, "recurring_open")} recurring break(s) open`} status={sum(runs, "important_open") ? "action" : "good"} />
      </ul>
      <div className="mt-4 grid gap-3">
        {runs.map((run) => <SignOff key={run.source_system} run={run} reload={reload} />)}
      </div>
    </>
  );
}

function groupCause(g) {
  return `${g.entity_type} ${g.field_name || ""} ${g.pattern}`.replace(/\s+/g, " ");
}

/** Read-only look inside one group: its summary and every break in it. Decisions stay in the group's task. */
function GroupDetail({ groupId, systemLabel, onClose }) {
  const { status, data, error, reload } = useAsync(() => api.reconGroup(groupId), [groupId]);
  return (
    <Modal title={`Group #${groupId}`} onClose={onClose}>
      {status === "loading" && <Loading what="the group" />}
      {status === "error" && !data && <LoadError error={error} onRetry={reload} />}
      {data && (
        <>
          <h3 className="text-sm font-semibold tracking-tight text-ink">{groupCause(data)}</h3>
          <dl className="card mt-4 grid grid-cols-2 gap-x-6 gap-y-1.5 rounded-xl border border-hair bg-surface p-4 text-sm sm:grid-cols-3">
            <div><dt className="text-ink2">Breaks</dt><dd className="font-medium text-ink">{data.break_count}</dd></div>
            <div><dt className="text-ink2">Total difference</dt><dd className="font-medium text-ink">{data.total_difference == null ? "—" : fmtAmount(data.total_difference)}</dd></div>
            <div><dt className="text-ink2">Kind</dt><dd className="font-medium text-ink">{data.important ? "Important, on its own" : data.requires_second_approval ? "Bulk, needs second approval" : "Bulk"}</dd></div>
            <div><dt className="text-ink2">Team</dt><dd className="font-medium text-ink">{data.team || "—"}</dd></div>
            <div><dt className="text-ink2">Due</dt><dd className="font-medium text-ink">{data.due_date || "—"}</dd></div>
            <div><dt className="text-ink2">Status</dt><dd className="font-medium text-ink">{data.status === "CLOSED" ? `Decided: ${data.decision?.toLowerCase()}` : "Open"}</dd></div>
          </dl>
          <div className="mt-4">
            <DataTable
              caption="Breaks in this group"
              columns={[
                { key: "entity", header: "Record", render: (r) => `${r.entity_type} ${r.entity_id}` },
                { key: "field_name", header: "Field", render: (r) => r.field_name || "(whole record)" },
                { key: "source_value", header: systemLabel },
                { key: "canonical_value", header: "Ours" },
                { key: "status", header: "Status", render: (r) => STATUS_LABEL[r.status] || r.status },
              ]}
              rows={data.breaks}
              rowKey={(r) => r.exception_id}
              emptyText="No breaks in this group."
            />
          </div>
          {data.status !== "CLOSED" && (
            <p className="mt-3 text-sm text-ink2">
              To decide this group (accept, correct or dismiss, optionally leaving some breaks out), open its task in{" "}
              <Link to="/tasks" className="text-accent underline">Tasks</Link>.
            </p>
          )}
        </>
      )}
    </Modal>
  );
}

function GroupsTable({ source }) {
  const { status, data, error, reload } = useAsync(() => api.reconGroups(), []);
  const [selectedId, setSelectedId] = useState(null);
  if (status === "loading") return <Loading what="the groups" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;
  const groups = data.filter((g) => !source || g.source_system === source);
  return (
    <>
    <DataTable
      caption="Groups of breaks"
      columns={[
        { key: "group_id", header: "Group", render: (g) => `#${g.group_id}` },
        ...(source ? [] : [{ key: "source_system", header: "Source", render: (g) => systemOf(g.source_system).name }]),
        { key: "pattern", header: "Cause", render: groupCause },
        { key: "break_count", header: "Breaks", align: "right" },
        { key: "total_difference", header: "Total difference", align: "right", render: (g) => (g.total_difference == null ? "—" : fmtAmount(g.total_difference)) },
        { key: "important", header: "Kind", render: (g) => (g.important ? "Important, on its own" : g.requires_second_approval ? "Bulk, needs second approval" : "Bulk") },
        { key: "status", header: "Status", render: (g) => (g.status === "CLOSED" ? `Decided: ${g.decision?.toLowerCase()}` : "Open: decide in Tasks") },
        { key: "due_date", header: "Due" },
      ]}
      rows={groups}
      rowKey={(g) => g.group_id}
      rowFlag={(g) => (g.important && g.status !== "CLOSED" ? { kind: "loss", label: "Important" } : null)}
      selectedKey={selectedId}
      onRowClick={(g) => setSelectedId(g.group_id)}
      emptyText="No groups yet: open breaks are grouped when the task bridge next runs."
    />
    {selectedId && (
      <GroupDetail groupId={selectedId} systemLabel={systemOf(groups.find((g) => g.group_id === selectedId)?.source_system).label} onClose={() => setSelectedId(null)} />
    )}
    </>
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
          <button key={v} type="button" onClick={() => setStatus(v)} className={status === v ? "rounded-md bg-accent px-3 py-1.5 text-sm text-on-accent" : BUTTON}>{l}</button>
        ))}
        <input value={note} onChange={(e) => setNote(e.target.value)} placeholder="Note" aria-label="Override note" className={`${INPUT} flex-1`} />
        <button type="button" onClick={submit} className={BUTTON}>Resolve</button>
      </div>
      {error && <p role="alert" className="mt-2 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
    </div>
  );
}

/**
 * "Our data vs the source systems" (specs/reconciliation-groups.md, client point 1; specs/multi-source-
 * reconciliation.md 3a): the latest runs and their sign-offs, the groups (decided in Tasks), and every break
 * with filters, age and export. One Source filter - all sources, the core banking system or the CRM
 * (Salesforce) - applies to all three; with all sources the tables gain a Source column. Read-only apart from
 * sign-off and the admin override: decisions happen in the group tasks.
 */
export default function CoreSystemSection({ initialSource = "" }) {
  const [source, setSource] = useState(initialSource);
  const system = source ? SYSTEMS[source] : null;
  const valueLabel = system ? system.label : "Their value";
  const { user } = useAuth() || {};
  const [typeFilter, setTypeFilter] = useState("");
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [recurringOnly, setRecurringOnly] = useState(false);
  const [groupFilter, setGroupFilter] = useState("");
  const [selected, setSelected] = useState(null);
  const { status, data, error, reload } = useAsync(() => api.reconciliationExceptions({ limit: 5000 }), []);

  const shown = (data || []).filter((r) => !source || r.source_system === source);
  const groupIds = [...new Set(shown.map((r) => r.group_id).filter((g) => g != null))].sort((a, b) => a - b);
  const rows = shown
    .filter((r) => (!statusFilter || r.status === statusFilter) && (!typeFilter || r.mismatch_type === typeFilter) && (!recurringOnly || r.recurring))
    .filter((r) => !groupFilter || (groupFilter === "none" ? r.group_id == null : String(r.group_id) === groupFilter))
    .map((r) => ({ ...r, age: ageDays(r.first_seen || r.detected_at) }));

  const exportColumns = [
    ["source_system", "Source"], ["entity_type", "Record type"], ["entity_id", "Record"], ["field_name", "Field"], ["mismatch_type", "Type"],
    ["source_value", valueLabel], ["canonical_value", "Ours"], ["status", "Status"], ["resolved_rule", "Cleared by rule"],
    ["group_id", "Group"], ["first_seen", "First seen"], ["last_seen", "Last seen"], ["times_seen", "Times seen"], ["recurring", "Recurring"],
  ];

  return (
    <>
      <div className="mt-6 flex flex-wrap items-center gap-3" role="group" aria-label="Source system">
        <label htmlFor="recon-source" className="text-sm font-medium text-ink">Source</label>
        <select
          id="recon-source"
          value={source}
          onChange={(e) => {
            setSource(e.target.value);
            setGroupFilter("");                            // a group belongs to one source
          }}
          className={INPUT}
        >
          <option value="">All sources</option>
          {SOURCE_KEYS.map((key) => <option key={key} value={key}>{SYSTEMS[key].name}</option>)}
        </select>
        <span className="text-sm text-ink2">Applies to the run summary, the groups and the breaks below.</span>
      </div>

      <RunPanel source={source} />

      <Section id="recon-groups" title="Groups" description="Breaks with the same cause are decided together, as one task in Tasks. Important breaks (missing records, key fields, large amounts) are always on their own.">
        <GroupsTable source={source} />
      </Section>

      <div role="tablist" aria-label="Filter by mismatch type" className="mt-8 flex flex-wrap gap-1 border-b border-hair pb-2.5">
        {TYPE_TABS.map(([value, label]) => (
          <button
            key={value || "all"}
            type="button"
            role="tab"
            aria-selected={typeFilter === value}
            onClick={() => setTypeFilter(value)}
            className={`whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition-all ${typeFilter === value ? "bg-accent font-medium text-on-accent" : "text-ink2 hover:bg-page hover:text-ink"}`}
          >
            {label}
          </button>
        ))}
      </div>

      <Section
        id="recon-exceptions"
        title="All breaks"
        description="Every difference found, with how long it has been open. Click a row for its details."
        action={
          <div className="flex flex-wrap items-center gap-3">
            <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)} aria-label="Status" className={INPUT}>
              <option value="">All statuses</option>
              {Object.entries(STATUS_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
            </select>
            <select value={groupFilter} onChange={(e) => setGroupFilter(e.target.value)} aria-label="Group" className={INPUT}>
              <option value="">All groups</option>
              {groupIds.map((g) => <option key={g} value={String(g)}>Group #{g}</option>)}
              <option value="none">Not in a group</option>
            </select>
            <label className="flex items-center gap-1.5 text-sm text-ink2">
              <input type="checkbox" checked={recurringOnly} onChange={(e) => setRecurringOnly(e.target.checked)} />
              Recurring only
            </label>
            <button type="button" className={BUTTON} disabled={!rows.length} onClick={() => download(`reconciliation-breaks-${source || "all-sources"}.csv`, toCsv(rows, exportColumns))}>Export CSV</button>
          </div>
        }
      >
        {status === "loading" && <Loading what="the breaks" />}
        {status === "error" && !data && <LoadError error={error} onRetry={reload} />}
        {data && (
          <DataTable
            caption="Reconciliation exceptions"
            columns={[
              { key: "group_id", header: "Group", render: (r) => (r.group_id != null ? `#${r.group_id}` : "—") },
              ...(source ? [] : [{ key: "source_system", header: "Source", render: (r) => systemOf(r.source_system).name }]),
              { key: "entity", header: "Record", render: (r) => `${r.entity_type} ${r.entity_id}` },
              { key: "field_name", header: "Field", render: (r) => r.field_name || "(whole record)" },
              { key: "mismatch_type", header: "Type", render: (r) => MISMATCH_LABEL[r.mismatch_type] || r.mismatch_type },
              { key: "source_value", header: valueLabel },
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
            <div><dt className="text-ink2">{systemOf(selected.source_system).label} value</dt><dd className="font-medium text-ink">{selected.source_value ?? "—"}</dd></div>
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
