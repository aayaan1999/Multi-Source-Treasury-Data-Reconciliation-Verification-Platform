import { useState } from "react";

/** Colour key for a chart. Always shown for two or more series (colour is never the only way to tell them apart). */
export function Legend({ items }) {
  if (items.length < 2) return null;
  return (
    <ul className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-ink2" aria-label="Legend">
      {items.map((i) => (
        <li key={i.label} className="inline-flex items-center gap-1.5">
          <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: i.color }} />
          {i.label}
        </li>
      ))}
    </ul>
  );
}

/**
 * Card around a chart: title, legend, and a "Show as table" toggle. Every chart has a table twin, so every value is
 * readable without hovering and without relying on colour.
 *   table : the table view, as a React node
 */
export default function ChartCard({ title, subtitle, legend = [], table, note, children }) {
  const [asTable, setAsTable] = useState(false);
  return (
    <li className="card rounded-xl border border-hair bg-surface p-4 transition-shadow hover:shadow-[var(--shadow-hover)]">
      <div className="flex items-start justify-between gap-2">
        <div>
          <h3 className="text-sm font-semibold text-ink">{title}</h3>
          {subtitle && <p className="text-xs text-ink2">{subtitle}</p>}
        </div>
        {table && (
          <button
            type="button"
            aria-pressed={asTable}
            onClick={() => setAsTable((v) => !v)}
            className="shrink-0 rounded-md border border-hair px-2 py-1 text-xs text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink"
          >
            {asTable ? "Show chart" : "Show as table"}
          </button>
        )}
      </div>
      <div className="mt-2">
        <Legend items={legend} />
      </div>
      <div className="mt-2">{asTable && table ? table : children}</div>
      {note && <p className="mt-2 text-xs text-ink2">{note}</p>}
    </li>
  );
}
