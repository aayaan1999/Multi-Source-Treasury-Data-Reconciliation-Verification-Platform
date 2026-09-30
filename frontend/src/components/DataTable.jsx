import { useEffect, useState } from "react";
import { CrossIcon, WarningIcon } from "./icons";

const ALIGN = { right: "text-right", left: "text-left", center: "text-center" };
const FLAG_ICON = { loss: CrossIcon, watch: WarningIcon };
const FLAG_COLOR = { loss: "var(--critical)", watch: "var(--warning)" };
const PAGE_SIZE = 10;
const SORT_WORD = { asc: "ascending", desc: "descending" };

/** The value a sortable column sorts on: its `sort(row)`, or the raw field. */
function sortValue(column, row) {
  return typeof column.sort === "function" ? column.sort(row) : row[column.key];
}

/** Compare two cells: empty last whichever way, numbers as numbers, text (and ISO dates) as text. */
export function compareCells(a, b, dir) {
  const empty = (v) => v === null || v === undefined || v === "";
  if (empty(a) || empty(b)) return empty(a) - empty(b);
  const na = typeof a === "number" ? a : Number.NaN;
  const nb = typeof b === "number" ? b : Number.NaN;
  const order = Number.isFinite(na) && Number.isFinite(nb) ? na - nb : String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  return dir === "desc" ? -order : order;
}

/**
 * A plain, accessible table, paginated 10 rows at a time with Prev/Next arrows whenever there's
 * more than one page. Pagination is client-side over whatever `rows` this already received, so
 * every table in the app gets it for free without each page managing its own page state.
 *  columns : [{ key, header, align?, render?(row), headerExtra?, title? }]
 *  rowFlag : (row) => { kind: "loss" | "watch", label } | null   flagged rows get a tinted background AND a word + icon
 *  onRowClick : makes each row a drill-down; the first cell becomes a real button so keyboard users can use it too
 *  selectedKey : highlights the row whose rowKey equals it
 *  Sorting is opt-in per column: `sort: true` sorts on row[key], `sort: (row) => value` on what it returns.
 *  Clicking a sortable header sorts by it (again: the other way round); defaultSort = { key, dir }.
 *  Rows are sorted before paging, so page 1 is always the top of the sorted list.
 */
export default function DataTable({ columns, rows: unsortedRows, rowKey, rowFlag, onRowClick, selectedKey, caption, defaultSort, emptyText = "Nothing to show yet." }) {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState(defaultSort || null);
  const sortColumn = sort && columns.find((c) => c.key === sort.key && c.sort);
  const rows = sortColumn
    ? [...unsortedRows].sort((a, b) => compareCells(sortValue(sortColumn, a), sortValue(sortColumn, b), sort.dir))
    : unsortedRows;
  const pageCount = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  const safePage = Math.min(page, pageCount);

  // A new filter/reload can shrink or entirely replace the row set; land back on page 1 rather
  // than showing an empty page 3 of a now-2-page table. Keyed on length, not the `rows` array
  // itself - several callers pass a freshly-computed array every render (e.g. Portfolio.jsx's
  // chartRows(dimension)), which would otherwise reset the page on every unrelated re-render.
  useEffect(() => {
    setPage(1);
  }, [rows.length]);

  function sortBy(key) {
    setSort((s) => ({ key, dir: s?.key === key && s.dir === "asc" ? "desc" : "asc" }));
    setPage(1);
  }

  if (!rows.length) return <p className="card rounded-xl border border-hair bg-surface p-4 text-sm text-ink2">{emptyText}</p>;

  const start = (safePage - 1) * PAGE_SIZE;
  const pageRows = rows.slice(start, start + PAGE_SIZE);

  return (
    <div className="card overflow-hidden rounded-xl border border-hair bg-surface">
      <div className="overflow-x-auto">
      <table className="w-full text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-hair bg-page/60 text-ink2">
            {columns.map((c) => {
              const active = sort?.key === c.key && c.sort;
              return (
                <th key={c.key} scope="col" title={c.title} aria-sort={c.sort ? (active ? SORT_WORD[sort.dir] : "none") : undefined}
                  className={`px-3 py-2.5 font-medium ${ALIGN[c.align || "left"]}`}>
                  {c.sort ? (
                    <button type="button" onClick={() => sortBy(c.key)}
                      className={`inline-flex items-center gap-1.5 rounded hover:text-ink ${active ? "text-ink" : ""}`}>
                      {c.header}{c.headerExtra}
                      <span aria-hidden className={`text-xs ${active ? "" : "opacity-40"}`}>{active ? (sort.dir === "asc" ? "▲" : "▼") : "↕"}</span>
                    </button>
                  ) : (
                    <span className="inline-flex items-center gap-1.5">{c.header}{c.headerExtra}</span>
                  )}
                </th>
              );
            })}
          </tr>
        </thead>
        <tbody>
          {pageRows.map((row) => {
            const flag = rowFlag?.(row);
            const Icon = flag && FLAG_ICON[flag.kind];
            const id = rowKey(row);
            return (
              <tr
                key={id}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                aria-selected={selectedKey !== undefined ? id === selectedKey : undefined}
                className={`border-b border-hair transition-colors last:border-0 ${onRowClick ? "cursor-pointer hover:bg-page" : ""} ${
                  id === selectedKey ? "bg-page" : ""
                }`}
                style={flag ? { background: `color-mix(in srgb, ${FLAG_COLOR[flag.kind]} 9%, transparent)` } : undefined}
              >
                {columns.map((c, i) => {
                  const content = c.render ? c.render(row) : row[c.key];
                  return (
                    <td key={c.key} className={`px-3 py-2 text-ink ${ALIGN[c.align || "left"]}`}>
                      {i === 0 ? (
                        <span className="inline-flex flex-wrap items-center gap-2">
                          {onRowClick ? (
                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation();
                                onRowClick(row);
                              }}
                              className="text-left underline-offset-2 hover:underline"
                            >
                              {content}
                            </button>
                          ) : (
                            content
                          )}
                          {flag && (
                            <span
                              className="inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium"
                              style={{ background: `color-mix(in srgb, ${FLAG_COLOR[flag.kind]} 14%, transparent)`, color: FLAG_COLOR[flag.kind] }}
                            >
                              <Icon color={FLAG_COLOR[flag.kind]} />
                              {flag.label}
                            </span>
                          )}
                        </span>
                      ) : (
                        content
                      )}
                    </td>
                  );
                })}
              </tr>
            );
          })}
        </tbody>
      </table>
      </div>
      {pageCount > 1 && (
        <div className="flex items-center justify-end gap-3 border-t border-hair px-3 py-2 text-sm text-ink2">
          <span aria-live="polite">
            {start + 1}–{Math.min(start + PAGE_SIZE, rows.length)} of {rows.length}
          </span>
          <span className="inline-flex overflow-hidden rounded-md border border-hair">
            <button
              type="button"
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={safePage === 1}
              aria-label="Previous page"
              className="border-r border-hair px-2.5 py-1 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              ‹
            </button>
            <button
              type="button"
              onClick={() => setPage((p) => Math.min(pageCount, p + 1))}
              disabled={safePage === pageCount}
              aria-label="Next page"
              className="px-2.5 py-1 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
            >
              ›
            </button>
          </span>
        </div>
      )}
    </div>
  );
}
