import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import PageShell, { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";

function fmtDateTime(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

const MISMATCH_LABEL = {
  VALUE_MISMATCH: "Value mismatch",
  MISSING_IN_CANONICAL: "Missing in our data",
  MISSING_IN_SOURCE: "Missing in source system",
};

/** Approve/Dismiss/Correct one open exception, with a note required for a correction. Rendered
 * inside a Modal popup, matching the Tasks tab's review flow. */
function ResolvePanel({ row, onDone, onClose }) {
  const [status, setStatus] = useState("");
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setError("");
    if (!status) return setError("Pick Accept, Correct or Dismiss.");
    if (status === "CORRECTED" && !note.trim()) return setError("A note is required when correcting a value.");
    setBusy(true);
    try {
      await api.resolveReconciliation(row.exception_id, { status, resolution_note: note || undefined });
      onDone();
    } catch (e) {
      setError(e.message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">
        {row.entity_type} {row.entity_id}{row.field_name ? ` — ${row.field_name}` : ""}
      </h3>
      <p className="mt-0.5 text-sm text-ink2">{MISMATCH_LABEL[row.mismatch_type] || row.mismatch_type}</p>

      <div className="card mb-5 mt-4 rounded-xl border border-hair bg-surface p-4">
        <dl className="grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
          <div><dt className="text-ink2">Source system value</dt><dd className="font-medium text-ink">{row.source_value ?? "—"}</dd></div>
          <div><dt className="text-ink2">Our recorded value</dt><dd className="font-medium text-ink">{row.canonical_value ?? "—"}</dd></div>
          <div><dt className="text-ink2">Detected</dt><dd className="font-medium text-ink">{fmtDateTime(row.detected_at)}</dd></div>
        </dl>
      </div>

      <h3 className="mb-2 text-sm font-medium text-ink2">Action</h3>
      <div className="card rounded-xl border border-hair bg-surface p-4">
        <div className="mb-3 flex flex-wrap gap-2">
          {[["ACCEPTED", "Accept"], ["CORRECTED", "Correct"], ["DISMISSED", "Dismiss"]].map(([value, label]) => (
            <button
              key={value}
              type="button"
              onClick={() => setStatus(value)}
              className={`rounded-md border px-3 py-1.5 text-sm font-medium transition-colors ${
                status === value ? "border-accent bg-accent text-white" : "border-hair text-ink hover:border-accent/40 hover:bg-page"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder={status === "CORRECTED" ? "What's the correct value, and why? (required)" : "Note (optional)"}
          className="mb-3 w-full rounded-md border border-hair bg-surface px-3 py-1.5 text-sm text-ink"
        />
        {error && <p role="alert" className="mb-3 text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
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
            onClick={submit}
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

export default function Reconciliation() {
  const [statusFilter, setStatusFilter] = useState("OPEN");
  const [selected, setSelected] = useState(null);
  const { status, data, error, reload } = useAsync(
    () => Promise.all([api.reconciliationExceptions({ status: statusFilter || undefined }), api.reconciliationSummary()]),
    [statusFilter],
  );

  if (status === "loading") return <PageShell title="Reconciliation"><Loading what="reconciliation exceptions" /></PageShell>;
  if (status === "error" && !data) return <PageShell title="Reconciliation"><LoadError error={error} onRetry={reload} /></PageShell>;

  const [rows, summary] = data;
  const openCount = summary.by_status.find((s) => s.status === "OPEN")?.count ?? 0;
  const resolvedCount = summary.by_status.filter((s) => s.status !== "OPEN").reduce((n, s) => n + s.count, 0);

  return (
    <PageShell
      title="Reconciliation"
      subtitle="Differences found between our own records and the bank's core system feed. Review each one and decide whether to accept it, correct our data, or dismiss it."
    >
      <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Reconciliation summary">
        <StatBox label="Open exceptions" value={openCount} status={openCount > 0 ? "action" : "good"} />
        <StatBox label="Resolved" value={resolvedCount} />
        {summary.by_mismatch_type.slice(0, 2).map((m) => (
          <StatBox key={m.mismatch_type} label={MISMATCH_LABEL[m.mismatch_type] || m.mismatch_type} value={m.count} hint="Open, by type" />
        ))}
      </ul>

      <Section
        id="exceptions"
        title="Exceptions"
        description="Click a row to accept, correct, or dismiss it."
        action={
          <select
            value={statusFilter}
            onChange={(e) => { setStatusFilter(e.target.value); setSelected(null); }}
            className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40"
          >
            <option value="OPEN">Open</option>
            <option value="ACCEPTED">Accepted</option>
            <option value="CORRECTED">Corrected</option>
            <option value="DISMISSED">Dismissed</option>
            <option value="">All</option>
          </select>
        }
      >
        <DataTable
          caption="Reconciliation exceptions"
          columns={[
            { key: "entity", header: "Record", render: (r) => `${r.entity_type} ${r.entity_id}` },
            { key: "field_name", header: "Field", render: (r) => r.field_name || "(whole record)" },
            { key: "mismatch_type", header: "Type", render: (r) => MISMATCH_LABEL[r.mismatch_type] || r.mismatch_type },
            { key: "source_value", header: "Source value" },
            { key: "canonical_value", header: "Canonical value" },
            { key: "detected_at", header: "Detected", render: (r) => fmtDateTime(r.detected_at) },
            { key: "status", header: "Status" },
            { key: "resolved_by_name", header: "Resolved by", render: (r) => r.resolved_by_name || "—" },
          ]}
          rows={rows}
          rowKey={(r) => r.exception_id}
          rowFlag={(r) => (r.status === "OPEN" ? { kind: "watch", label: "Open" } : null)}
          selectedKey={selected?.exception_id}
          onRowClick={(r) => (r.status === "OPEN" ? setSelected(r) : null)}
          emptyText="No exceptions for this filter."
        />
      </Section>

      {selected && (
        <Modal title="Resolve exception" onClose={() => setSelected(null)}>
          <ResolvePanel
            row={selected}
            onClose={() => setSelected(null)}
            onDone={() => {
              setSelected(null);
              reload();
            }}
          />
        </Modal>
      )}
    </PageShell>
  );
}
