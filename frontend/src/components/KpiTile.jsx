import { Link } from "react-router-dom";
import { formatDayShort, formatValue } from "../kpi/format";
import { computeDelta, statusOf, STATUS_META } from "../kpi/status";
import AssumptionBadge from "./AssumptionBadge";
import { ArrowIcon, CheckIcon, CrossIcon, DashIcon, WarningIcon } from "./icons";

const STATUS_ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, none: DashIcon, unknown: DashIcon };
const TONE_COLOR = { good: "var(--good)", bad: "var(--critical)", neutral: "var(--muted)" };

export default function KpiTile({ kpi, value, previous, previousDate, assumptions = [] }) {
  const status = statusOf(kpi, value);
  const meta = STATUS_META[status];
  const StatusIcon = STATUS_ICON[status];
  const delta = computeDelta(kpi, value, previous);

  return (
    <li className="card card-interactive relative flex min-h-[10.5rem] flex-col overflow-hidden rounded-xl border border-hair bg-surface p-4 pb-5 transition-colors focus-within:border-accent hover:border-accent">
      {/* Status bar along the top: a quiet, always-visible signal that doesn't compete with the number. */}
      <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: meta.color }} />

      <div className="flex items-start justify-between gap-2">
        {/* The label is the tile's link; its ::after stretches over the whole tile so the tile is one big click target. */}
        <Link
          to={kpi.drill}
          title={kpi.hint}
          className="text-sm font-medium text-ink2 after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-xl focus-visible:after:outline-2 focus-visible:after:outline-accent"
        >
          {kpi.label}
        </Link>
        {assumptions.length > 0 && <AssumptionBadge items={assumptions} />}
      </div>

      <div className="mt-3 text-4xl font-semibold tracking-tight text-ink tabular-nums">{formatValue(kpi, value)}</div>

      <div className="mt-2 flex items-center gap-1.5 text-sm text-ink2">
        {delta ? (
          <>
            <ArrowIcon direction={delta.direction} color={TONE_COLOR[delta.tone]} />
            <span>{delta.text}</span>
            {delta.tone !== "neutral" && <span className="sr-only">({delta.tone === "good" ? "better" : "worse"})</span>}
            <span className="text-muted">vs {formatDayShort(previousDate)}</span>
          </>
        ) : (
          <span className="text-muted">No earlier period yet</span>
        )}
      </div>

      <div className="mt-auto pt-3">
        <span
          className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
          style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}
        >
          <StatusIcon color={meta.color} />
          {meta.label}
        </span>
      </div>
    </li>
  );
}
