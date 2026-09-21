import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "../auth";
import { formatDay } from "../kpi/format";
import { THEME_ORDER, getTheme, setTheme } from "../theme";

const BANK_NAME = import.meta.env.VITE_BANK_NAME || "Bank X";

function ThemeToggle() {
  const [theme, setLocal] = useState(getTheme);
  const next = THEME_ORDER[(THEME_ORDER.indexOf(theme) + 1) % THEME_ORDER.length];
  return (
    <button
      type="button"
      onClick={() => {
        setTheme(next);
        setLocal(next);
      }}
      className="rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 hover:bg-page"
      title={`Theme: ${theme}. Click for ${next}.`}
    >
      Theme: {theme}
    </button>
  );
}

/**
 * Top strip: bank name, today's date and "data as of". `dates` (newest first) enables the date selector;
 * pages without a date-scoped view omit it.
 */
export default function TopBar({ asOf, dates, selected, onSelect }) {
  const { user, logout } = useAuth();
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <header className="border-b border-hair bg-surface">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3">
        <div>
          <Link to="/" className="text-lg font-semibold text-ink">
            {BANK_NAME}
          </Link>
          <div className="text-sm text-ink2">
            {today}
            {asOf && <span> · Data as of {formatDay(asOf)}</span>}
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {dates?.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-ink2">
              Date
              <select
                value={selected}
                onChange={(e) => onSelect(e.target.value)}
                className="rounded-md border border-hair bg-surface px-2 py-1.5 text-ink"
              >
                {dates.map((d) => (
                  <option key={d} value={d}>
                    {formatDay(d)}
                  </option>
                ))}
              </select>
            </label>
          )}
          <ThemeToggle />
          {user && (
            <div className="flex items-center gap-2 text-sm text-ink2">
              <span>
                {user.name} <span className="text-muted">({user.role})</span>
              </span>
              <button type="button" onClick={logout} className="rounded-md border border-hair px-2.5 py-1.5 hover:bg-page">
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
