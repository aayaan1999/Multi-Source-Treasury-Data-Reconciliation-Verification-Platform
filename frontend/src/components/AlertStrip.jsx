import { Link } from "react-router-dom";
import { CheckIcon, CrossIcon, WarningIcon } from "./icons";

const TONE = {
  critical: { Icon: CrossIcon, color: "var(--critical)", word: "Action needed" },
  warning: { Icon: WarningIcon, color: "var(--warning)", word: "Watch" },
  good: { Icon: CheckIcon, color: "var(--good)", word: "OK" },
};

export default function AlertStrip({ alerts }) {
  if (alerts.length === 0) return <p className="text-sm text-ink2">No KPI data to assess yet.</p>;
  return (
    <ul className="card divide-y divide-[color:var(--border)] overflow-hidden rounded-xl border border-hair bg-surface">
      {alerts.map(({ key, tone, text, to }) => {
        const { Icon, color, word } = TONE[tone];
        const body = (
          <>
            <span
              className="mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full"
              style={{ background: `color-mix(in srgb, ${color} 14%, transparent)` }}
            >
              <Icon color={color} />
            </span>
            <span className="text-sm text-ink">
              <span className="sr-only">{word}: </span>
              {text}
            </span>
          </>
        );
        return (
          <li key={key} className="border-l-[3px]" style={{ borderColor: color }}>
            {to ? (
              <Link to={to} className="flex items-center gap-3 px-4 py-3 transition-colors hover:bg-page">
                {body}
              </Link>
            ) : (
              <div className="flex items-center gap-3 px-4 py-3">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
