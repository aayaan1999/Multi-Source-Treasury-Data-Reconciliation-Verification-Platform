import { useState } from "react";
import { api } from "../api";
import useAsync from "../hooks/useAsync";
import { formatNumber } from "../kpi/format";
import DataTable from "./DataTable";

const PAGE = 10;

/**
 * The loans behind whatever was clicked. Read straight from the `loans` table (amounts are in each loan's own currency,
 * which is why the currency is its own column). Pages of 10; while a page reloads the old one stays put, dimmed.
 */
export default function LoanList({ params, emptyText = "No loans match these filters." }) {
  const [offset, setOffset] = useState(0);
  const key = JSON.stringify(params);
  const [seen, setSeen] = useState(key);
  if (seen !== key) {
    setSeen(key);
    setOffset(0);
  }
  const { status, data, error, refreshing, reload } = useAsync(() => api.loans({ ...params, limit: PAGE, offset }), [key, offset]);

  if (status === "error" && !data) {
    return (
      <p role="alert" className="rounded-xl border border-hair bg-surface p-4 text-sm text-ink">
        {error.message}{" "}
        <button type="button" onClick={reload} className="underline">Try again</button>
      </p>
    );
  }
  if (!data) return <p className="rounded-xl border border-hair bg-surface p-4 text-sm text-ink2" role="status">Loading loans…</p>;

  const columns = [
    { key: "loan_id", header: "Loan" },
    { key: "customer_name", header: "Customer", render: (l) => `${l.customer_name} (${l.customer_id})` },
    { key: "product", header: "Product" },
    { key: "branch_id", header: "Branch" },
    { key: "segment", header: "Segment" },
    { key: "currency", header: "Ccy" },
    { key: "outstanding", header: "Outstanding", align: "right", render: (l) => formatNumber(l.outstanding) },
    { key: "days_past_due", header: "Days late", align: "right" },
    { key: "stage", header: "Stage", align: "right" },
    { key: "collateral_value", header: "Collateral", align: "right", render: (l) => formatNumber(l.collateral_value) },
  ];
  const from = data.total === 0 ? 0 : offset + 1;
  const to = Math.min(offset + PAGE, data.total);

  return (
    <div className={refreshing ? "opacity-60 transition-opacity" : "transition-opacity"}>
      <DataTable
        columns={columns}
        rows={data.items}
        rowKey={(l) => l.loan_id}
        rowFlag={(l) => (l.days_past_due >= 90 ? { kind: "loss", label: "Bad loan" } : null)}
        caption="Loans matching the current filters"
        emptyText={emptyText}
      />
      <div className="mt-2 flex items-center justify-between text-sm text-ink2">
        <span>
          {data.total === 0 ? "No loans" : `Showing ${from}–${to} of ${data.total} loans`} · amounts in each loan's own currency
        </span>
        <span className="flex gap-2">
          <button type="button" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}
            className="rounded-md border border-hair px-2.5 py-1 hover:bg-page disabled:opacity-40">Previous</button>
          <button type="button" disabled={offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}
            className="rounded-md border border-hair px-2.5 py-1 hover:bg-page disabled:opacity-40">Next</button>
        </span>
      </div>
    </div>
  );
}
