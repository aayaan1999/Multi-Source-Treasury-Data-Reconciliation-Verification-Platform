import { useMemo, useState } from "react";
import { api } from "../api";
import { CheckIcon, CrossIcon, DashIcon, WarningIcon } from "../components/icons";
import ChartCard from "../components/ChartCard";
import DataTable from "../components/DataTable";
import PageShell, { LoadError, Loading, Notice } from "../components/PageShell";
import ProjectionChart, { breachSentence } from "../components/ProjectionChart";
import Section from "../components/Section";
import Waterfall, { waterfallRows } from "../components/Waterfall";
import useAsync from "../hooks/useAsync";
import { formatPercentValue, formatUsdCompact } from "../kpi/format";
import { STATUS_META } from "../kpi/status";
import {
  ASSUMPTION_DEFS, NOT_MODELLED, PIPELINE_ASSUMPTIONS, PRESETS, SLIDERS, computeScenario, defaultAssumptions,
  loanBookShare, missingSnapshotFields, ratioStatus, summarise, surplusStatus,
} from "../scenario/engine";

const ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, unknown: DashIcon, none: DashIcon };
const signed = (v, digits, unit) => `${v < 0 ? "−" : "+"}${Math.abs(v).toFixed(digits)}${unit}`;
const signedUsd = (v) => `${v < 0 ? "−" : "+"}${formatUsdCompact(Math.abs(v))}`;

/** One before/after result: the number that matters is the "after", coloured against the regulatory minimum. */
function ResultBox({ label, before, after, change, status, statusWord, footnote }) {
  const meta = STATUS_META[status] ?? STATUS_META.unknown;
  const Icon = ICON[status] ?? DashIcon;
  return (
    <li className="card relative flex flex-col overflow-hidden rounded-xl border border-hair bg-surface p-4 pb-5">
      <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: meta.color }} />
      <span className="text-sm font-medium text-ink2">{label}</span>
      <span className="mt-2 text-3xl font-semibold tracking-tight text-ink tabular-nums" aria-label={`${label} after stress`}>{after}</span>
      <span className="mt-1 text-sm text-ink2">
        {before !== null && <>Before {before} · </>}
        {change}
      </span>
      {footnote && <span className="mt-1 text-xs text-ink2">{footnote}</span>}
      <div className="mt-auto pt-3">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
          style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}
        >
          <Icon color={meta.color} />
          {statusWord ?? meta.label}
        </span>
      </div>
    </li>
  );
}

function Slider({ def, value, onChange }) {
  const id = `slider-${def.key}`;
  const shown = def.step < 1 ? value.toFixed(1) : value;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <label htmlFor={id} className="text-sm font-medium text-ink">{def.label}</label>
        <output htmlFor={id} className="text-lg font-semibold text-ink">{def.min < 0 && value > 0 ? "+" : ""}{shown}{def.unit}</output>
      </div>
      <input
        id={id} type="range" min={def.min} max={def.max} step={def.step} value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        aria-valuetext={`${shown}${def.unit === "%" ? " percent" : ""}`}
        className="mt-2 w-full accent-[var(--series-1)]"
      />
      <div className="flex justify-between text-xs text-muted"><span>{def.min}{def.unit}</span><span>{def.max}{def.unit}</span></div>
      <p className="mt-1 text-xs text-ink2">{def.hint}</p>
    </div>
  );
}

function AssumptionsPanel({ assumptions, defaults, onChange, onReset, snapshot, open }) {
  return (
    <details id="assumptions" open={open} className="card rounded-xl border border-hair bg-surface p-4">
      <summary className="cursor-pointer text-sm font-medium text-ink">
        Assumptions behind this model <span className="text-ink2">({ASSUMPTION_DEFS.length} editable, {PIPELINE_ASSUMPTIONS.length} from the pipeline)</span>
      </summary>
      <p className="mt-2 text-sm text-ink2">
        Every constant the calculation uses is listed here. Change one and every result updates instantly. Nothing is hidden in
        code, and none of these is verified against the bank's own policy: they are working assumptions to confirm.
      </p>
      <ul className="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
        {ASSUMPTION_DEFS.map((d) => (
          <li key={d.key} className="rounded-lg border border-hair p-3">
            <label className="flex flex-wrap items-center justify-between gap-2 text-sm font-medium text-ink" htmlFor={`assume-${d.key}`}>
              {d.label}
              <input
                id={`assume-${d.key}`}
                type={d.type === "text" ? "text" : "number"}
                step={d.step}
                value={assumptions[d.key]}
                onChange={(e) => onChange(d.key, d.type === "text" ? e.target.value.toUpperCase().slice(0, 3) : e.target.value)}
                className="w-24 rounded-md border border-hair bg-surface px-2 py-1 text-right text-sm text-ink"
              />
            </label>
            <p className="mt-1 text-xs text-ink2">{d.why}</p>
            {d.key === "coveragePct" && snapshot && (
              <p className="mt-1 text-xs text-ink2">Default from today's snapshot: {defaults.coveragePct.toFixed(1)}%.</p>
            )}
          </li>
        ))}
      </ul>
      <h3 className="mt-4 text-sm font-medium text-ink">Assumptions already built into the pipeline's snapshot</h3>
      <ul className="mt-2 space-y-2 text-sm">
        {PIPELINE_ASSUMPTIONS.map((a) => (
          <li key={a.label}>
            <strong className="text-ink">{a.label}:</strong> <span className="text-ink">{a.value}</span>
            <p className="text-xs text-ink2">{a.why}</p>
          </li>
        ))}
      </ul>
      <h3 className="mt-4 text-sm font-medium text-ink">Not modelled</h3>
      <ul className="mt-2 list-disc pl-5 text-sm text-ink2">
        {NOT_MODELLED.map((n) => <li key={n}>{n}</li>)}
      </ul>
      <button type="button" onClick={onReset} className="mt-4 rounded-md border border-hair px-3 py-1.5 text-sm text-ink transition-colors hover:border-accent/40 hover:bg-page">
        Reset assumptions to defaults
      </button>
    </details>
  );
}

function ScenarioBody({ snapshot }) {
  const defaults = useMemo(() => defaultAssumptions(snapshot), [snapshot]);
  const [assumptions, setAssumptions] = useState(defaults);
  const [inputs, setInputs] = useState(PRESETS.base.inputs);
  const [name, setName] = useState("");
  const [saveState, setSaveState] = useState({ busy: false, message: "", error: "" });
  const saved = useAsync(() => api.savedScenarios(), []);

  // The whole calculation runs here, in the browser, on every slider move: no backend call.
  const result = useMemo(() => computeScenario(snapshot, inputs, assumptions), [snapshot, inputs, assumptions]);
  const presetRows = useMemo(
    () => Object.entries(PRESETS).map(([key, p]) => ({ key, label: p.label, inputs: p.inputs, ...summarise(computeScenario(snapshot, p.inputs, assumptions)) })),
    [snapshot, assumptions],
  );

  const a = assumptions;
  const { before, after } = result;
  const carStatus = ratioStatus(after.car, a.minimumCarPct, a.carWatchPoints);
  const lcrStatus = ratioStatus(after.lcr, a.minimumLcrPct, a.lcrWatchPoints);
  const surplusState = surplusStatus(after.surplus, after.rwa, a.minimumCarPct, a.surplusWatchPct);
  const share = loanBookShare(snapshot);
  const activePreset = Object.entries(PRESETS).find(([, p]) => Object.keys(p.inputs).every((k) => p.inputs[k] === inputs[k]))?.[0];
  const setAssumption = (key, raw) => {
    const def = ASSUMPTION_DEFS.find((d) => d.key === key);
    if (def.type === "text") return setAssumptions((s) => ({ ...s, [key]: raw }));
    const n = Number(raw);
    if (raw !== "" && Number.isFinite(n)) setAssumptions((s) => ({ ...s, [key]: n }));
  };

  async function save() {
    setSaveState({ busy: true, message: "", error: "" });
    try {
      await api.saveScenario({
        name,
        inputs: { devaluation_pct: inputs.devaluationPct, rate_change_pct: inputs.rateChangePct, npl_increase_pct: inputs.nplIncreasePct, deposit_outflow_pct: inputs.depositOutflowPct },
        assumptions,
        outputs: summarise(result),
      });
      setSaveState({ busy: false, message: `Saved “${name.trim()}”.`, error: "" });
      setName("");
      saved.reload();
    } catch (e) {
      setSaveState({ busy: false, message: "", error: e.message });
    }
  }

  const rows = [
    { key: "current", label: "Current sliders (not saved)", ...summarise(result), inputs, current: true },
    ...presetRows,
    ...(saved.data ?? []).map((s) => ({
      key: `saved-${s.scenario_id}`, label: s.name, saved: true,
      inputs: { devaluationPct: s.inputs.devaluation_pct, rateChangePct: s.inputs.rate_change_pct, nplIncreasePct: s.inputs.npl_increase_pct, depositOutflowPct: s.inputs.deposit_outflow_pct },
      ...s.outputs,
    })),
  ];
  const num = (v, f) => (Number.isFinite(v) ? f(v) : "—");

  return (
    <>
      {share !== null && share < 10 && (
        <div role="note" className="card mt-4 rounded-xl border border-hair bg-surface p-3 text-sm text-ink">
          <WarningIcon color="var(--warning)" /> <strong>Read this first.</strong> The loan book in today's snapshot is {formatUsdCompact(result.detail.grossLoans)},
          only {share.toFixed(2)}% of risk-weighted assets ({formatUsdCompact(before.rwa)}). A stress on loans can therefore barely move the
          capital ratio, whatever the sliders say. The model is working; the sample data behind it is far smaller than the capital it is measured against.
        </div>
      )}

      <div className="mt-5 grid grid-cols-1 gap-6 lg:grid-cols-[minmax(0,21rem)_minmax(0,1fr)]">
        <div>
          <section aria-label="Stress controls" className="card rounded-xl border border-hair bg-surface p-4">
            <h2 className="text-base font-semibold tracking-tight text-ink">Stress controls</h2>
            <div className="mt-3 flex flex-wrap gap-2" role="group" aria-label="Preset scenarios">
              {Object.entries(PRESETS).map(([key, p]) => (
                <button key={key} type="button" aria-pressed={activePreset === key} onClick={() => setInputs(p.inputs)}
                  className={`rounded-full border px-3 py-1.5 text-sm transition-colors ${activePreset === key ? "border-accent bg-accent font-medium text-on-accent shadow-sm" : "border-hair text-ink2 hover:border-accent/40 hover:bg-page hover:text-ink"}`}>
                  {p.label}
                </button>
              ))}
            </div>
            <p className="mt-2 text-xs text-ink2">Preset values are illustrative starting points; confirm the standard scenarios with the regulator or client.</p>
            <div className="mt-4 space-y-5">
              {SLIDERS.map((def) => (
                <Slider key={def.key} def={def} value={inputs[def.key]} onChange={(v) => setInputs((s) => ({ ...s, [def.key]: v }))} />
              ))}
            </div>
          </section>

          <div className="card mt-4 rounded-xl border border-hair bg-surface p-4">
            <label className="text-sm font-medium text-ink" htmlFor="scenario-name">Save this scenario</label>
            <div className="mt-2 flex gap-2">
              <input id="scenario-name" value={name} onChange={(e) => setName(e.target.value)} maxLength={80} placeholder="e.g. Board stress test"
                className="min-w-0 flex-1 rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink outline-none transition focus:border-transparent focus:ring-2 focus:ring-accent/60" />
              <button type="button" onClick={save} disabled={!name.trim() || saveState.busy}
                className="rounded-md bg-accent px-3 py-1.5 text-sm font-medium text-on-accent transition hover:brightness-110 disabled:opacity-50">
                {saveState.busy ? "Saving…" : "Save"}
              </button>
            </div>
            {saveState.message && <p role="status" className="mt-2 text-sm text-ink">{saveState.message}</p>}
            {saveState.error && <p role="alert" className="mt-2 text-sm text-ink"><span style={{ color: "var(--critical)" }}>✕ </span>{saveState.error}</p>}
          </div>
        </div>

        <div>
          {result.hqlaExhausted && (
            <div role="alert" className="card mb-4 rounded-xl border p-3 text-sm text-ink" style={{ borderColor: "var(--critical)", background: "color-mix(in srgb, var(--critical) 8%, transparent)" }}>
              <CrossIcon color="var(--critical)" /> <strong>Liquid assets run out before the outflow is covered.</strong> This is the scenario where a bank fails
              while still technically solvent.
            </div>
          )}
          <ul className="grid grid-cols-1 gap-5 sm:grid-cols-2" aria-label="Results after stress">
            <ResultBox label="Capital ratio" before={formatPercentValue(before.car, 2)} after={formatPercentValue(after.car, 2)}
              change={signed(after.car - before.car, 2, " pts")} status={carStatus} footnote={`Minimum ${a.minimumCarPct}%`} />
            <ResultBox label="Liquidity ratio" before={formatPercentValue(before.lcr, 1)} after={formatPercentValue(after.lcr, 1)}
              change={signed(after.lcr - before.lcr, 1, " pts")} status={lcrStatus} footnote={`Minimum ${a.minimumLcrPct}%`} />
            <ResultBox label="Capital surplus / (shortfall)" before={signedUsd(before.surplus)} after={signedUsd(after.surplus)}
              change={signedUsd(after.surplus - before.surplus)} status={surplusState} statusWord={after.surplus < 0 ? "Shortfall" : undefined}
              footnote={`Capital above ${a.minimumCarPct}% of RWA`} />
            <ResultBox label="Profit impact" before={null} after={signedUsd(after.profitImpact)}
              change={after.profitImpact === 0 ? "No change" : after.profitImpact < 0 ? "Loss" : "Gain"} status="none"
              statusWord="Provisions and interest, before tax" />
          </ul>
        </div>
      </div>

      <Section id="waterfall" title="Which factor hurts most?" description="Today's capital ratio, then the step each stressed factor causes, in the order the model applies them.">
        <ul>
          <ChartCard
            title="Capital ratio waterfall"
            legend={[]}
            note={`Grey = totals · red = the ratio falls · blue = it rises · dashed line = the ${a.minimumCarPct}% minimum. Deposit outflow affects liquidity, not this ratio.`}
            table={
              <DataTable
                caption="Waterfall steps"
                columns={[{ key: "label", header: "Step" }, { key: "text", header: "Capital ratio", align: "right" }, { key: "note", header: "Note", render: (r) => r.note ?? "" }]}
                rows={waterfallRows(before.car, result.steps, after.car)}
                rowKey={(r) => r.name}
              />
            }
          >
            <Waterfall start={before.car} steps={result.steps} end={after.car} minimum={a.minimumCarPct} />
          </ChartCard>
        </ul>
      </Section>

      <Section id="projection" title="12-month projection" description={`The stress phases in evenly over ${a.phaseInMonths} months (an assumption you can change).`}>
        <p role="status" className="mb-2 text-base font-medium text-ink">{breachSentence(result.breachMonth, a.minimumCarPct)}</p>
        <ul>
          <ChartCard
            title="Capital ratio by month under stress"
            note="Dashed line = regulatory minimum. A red dot marks the first month below it."
            table={
              <DataTable
                caption="Projection by month"
                columns={[{ key: "month", header: "Month", render: (p) => (p.month === 0 ? "Now" : `Month ${p.month}`) },
                  { key: "car", header: "Capital ratio", align: "right", render: (p) => formatPercentValue(p.car, 2) }]}
                rows={result.projection}
                rowKey={(p) => String(p.month)}
                rowFlag={(p) => (p.car < a.minimumCarPct ? { kind: "loss", label: "Below minimum" } : null)}
              />
            }
          >
            <ProjectionChart projection={result.projection} minimum={a.minimumCarPct} breachMonth={result.breachMonth} />
          </ChartCard>
        </ul>
      </Section>

      <Section id="compare" title="Scenarios side by side" description="The three standard scenarios always appear. Save your own with the box above and it joins the table.">
        <DataTable
          caption="Scenario comparison"
          columns={[
            { key: "label", header: "Scenario" },
            { key: "dev", header: "Devaluation", align: "right", render: (r) => `${r.inputs.devaluationPct}%` },
            { key: "rate", header: "Rates", align: "right", render: (r) => `${r.inputs.rateChangePct > 0 ? "+" : ""}${r.inputs.rateChangePct}%` },
            { key: "npl", header: "Bad loans", align: "right", render: (r) => `+${r.inputs.nplIncreasePct}%` },
            { key: "out", header: "Outflow", align: "right", render: (r) => `${r.inputs.depositOutflowPct}%` },
            { key: "car", header: "Capital ratio", align: "right", render: (r) => num(r.carAfter, (v) => formatPercentValue(v, 2)) },
            { key: "lcr", header: "Liquidity ratio", align: "right", render: (r) => num(r.lcrAfter, (v) => formatPercentValue(v, 1)) },
            { key: "surplus", header: "Surplus / (shortfall)", align: "right", render: (r) => num(r.surplusAfter, signedUsd) },
            { key: "profit", header: "Profit impact", align: "right", render: (r) => num(r.profitImpact, signedUsd) },
          ]}
          rows={rows}
          rowKey={(r) => r.key}
          rowFlag={(r) => (Number.isFinite(r.surplusAfter) && r.surplusAfter < 0 ? { kind: "loss", label: "Shortfall" } : null)}
          selectedKey="current"
        />
        <p className="mt-2 text-xs text-ink2">
          Saved scenarios show the results as they were when saved. {saved.status === "error" && (
            <span role="alert" className="text-ink"><span style={{ color: "var(--critical)" }}>✕ </span>Saved scenarios couldn't be loaded: {saved.error.message}</span>
          )}
        </p>
      </Section>

      <Section id="assumptions-section" title="Assumptions" description="What is behind the model. Bankers will ask.">
        <AssumptionsPanel
          assumptions={assumptions} defaults={defaults} snapshot={snapshot} open
          onChange={setAssumption} onReset={() => setAssumptions(defaults)}
        />
      </Section>
    </>
  );
}

export default function Scenario() {
  // Fetched exactly once when the screen opens. Slider moves never call the backend again.
  const { status, data, error, reload } = useAsync(() => api.scenarioSnapshot(), []);
  const title = "Scenario modelling";
  const subtitle = "What if? Take today's real position, apply a bad event, and see what breaks. Everything recalculates in your browser as you move a slider.";

  if (status === "loading") return <PageShell title={title}><Loading what="today's position" /></PageShell>;
  if (status === "error" && !data) return <PageShell title={title}><LoadError error={error} onRetry={reload} /></PageShell>;

  const missing = missingSnapshotFields(data);
  if (missing.length) {
    return (
      <PageShell title={title}>
        <Notice title="The snapshot is incomplete">
          The scenario model needs these figures from the latest pipeline run and they are missing: {missing.join(", ")}.
        </Notice>
      </PageShell>
    );
  }
  return (
    <PageShell title={title} eyebrow="Scenario engine" subtitle={subtitle} asOf={data.calculation_date}>
      <ScenarioBody snapshot={data} />
    </PageShell>
  );
}
