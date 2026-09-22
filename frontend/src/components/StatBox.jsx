import { STATUS_META } from "../kpi/status";
import { CheckIcon, CrossIcon, DashIcon, WarningIcon } from "./icons";

const ICON = { good: CheckIcon, watch: WarningIcon, action: CrossIcon, none: DashIcon, unknown: DashIcon };

/**
 * A summary figure for a top strip: label, big value, an explanatory line, and (optionally) a status. The status is a
 * bar along the bottom AND an icon + word, so colour never carries the meaning alone.
 */
export default function StatBox({ label, value, hint, status, badge }) {
  const meta = status ? STATUS_META[status] : null;
  const Icon = status ? ICON[status] : null;
  return (
    <li className="card relative flex min-h-[8rem] flex-col overflow-hidden rounded-xl border border-hair bg-surface p-4 pb-5">
      {meta && <span aria-hidden className="absolute inset-x-0 top-0 h-1" style={{ background: meta.color }} />}
      <div className="flex items-start justify-between gap-2">
        <span className="text-sm font-medium text-ink2">{label}</span>
        {badge}
      </div>
      <div className="mt-2 text-3xl font-semibold tracking-tight text-ink tabular-nums">{value}</div>
      {hint && <p className="mt-1 text-sm text-ink2">{hint}</p>}
      {meta && (
        <div className="mt-auto pt-3">
          <span
            className="inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium"
            style={{ background: `color-mix(in srgb, ${meta.color} 14%, transparent)`, color: meta.color }}
          >
            <Icon color={meta.color} />
            {meta.label}
          </span>
        </div>
      )}
    </li>
  );
}
