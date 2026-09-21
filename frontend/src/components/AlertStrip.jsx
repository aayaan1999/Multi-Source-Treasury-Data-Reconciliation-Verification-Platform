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
    <ul className="divide-y divide-[color:var(--border)] rounded-xl border border-hair bg-surface">
      {alerts.map(({ key, tone, text, to }) => {
        const { Icon, color, word } = TONE[tone];
        const body = (
          <>
            <span className="mt-0.5 shrink-0">
              <Icon color={color} />
            </span>
            <span className="text-sm text-ink">
              <span className="sr-only">{word}: </span>
              {text}
            </span>
          </>
        );
        return (
          <li key={key}>
            {to ? (
              <Link to={to} className="flex gap-3 px-4 py-3 hover:bg-page">
                {body}
              </Link>
            ) : (
              <div className="flex gap-3 px-4 py-3">{body}</div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
