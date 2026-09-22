import { CrossIcon, WarningIcon } from "./icons";

const ALIGN = { right: "text-right", left: "text-left", center: "text-center" };
const FLAG_ICON = { loss: CrossIcon, watch: WarningIcon };
const FLAG_COLOR = { loss: "var(--critical)", watch: "var(--warning)" };

/**
 * A plain, accessible table.
 *  columns : [{ key, header, align?, render?(row), headerExtra?, title? }]
 *  rowFlag : (row) => { kind: "loss" | "watch", label } | null   flagged rows get a tinted background AND a word + icon
 *  onRowClick : makes each row a drill-down; the first cell becomes a real button so keyboard users can use it too
 *  selectedKey : highlights the row whose rowKey equals it
 */
export default function DataTable({ columns, rows, rowKey, rowFlag, onRowClick, selectedKey, caption, emptyText = "Nothing to show yet." }) {
  if (!rows.length) return <p className="card rounded-xl border border-hair bg-surface p-4 text-sm text-ink2">{emptyText}</p>;
  return (
    <div className="card overflow-x-auto rounded-xl border border-hair bg-surface">
      <table className="w-full text-sm">
        {caption && <caption className="sr-only">{caption}</caption>}
        <thead>
          <tr className="border-b border-hair bg-page/60 text-ink2">
            {columns.map((c) => (
              <th key={c.key} scope="col" title={c.title} className={`px-3 py-2.5 font-medium ${ALIGN[c.align || "left"]}`}>
                <span className="inline-flex items-center gap-1.5">{c.header}{c.headerExtra}</span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
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
                            <span className="inline-flex items-center gap-1 rounded border border-hair px-1.5 py-0.5 text-xs text-ink2">
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
  );
}
