import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import { sentence as limitSentence } from "../kpi/alerts";
import AssumptionBadge from "../components/AssumptionBadge";
import { ArrowIcon, CheckIcon, CrossIcon, DashIcon, WarningIcon } from "../components/icons";
import PageShell, { Loading, LoadError } from "../components/PageShell";
import Section from "../components/Section";
import TrendPanel from "../components/TrendPanel";
import useAsync from "../hooks/useAsync";
import { formatDay, formatValue, isNum } from "../kpi/format";
import { KPI_BY_KEY } from "../kpi/kpiConfig";
import { computeDelta, statusOf, STATUS_META } from "../kpi/status";
import { suggestionFor } from "../kpi/suggestions";

const STATUS_ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, none: DashIcon, unknown: DashIcon };
const TONE_COLOR = { good: "var(--good)", bad: "var(--critical)", neutral: "var(--muted)" };

// Every clause here is filled in from real numbers already on hand (delta, dates, the KPI's own
// direction) - a template, not a generated summary.
function trendElaboration(kpi, current, previous, currentDate, previousDate) {
  if (!isNum(previous)) {
    return `Only one calculation date is loaded so far (${formatDay(currentDate)}) - a trend needs at least two.`;
  }
  const delta = computeDelta(kpi, current, previous);
  if (!delta || delta.direction === "flat") {
    return `Unchanged since ${formatDay(previousDate)}: ${formatValue(kpi, previous)} both times.`;
  }
  const better = kpi.direction === "higher" ? "better when higher" : "better when lower";
  return (
    `Moved from ${formatValue(kpi, previous)} on ${formatDay(previousDate)} to ${formatValue(kpi, current)} on ` +
    `${formatDay(currentDate)} — a change of ${delta.text}, which is ${delta.tone === "good" ? "an improvement" : "a decline"} ` +
    `since this ratio is ${better}.`
  );
}

/**
 * Where a KPI tile (or an alert-strip line) sends you now, instead of a different screen entirely:
 * this KPI's own number, broken down into the real source-table amounts that produced it, using the
 * exact formula notebooks/03_kpi_summary.py uses (backend/app/routers/kpi.py's /breakdown endpoint) -
 * plain arithmetic made visible, not an AI-written explanation.
 */
export default function KpiDetail() {
  const { key } = useParams();
  const kpi = KPI_BY_KEY[key];
  const { status, data, error, reload } = useAsync(
    () => Promise.all([api.kpiBreakdown(key), api.kpiHistory(90)]),
    [key],
  );

  if (!kpi) {
    return (
      <PageShell title="Unknown KPI" eyebrow="KPI detail">
        <p className="mt-6 text-sm text-ink2">
          There's no KPI called "{key}".{" "}
          <Link to="/" className="text-accent underline-offset-2 hover:underline">Back to the Executive summary</Link>.
        </p>
      </PageShell>
    );
  }

  const backLink = (
    <Link to="/" className="rounded-md border border-hair px-3 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink">
      Back to Executive summary
    </Link>
  );

  if (status === "loading") return <PageShell title={kpi.label} eyebrow="KPI detail" actions={backLink}><Loading what="the breakdown" /></PageShell>;
  if (status === "error" && !data) return <PageShell title={kpi.label} eyebrow="KPI detail" actions={backLink}><LoadError error={error} onRetry={reload} /></PageShell>;

  const [breakdown, history] = data;
  const trendData = history.filter((r) => isNum(r[key])).map((r) => ({ date: r.calculation_date, value: r[key] }));
  const delta = computeDelta(kpi, breakdown.value, breakdown.previous_value);
  const kpiStatus = statusOf(kpi, breakdown.value);
  const meta = STATUS_META[kpiStatus];
  const StatusIcon = STATUS_ICON[kpiStatus];

  return (
    <PageShell title={kpi.label} eyebrow="KPI detail" subtitle={kpi.hint} actions={backLink}>
      <div className="mt-6 grid grid-cols-1 gap-5 lg:grid-cols-3">
        <div className="card rounded-xl border border-hair bg-surface p-5 lg:col-span-1">
          <div className="text-4xl font-semibold tracking-tight text-ink tabular-nums">{formatValue(kpi, breakdown.value)}</div>

          <div className="mt-2 flex items-center gap-1.5 text-sm text-ink2">
            {delta ? (
              <>
                <ArrowIcon direction={delta.direction} color={TONE_COLOR[delta.tone]} />
                <span>{delta.text}</span>
                {delta.tone !== "neutral" && <span className="sr-only">({delta.tone === "good" ? "better" : "worse"})</span>}
                <span className="text-muted">vs {formatDay(breakdown.previous_calculation_date)}</span>
              </>
            ) : (
              <span className="text-muted">No earlier period yet</span>
            )}
          </div>

          <div className="mt-4">
            <span
              className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
              style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}
            >
              <StatusIcon color={meta.color} />
              {meta.label}
            </span>
          </div>

          {breakdown.assumptions_applied.length > 0 && (
            <div className="mt-4">
              <AssumptionBadge items={breakdown.assumptions_applied} align="left" />
            </div>
          )}
        </div>

        <div className="card rounded-xl border border-hair bg-surface p-5 lg:col-span-2">
          <h2 className="text-sm font-medium text-ink2">Formula</h2>
          <p className="mt-1 text-sm text-ink">{breakdown.formula}</p>

          {breakdown.mismatch_note && (
            <p className="mt-3 rounded-md border border-hair bg-page px-3 py-2 text-sm" style={{ color: "var(--warning)" }}>
              {breakdown.mismatch_note}
            </p>
          )}

          <h2 className="mt-5 text-sm font-medium text-ink2">What it's made of, as of {formatDay(breakdown.calculation_date)}</h2>
          <dl className="mt-2 divide-y divide-hair">
            {breakdown.components.map((c) => (
              <div key={c.label} className="flex items-center justify-between gap-4 py-2 text-sm">
                <dt className="text-ink2">{c.label}</dt>
                <dd className="font-medium tabular-nums text-ink">{c.formatted}</dd>
              </div>
            ))}
          </dl>

          {breakdown.fx_notes.length > 0 && (
            <ul className="mt-3 space-y-0.5 text-xs text-muted">
              {breakdown.fx_notes.map((n) => <li key={n}>{n}</li>)}
            </ul>
          )}
        </div>
      </div>

      <Section id="trend-data" title="Trend & data" description="What actually moved, in plain terms - every sentence here comes from the numbers above, not a generated summary.">
        <div className="card rounded-xl border border-hair bg-surface p-5">
          <p className="text-sm text-ink">
            {trendElaboration(kpi, breakdown.value, breakdown.previous_value, breakdown.calculation_date, breakdown.previous_calculation_date)}
          </p>
          {kpiStatus !== "none" && kpiStatus !== "unknown" && (
            <p className="mt-2 text-sm text-ink">{limitSentence(kpi, breakdown.value, kpiStatus)}.</p>
          )}

          {breakdown.history_series.length > 1 && (
            <>
              <h3 className="mt-4 text-sm font-medium text-ink2">Every data point behind this ratio</h3>
              <dl className="mt-2 divide-y divide-hair">
                {breakdown.history_series.map((h) => (
                  <div key={h.label} className="flex items-center justify-between gap-4 py-1.5 text-sm">
                    <dt className="text-ink2">{h.label}</dt>
                    <dd className="font-medium tabular-nums text-ink">{formatValue(kpi, h.value)}</dd>
                  </div>
                ))}
              </dl>
            </>
          )}
        </div>
      </Section>

      <Section id="suggested-actions" title="Suggested actions" description="Read straight off this KPI's own formula - which lever, moved which way, would change the ratio.">
        <div className="card rounded-xl border border-hair bg-surface p-5 text-sm text-ink">
          {kpiStatus === "good" ? (
            <p>Within target - no action needed right now.</p>
          ) : kpiStatus === "none" || kpiStatus === "unknown" ? (
            <p>No target is set for this KPI - it's tracked for trend/scale context, not against a limit.</p>
          ) : (
            <p>{suggestionFor(key, breakdown.components) ?? "No formula-derived suggestion is available for this KPI."}</p>
          )}
        </div>
      </Section>

      {trendData.length > 1 && (
        <Section id="trend" title="Recent trend">
          <ul className="grid grid-cols-1 gap-5">
            <TrendPanel kpi={kpi} data={trendData} />
          </ul>
        </Section>
      )}
    </PageShell>
  );
}
