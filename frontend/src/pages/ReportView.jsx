import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import DataTable from "../components/DataTable";
import { CheckIcon, CrossIcon, WarningIcon } from "../components/icons";
import PageShell, { ExportButton, LoadError, Loading, Notice } from "../components/PageShell";
import Section from "../components/Section";
import useAsync from "../hooks/useAsync";
import { formatChange, formatLine, statusLabel } from "../reports/calendar";

const LEVEL = {
  pass: { Icon: CheckIcon, color: "var(--good)", word: "Passed" },
  warn: { Icon: WarningIcon, color: "var(--warning)", word: "Explanation required" },
  fail: { Icon: CrossIcon, color: "var(--critical)", word: "Blocks submission" },
};
const BOLD_KINDS = new Set(["subtotal", "total"]);

function DemoBadge() {
  return (
    <span className="ml-2 rounded border border-hair px-1.5 py-0.5 text-xs text-ink2" title="No source table holds this figure yet: it is the real total split in the proportions of the source document's worked example.">
      Demo input
    </span>
  );
}

function DrillPanel({ reportId, line, onClose }) {
  const { status, data, error, reload } = useAsync(() => api.drill(reportId, line.line_code), [reportId, line.line_code]);
  return (
    <aside aria-label={`How ${line.line_code} was calculated`} className="card sticky top-24 rounded-xl border border-accent/30 bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-ink2">{line.line_code} · {line.label}</h3>
          <p className="text-2xl font-semibold tracking-tight text-ink tabular-nums">{formatLine(line.unit, line.value)}</p>
        </div>
        <button type="button" onClick={onClose} className="rounded-md border border-hair px-2 py-1 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page">Close</button>
      </div>
      {status === "loading" && <p role="status" className="mt-3 text-sm text-ink2">Loading the calculation…</p>}
      {status === "error" && (
        <p role="alert" className="mt-3 text-sm text-ink">
          <span style={{ color: "var(--critical)" }}>✕ </span>{error.message}{" "}
          <button type="button" onClick={reload} className="underline">Try again</button>
        </p>
      )}
      {status === "ready" && (
        <dl className="mt-3 space-y-3 text-sm">
          {data.is_demo_input && (
            <div role="note" className="rounded-lg border border-hair p-2 text-ink">
              <WarningIcon color="var(--warning)" /> This is a <strong>demo input</strong>: the source data has no such line, so the real total is split in the
              proportions of the source document's example. Replace it once the source system provides the figure.
            </div>
          )}
          <div><dt className="font-medium text-ink2">Formula</dt><dd className="text-ink">{data.formula_text}</dd></div>
          <div><dt className="font-medium text-ink2">Source tables</dt><dd className="text-ink">{[].concat(data.source_tables ?? []).join(", ") || "—"}</dd></div>
          <div><dt className="font-medium text-ink2">Filters applied</dt><dd className="text-ink">{data.filters_applied || "None"}</dd></div>
          <div><dt className="font-medium text-ink2">Records used</dt><dd className="text-ink">{data.record_count ?? "—"}</dd></div>
          <div><dt className="font-medium text-ink2">Calculated at</dt><dd className="text-ink">{data.calculated_at ? new Date(data.calculated_at).toLocaleString() : "—"}</dd></div>
          {data.notes && <div><dt className="font-medium text-ink2">Notes</dt><dd className="text-ink">{data.notes}</dd></div>}
          {data.detail_link && (
            <div><Link to={data.detail_link} className="text-ink underline underline-offset-4">See the loans behind this number →</Link></div>
          )}
        </dl>
      )}
    </aside>
  );
}

function FormSection({ section, selected, onPick }) {
  return (
    <section aria-label={`Section ${section.section}: ${section.title}`} className="mt-4 first:mt-0">
      <h3 className="border-b border-hair pb-1 text-sm font-semibold tracking-wide text-ink2">{section.section}. {section.title}</h3>
      <ul>
        {section.lines.map((l) => {
          const bold = BOLD_KINDS.has(l.line_kind);
          return (
            <li key={l.line_code} className={`flex items-center justify-between gap-3 border-b border-hair py-2 last:border-0 ${bold ? "font-semibold" : ""}`}>
              <span className="text-ink"><span className="mr-2 text-ink2">{l.line_code}</span>{l.label}{l.is_demo_input && <DemoBadge />}</span>
              <button
                type="button"
                onClick={() => onPick(l)}
                aria-pressed={selected === l.line_code}
                aria-label={`${l.line_code} ${l.label}: ${formatLine(l.unit, l.value)}. Show how it was calculated`}
                className={`min-h-[28px] rounded-md px-2 tabular-nums text-ink underline decoration-dotted underline-offset-4 transition-colors hover:bg-page ${selected === l.line_code ? "bg-accent/15 font-medium no-underline" : ""}`}
              >
                {formatLine(l.unit, l.value)}
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

export default function ReportView() {
  const { id } = useParams();
  const { status, data, error, reload } = useAsync(() => api.report(id), [id]);
  const [picked, setPicked] = useState(null);

  if (status === "loading") return <PageShell title="Report"><Loading what="the report" /></PageShell>;
  if (status === "error" && !data) return <PageShell title="Report"><LoadError error={error} onRetry={reload} emptyTitle="Report not found" /></PageShell>;

  const { report } = data;
  const title = `${report.name} · ${report.period}`;
  const back = <Link to="/reports" className="text-sm text-ink underline underline-offset-4">← All reports</Link>;

  if (!data.available) {
    return (
      <PageShell title={title} actions={back}>
        <Notice title="This return hasn't been built yet">Only the Capital Adequacy return is built so far. Its figures will appear here once it is.</Notice>
      </PageShell>
    );
  }

  const exports = (
    <span className="flex flex-wrap items-start gap-2">
      <ExportButton label="Export PDF" onExport={() => api.exportReport(id, "pdf")} />
      <ExportButton label="Export Excel" onExport={() => api.exportReport(id, "excel")} />
    </span>
  );
  const lineByCode = Object.fromEntries(data.sections.flatMap((s) => s.lines).map((l) => [l.line_code, l]));
  const noPrior = data.comparison.every((c) => c.prior === null || c.prior === undefined);

  return (
    <PageShell title={title} eyebrow="Regulatory intelligence" subtitle={`${report.frequency} return · ${statusLabel(report.status)} · due ${report.due_date}`} actions={<div className="flex flex-col items-end gap-2">{back}{exports}</div>}>
      {data.blocked && (
        <div role="alert" className="card mt-4 rounded-xl border p-3 text-sm text-ink" style={{ borderColor: "var(--critical)", background: "color-mix(in srgb, var(--critical) 8%, transparent)" }}>
          <CrossIcon color="var(--critical)" /> <strong>This return cannot be approved or submitted</strong> until the failed checks below are fixed.
        </div>
      )}

      <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,22rem)]">
        <section aria-label="Return" className="card rounded-xl border border-hair bg-surface p-4">
          <p className="mb-3 text-xs text-ink2">Click any figure to see its formula, source tables and record count.</p>
          {data.sections.map((s) => <FormSection key={s.section} section={s} selected={picked?.line_code} onPick={setPicked} />)}
        </section>
        <div>{picked && <DrillPanel reportId={id} line={lineByCode[picked.line_code] ?? picked} onClose={() => setPicked(null)} />}</div>
      </div>

      <Section id="validation" title="Validation checks" description="Run automatically. A red check blocks submission; an amber one needs a written explanation.">
        <ul className="space-y-2">
          {data.validation.map((v) => {
            const m = LEVEL[v.level] ?? LEVEL.warn;
            return (
              <li key={v.rule_key} className="card flex items-start gap-2 rounded-xl border border-hair bg-surface p-3 text-sm">
                <m.Icon color={m.color} />
                <span className="text-ink"><strong>{v.name}</strong> · <span className="text-ink2">{m.word}</span><br />{v.message}</span>
              </li>
            );
          })}
        </ul>
      </Section>

      <Section id="comparison" title="Against the prior period" description={noPrior ? "N/A — no prior period yet. The first return has nothing to compare with." : "Lines that moved more than 10% need an explanation."}>
        <DataTable
          caption="Current against prior period"
          columns={[
            { key: "label", header: "Line", render: (r) => `${r.line_code} ${r.label}` },
            { key: "current", header: "Current", align: "right", render: (r) => formatLine(r.unit, r.current) },
            { key: "prior", header: "Prior", align: "right", render: (r) => (r.prior === null || r.prior === undefined ? "N/A" : formatLine(r.unit, r.prior)) },
            { key: "change", header: "Change", align: "right", render: (r) => formatChange(r) },
          ]}
          rows={data.comparison}
          rowKey={(r) => r.line_code}
          rowFlag={(r) => (r.needs_explanation ? { kind: "watch", label: "Explain" } : null)}
        />
      </Section>
    </PageShell>
  );
}
