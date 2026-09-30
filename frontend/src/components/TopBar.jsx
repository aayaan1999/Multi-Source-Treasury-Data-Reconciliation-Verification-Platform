import { useEffect, useRef, useState } from "react";
import { Link, NavLink, useLocation } from "react-router-dom";
import { canSee, roleTitle } from "../access";
import { useAuth } from "../auth";
import { usePageRefresh } from "../pageRefresh";
import { formatDay } from "../kpi/format";
import { THEME_ORDER, getTheme, setTheme } from "../theme";
import appbayLogo from "../assets/appbay-logo.jpg";

// A `group` entry is one menu button whose screens open from a dropdown - it keeps the tab row on one
// line instead of scrolling sideways (manager review, 2026-09-29).
const NAV = [
  ["/ingestion", "Data ingestion"],
  ["/", "Executive summary", true],
  ["/portfolio", "Portfolio & credit risk"],
  {
    group: "Analysis & reporting",
    items: [
      ["/performance", "Branch & segment"],
      ["/scenario", "Scenario modelling"],
      ["/reports", "Regulatory reporting"],
    ],
  },
  ["/reconciliation", "Reconciliation"],
  ["/tasks", "Tasks"],
  ["/audit-oversight", "Audit & Oversight"],
  ["/ask", "AI assistant"],
];

const BANK_NAME = import.meta.env.VITE_BANK_NAME || "Bank Data Platform";

/** The menu for this person: only the screens they use (specs/user-roles.md). A group left with one
 * screen becomes a plain tab; an empty group disappears. */
export function navFor(user) {
  return NAV.flatMap((entry) => {
    if (!entry.group) return canSee(user, entry[0]) ? [entry] : [];
    const items = entry.items.filter(([path]) => canSee(user, path));
    if (!items.length) return [];
    return items.length === 1 ? [items[0]] : [{ ...entry, items }];
  });
}

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

const TAB = "whitespace-nowrap rounded-full px-3.5 py-1.5 text-sm transition-all";
const TAB_ACTIVE = "bg-accent font-medium text-on-accent shadow-[0_4px_12px_-2px_var(--series-1-soft)]";
const TAB_IDLE = "text-ink2 hover:bg-page hover:text-ink";

/** A menu button whose screens open from a dropdown; highlighted while one of them is open. */
function NavGroup({ label, items }) {
  const refresh = usePageRefresh();
  const [open, setOpen] = useState(false);
  const box = useRef(null);
  const menu = useRef(null);
  const { pathname } = useLocation();
  const active = items.some(([to]) => pathname === to || pathname.startsWith(`${to}/`));

  useEffect(() => setOpen(false), [pathname]);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (e) => !box.current?.contains(e.target) && setOpen(false);
    const escape = (e) => {
      if (e.key === "Escape") {
        setOpen(false);
        box.current?.querySelector("button")?.focus();
      }
    };
    document.addEventListener("mousedown", outside);
    document.addEventListener("keydown", escape);
    return () => {
      document.removeEventListener("mousedown", outside);
      document.removeEventListener("keydown", escape);
    };
  }, [open]);

  // Arrow keys move between the screens in the open menu.
  function onMenuKey(e) {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const links = [...(menu.current?.querySelectorAll("a") || [])];
    const at = links.indexOf(document.activeElement);
    links[(at + (e.key === "ArrowDown" ? 1 : links.length - 1)) % links.length]?.focus();
  }

  return (
    <div ref={box} className="relative">
      <button
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setOpen(true);
            setTimeout(() => menu.current?.querySelector("a")?.focus());
          }
        }}
        className={`${TAB} inline-flex items-center gap-1.5 ${active ? TAB_ACTIVE : TAB_IDLE}`}
      >
        {label}
        <svg aria-hidden viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.8" className={`transition-transform ${open ? "rotate-180" : ""}`}>
          <path d="M2.5 4.5L6 8l3.5-3.5" />
        </svg>
      </button>
      {open && (
        <div ref={menu} role="menu" aria-label={label} onKeyDown={onMenuKey}
          className="absolute left-0 top-full z-30 mt-1.5 min-w-[13rem] rounded-xl border border-hair bg-surface p-1.5 shadow-[var(--shadow-hover)]">
          {items.map(([to, text]) => (
            <NavLink
              key={to}
              to={to}
              role="menuitem"
              onClick={refresh}
              className={({ isActive }) =>
                `block rounded-lg px-3 py-2 text-sm transition-colors ${isActive ? "bg-accent font-medium text-on-accent" : "text-ink2 hover:bg-page hover:text-ink"}`
              }
            >
              {text}
            </NavLink>
          ))}
        </div>
      )}
    </div>
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
  const refresh = usePageRefresh();
  const today = new Date().toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" });

  return (
    <header className="brand-header sticky top-0 z-20 border-b border-hair">
      <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-x-6 gap-y-3 px-4 py-3">
        <div className="flex items-center gap-4">
          {/* The company that built the platform, on the charcoal header band its logo was made for. */}
          <img src={appbayLogo} alt="AppBay" className="h-10 w-auto shrink-0" />
          <span aria-hidden className="h-9 w-px bg-hair" />
          <div>
            <Link to="/" onClick={refresh} className="text-lg font-semibold leading-tight tracking-tight text-ink">
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
                <span title={user.name}>{roleTitle(user)}</span>
              </span>
              <button type="button" onClick={logout} className="rounded-md border border-hair px-2.5 py-1.5 transition-colors hover:border-accent/40 hover:bg-page">
                Sign out
              </button>
            </div>
          )}
        </div>
      </div>
      {/* Wraps onto a second line on narrow screens rather than scrolling sideways (the dropdown can't
          sit inside a scrolling box - it would be clipped). */}
      <nav aria-label="Screens" className="mx-auto flex max-w-7xl flex-wrap gap-1 px-4 pb-2.5">
        {navFor(user).map((entry) =>
          entry.group ? (
            <NavGroup key={entry.group} label={entry.group} items={entry.items} />
          ) : (
            <NavLink key={entry[0]} to={entry[0]} end={entry[2]} onClick={refresh} className={({ isActive }) => `${TAB} ${isActive ? TAB_ACTIVE : TAB_IDLE}`}>
              {entry[1]}
            </NavLink>
          ),
        )}
      </nav>
    </header>
  );
}
