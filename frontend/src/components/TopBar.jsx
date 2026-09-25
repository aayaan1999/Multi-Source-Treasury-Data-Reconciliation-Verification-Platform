import { useState } from "react";
import { Link, NavLink } from "react-router-dom";
import { useAuth } from "../auth";
import { formatDay } from "../kpi/format";
import { THEME_ORDER, getTheme, setTheme } from "../theme";
import appbayLogo from "../assets/appbay-logo.jpg";

const NAV = [
  ["/", "Executive summary", true],
  ["/portfolio", "Portfolio & credit risk"],
  ["/performance", "Branch & segment"],
  ["/scenario", "Scenario modelling"],
  ["/reports", "Regulatory reporting"],
  ["/reconciliation", "Reconciliation"],
  ["/tasks", "Tasks"],
  ["/audit-oversight", "Audit & Oversight"],
];

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
      className="rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink"
      title={`Theme: ${theme}. Click for ${next}.`}
    >
      Theme: {theme}
    </button>
  );
}

function initials(name) {
  return (name || "")
    .split(" ")
    .filter(Boolean)
    .slice(0, 2)
    .map((s) => s[0]?.toUpperCase())
    .join("");
}

/**
 * Top strip: bank name, today's date and "data as of". `dates` (newest first) enables the date selector;
 * pages without a date-scoped view omit it.
 */
export default function TopBar({ asOf, dates, selected, onSelect }) {
  const { user, logout } = useAuth();
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <header className="brand-header sticky top-0 z-20 border-b border-hair">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-4">
          {/* The company that built the platform, on the charcoal header band its logo was made for. */}
          <img src={appbayLogo} alt="AppBay" className="h-10 w-auto shrink-0" />
          <span aria-hidden className="h-9 w-px bg-hair" />
          <div>
            <Link to="/" className="text-lg font-semibold leading-tight tracking-tight text-ink">
              {BANK_NAME}
            </Link>
            <div className="text-sm text-ink2">
              {today}
              {asOf && <span> · Data as of {formatDay(asOf)}</span>}
            </div>
          </div>
        </div>

        <div className="flex flex-wrap items-center gap-3">
          {dates?.length > 0 && (
            <label className="flex items-center gap-2 text-sm text-ink2">
              Date
              <select
                value={selected}
                onChange={(e) => onSelect(e.target.value)}
                className="rounded-md border border-hair bg-surface px-2 py-1.5 text-ink transition-colors hover:border-accent/40"
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
            <div className="flex items-center gap-2.5 border-l border-hair pl-3 text-sm text-ink2">
              <span
                aria-hidden
                className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full text-xs font-semibold text-on-accent"
                style={{ background: "var(--series-1)" }}
              >
                {initials(user.name) || "?"}
              </span>
              <span className="hidden sm:inline">
                {user.name} <span className="text-muted">({user.role})</span>
              </span>
              <button type="button" onClick={logout} className="rounded-md border border-hair px-2.5 py-1.5 transition-colors hover:border-accent/40 hover:bg-page">
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
      <nav aria-label="Screens" className="mx-auto flex max-w-7xl gap-1 overflow-x-auto px-4 pb-2.5">
        {NAV.map(([to, label, end]) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              `whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition-all ${
                isActive
                  ? "bg-accent font-medium text-on-accent shadow-[0_4px_12px_-2px_var(--series-1-soft)]"
                  : "text-ink2 hover:bg-page hover:text-ink"
              }`
            }
          >
            {label}
          </NavLink>
        ))}
      </nav>
    </header>
  );
}
