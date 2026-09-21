import { useId, useState } from "react";
import { Link } from "react-router-dom";
import { formatDayShort, formatValue } from "../kpi/format";
import { computeDelta, statusOf, STATUS_META } from "../kpi/status";
import { ArrowIcon, CheckIcon, CrossIcon, DashIcon, InfoIcon, WarningIcon } from "./icons";

const STATUS_ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, none: DashIcon, unknown: DashIcon };
const TONE_COLOR = { good: "var(--good)", bad: "var(--critical)", neutral: "var(--muted)" };

// The 3 placeholder-assumption KPIs must be visibly different from the directly computed ones
// (specs/screen-01-executive-summary.md section 3): a labelled marker that opens the specific assumption.
function AssumptionMarker({ assumptions }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return (
    <span className="relative z-10 shrink-0">
      <button
        type="button"
        aria-describedby={open ? id : undefined}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        onKeyDown={(e) => e.key === "Escape" && setOpen(false)}
        className="inline-flex items-center gap-1 rounded-full border border-hair px-2 py-0.5 text-xs text-ink2 hover:bg-page"
      >
        <InfoIcon />
        Assumption
      </button>
      {open && (
        <span
          id={id}
          role="tooltip"
          className="absolute right-0 top-full z-20 mt-1 w-64 rounded-lg border border-hair bg-surface p-3 text-left text-xs leading-relaxed text-ink shadow-lg"
        >
          <strong className="block text-ink">Based on a demo assumption</strong>
          <ul className="mt-1 list-disc pl-4 text-ink2">
            {assumptions.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
          <span className="mt-1 block text-ink2">A placeholder pending confirmation — not verified accounting.</span>
        </span>
      )}
    </span>
  );
}

export default function KpiTile({ kpi, value, previous, previousDate, assumptions = [] }) {
  const status = statusOf(kpi, value);
  const meta = STATUS_META[status];
  const StatusIcon = STATUS_ICON[status];
  const delta = computeDelta(kpi, value, previous);

  return (
    <li className="relative flex min-h-[10.5rem] flex-col rounded-xl border border-hair bg-surface p-4 pb-5 transition-colors focus-within:border-accent hover:border-accent">
      <div className="flex items-start justify-between gap-2">
        {/* The label is the tile's link; its ::after stretches over the whole tile so the tile is one big click target. */}
        <Link
          to={kpi.drill}
          title={kpi.hint}
          className="text-sm font-medium text-ink2 after:absolute after:inset-0 after:content-[''] focus-visible:after:rounded-xl focus-visible:after:outline-2 focus-visible:after:outline-accent"
        >
          {kpi.label}
        </Link>
        {assumptions.length > 0 && <AssumptionMarker assumptions={assumptions} />}
      </div>

      <div className="mt-3 text-4xl font-semibold tracking-tight text-ink">{formatValue(kpi, value)}</div>

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

      <div className="mt-auto flex items-center gap-1.5 pt-3 text-sm text-ink2">
        <StatusIcon color={meta.color} />
        <span>{meta.label}</span>
      </div>

      {/* Status bar along the bottom; the label above carries the same meaning, so colour is never alone. */}
      <span aria-hidden className="absolute inset-x-0 bottom-0 h-1 rounded-b-xl" style={{ background: meta.color }} />
    </li>
  );
}
