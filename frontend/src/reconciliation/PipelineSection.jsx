import { useState } from "react";
import { api } from "../api";
import DataTable from "../components/DataTable";
import Modal from "../components/Modal";
import { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { currencyLines, fmtAmount, gapSummary } from "./pipeline";

function fmtDateTime(iso) {
  return iso ? new Date(iso).toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—";
}

/** Popup for one item: the amount per currency, then the records that were dropped and why. */
function ItemDetail({ item }) {
  const { status, data, error, reload } = useAsync(() => api.pipelineRecords(item.recon_id), [item.recon_id]);
  const lines = currencyLines(item.amounts_by_currency);

  return (
    <>
      <h3 className="text-sm font-semibold tracking-tight text-ink">
        {item.source_system} · {item.source_country} · {item.source_table}
      </h3>
      <p className="mt-0.5 text-sm text-ink2">
        {item.received_rows} rows received, {item.clean_rows} kept, {item.rejected_rows} rejected · run {item.ingest_batch_id}
      </p>

      {lines.length > 0 && (
        <>
          <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Amount ({item.amount_column}) per currency</h3>
          <DataTable
            caption="Amount per currency"
            columns={[
              { key: "currency", header: "Currency" },
              { key: "received", header: "Received", align: "right", render: (l) => fmtAmount(l.received) },
              { key: "clean", header: "Kept", align: "right", render: (l) => fmtAmount(l.clean) },
              { key: "gap", header: "Gap", align: "right", render: (l) => fmtAmount(l.gap) },
            ]}
            rows={lines}
            rowKey={(l) => l.currency}
            rowFlag={(l) => (Math.abs(l.gap) > 0.005 ? { kind: "watch", label: "Gap" } : null)}
          />
          {item.unreadable_amount_rows > 0 && (
            <p className="mt-2 text-sm text-ink2">
              {item.unreadable_amount_rows} row(s) had no readable amount, so they count as rows but add nothing to the amounts.
            </p>
          )}
        </>
      )}

      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Rejected records</h3>
      {status === "loading" && <Loading what="the rejected records" />}
      {status === "error" && !data && <LoadError error={error} onRetry={reload} />}
      {data && !data.records_available && (
        <p className="card rounded-xl border border-hair bg-surface p-4 text-sm text-ink2">
          This item is from an older run. Record-level detail is kept for the latest run only; the counts above still stand.
        </p>
      )}
      {data && data.records_available && (
        <DataTable
          caption="Rejected records"
          columns={[
            { key: "record_key", header: "Record" },
            { key: "flag_label", header: "Check" },
            { key: "description", header: "Why it was rejected" },
          ]}
          rows={data.records}
          rowKey={(r) => `${r.record_key}:${r.flag_label}`}
          emptyText="Nothing was rejected: every row this source sent was kept."
        />
      )}
    </>
  );
}

/**
 * "Received vs kept, per source" (FLOW-3): for each source's latest run, what it sent against what
 * survived cleaning, per country and table. Read-only here; acting on an item comes with the CFO
 * workflow (FLOW-5). Loads on its own, so the core-system comparison below still works if this fails.
 */
export default function PipelineSection() {
  const [country, setCountry] = useState("");
  const [gapsOnly, setGapsOnly] = useState(true);
  const [selected, setSelected] = useState(null);
  const { status, data, error, reload } = useAsync(() => api.pipelineReconciliation(), []);

  if (status === "loading") return <Loading what="source deliveries" />;
  if (status === "error" && !data) return <LoadError error={error} onRetry={reload} />;

  const countries = [...new Set(data.map((r) => r.source_country))].sort();
  const rows = data.filter((r) => (!country || r.source_country === country) && (!gapsOnly || r.has_gap));
  const gapCount = data.filter((r) => r.has_gap).length;
  const rejected = data.reduce((n, r) => n + r.rejected_rows, 0);
  const sources = new Set(data.map((r) => r.source_system)).size;

  return (
    <>
      <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-3" aria-label="Received vs kept summary">
        <StatBox label="Items with a gap" value={gapCount} status={gapCount > 0 ? "action" : "good"} hint="Latest run of each source" />
        <StatBox label="Rows rejected" value={rejected.toLocaleString("en-US")} hint="Received but not kept" />
        <StatBox label="Sources delivered" value={sources} />
      </ul>

      <Section
        id="pipeline"
        title="Received vs kept, per source"
        description="What each source sent against what survived our checks, by country and table. Click an item to see the amounts per currency and the records that were dropped."
        action={
          <div className="flex flex-wrap items-center gap-3">
            <select
              value={country}
              onChange={(e) => setCountry(e.target.value)}
              aria-label="Country"
              className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40"
            >
              <option value="">All countries</option>
              {countries.map((c) => <option key={c} value={c}>{c}</option>)}
            </select>
            <label className="flex items-center gap-1.5 text-sm text-ink2">
              <input type="checkbox" checked={gapsOnly} onChange={(e) => setGapsOnly(e.target.checked)} />
              Gaps only
            </label>
          </div>
        }
      >
        <DataTable
          caption="Received vs kept, per source"
          columns={[
            { key: "source_system", header: "Source" },
            { key: "source_country", header: "Country" },
            { key: "source_table", header: "Table" },
            { key: "received_rows", header: "Received", align: "right" },
            { key: "clean_rows", header: "Kept", align: "right" },
            { key: "rejected_rows", header: "Rejected", align: "right" },
            { key: "amount_gap", header: "Amount gap", render: (r) => gapSummary(r.amounts_by_currency) },
            { key: "detected_at", header: "Run", render: (r) => fmtDateTime(r.detected_at) },
          ]}
          rows={rows}
          rowKey={(r) => r.recon_id}
          rowFlag={(r) => (r.has_gap ? { kind: "watch", label: "Gap" } : null)}
          selectedKey={selected?.recon_id}
          onRowClick={setSelected}
          emptyText={gapsOnly ? "No gaps: every source's latest delivery was kept in full." : "No deliveries recorded yet."}
        />
      </Section>

      {selected && (
        <Modal title="Received vs kept" onClose={() => setSelected(null)}>
          <ItemDetail item={selected} />
        </Modal>
      )}
    </>
  );
}
