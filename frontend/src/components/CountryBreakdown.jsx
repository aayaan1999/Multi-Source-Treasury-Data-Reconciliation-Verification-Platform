import { api } from "../api";
import useAsync from "../hooks/useAsync";
import { formatNumber, formatPercentValue, formatUsdCompact, isNum } from "../kpi/format";
import DataTable from "./DataTable";

const SUMMED = ["customer_count", "deposits_usd", "loans_usd", "npl_loans_usd", "transaction_count", "transaction_volume_usd"];

/** Each country's row plus its share of the bank's loans, and a bank-wide total row at the end. The
 * total is summed here (all figures are USD, so they add up); its bad-loan ratio is recomputed from
 * the sums, never averaged across countries. */
export function withBankTotal(rows) {
  const total = { country: "Bank-wide" };
  for (const key of SUMMED) total[key] = rows.reduce((n, r) => n + (isNum(r[key]) ? r[key] : 0), 0);
  total.npl_ratio_pct = total.loans_usd ? (total.npl_loans_usd / total.loans_usd) * 100 : null;
  const share = (r) => (total.loans_usd ? (r.loans_usd / total.loans_usd) * 100 : null);
  return [...rows.map((r) => ({ ...r, loan_share_pct: share(r) })), { ...total, loan_share_pct: rows.length ? 100 : null }];
}

/**
 * The CFO's global view by country (FLOW-4, specs/cfo-country-view.md): latest customers, deposits,
 * loans, bad loans and activity per country, in USD. Loads on its own, so the rest of the dashboard
 * still shows if this table isn't there yet.
 */
export default function CountryBreakdown({ reloadKey }) {
  const { status, data, error } = useAsync(() => api.kpiCountries(), [reloadKey]);

  if (status === "loading") return <p className="text-sm text-ink2" role="status">Loading the country view…</p>;
  if (status === "error" && !data) return <p className="text-sm text-ink2">The country view isn't available yet ({error?.message}).</p>;
  if (!data.length) return <p className="text-sm text-ink2">No country figures yet: they appear after the next pipeline run.</p>;

  return (
    <>
      <DataTable
        caption="Performance by country"
        columns={[
          { key: "country", header: "Country" },
          { key: "customer_count", header: "Customers", align: "right", render: (r) => formatNumber(r.customer_count) },
          { key: "deposits_usd", header: "Deposits", align: "right", render: (r) => formatUsdCompact(r.deposits_usd) },
          { key: "loans_usd", header: "Loans", align: "right", render: (r) => formatUsdCompact(r.loans_usd) },
          { key: "loan_share_pct", header: "Share of loans", align: "right", render: (r) => formatPercentValue(r.loan_share_pct) },
          { key: "npl_ratio_pct", header: "Bad loans", align: "right", title: "Loans 90+ days past due, as a share of the country's loans", render: (r) => formatPercentValue(r.npl_ratio_pct) },
          { key: "transaction_count", header: "Transactions", align: "right", render: (r) => formatNumber(r.transaction_count) },
          { key: "transaction_volume_usd", header: "Volume", align: "right", render: (r) => formatUsdCompact(r.transaction_volume_usd) },
        ]}
        rows={withBankTotal(data)}
        rowKey={(r) => r.country}
      />
      <p className="mt-2 text-xs text-muted">
        All amounts in USD at the day's live rates. A record's country comes from its branch; "Unknown" means its branch
        couldn't be found in the source data.
      </p>
    </>
  );
}
