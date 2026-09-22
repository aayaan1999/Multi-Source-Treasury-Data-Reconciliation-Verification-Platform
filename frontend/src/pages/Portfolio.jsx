import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import BarPairChart from "../components/BarPairChart";
import ChartCard from "../components/ChartCard";
import DataTable from "../components/DataTable";
import LoanList from "../components/LoanList";
import PageShell, { ExportButton, LoadError, Loading } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { formatNumber, formatPercentValue, formatUsd, formatUsdCompact } from "../kpi/format";
import { KPI_BY_KEY } from "../kpi/kpiConfig";
import { statusOf } from "../kpi/status";
import {
  AGEING_WATCH, IFRS_STAGES, LTV_UNCOVERED, NPL_REFERENCE_LIMIT_PCT, SINGLE_BORROWER_LIMIT_PCT,
  concentration, coverageStatus, describeFilters, loanParams, parseFilters, topStrip,
} from "../portfolio/derive";

const SERIES = [
  { key: "total_outstanding_usd", label: "Total loans", color: "var(--series-1)" },
  { key: "bad_loan_outstanding_usd", label: "Bad loans (90+ days late)", color: "var(--series-2)" },
];
const DIMENSIONS = [
  { dimension: "product", filter: "product", title: "By product" },
  { dimension: "segment", filter: "segment", title: "By segment" },
  { dimension: "branch", filter: "branch", title: "By branch" },
  { dimension: "currency", filter: "currency", title: "By currency" },
];

async function loadAll() {
  const [stages, topExposures, ageing, ltv, product, segment, branch, currency, branches] = await Promise.all([
    api.stageSummary(), api.topExposures(), api.ageing(), api.ltvDistribution(),
    api.breakdown("product"), api.breakdown("segment"), api.breakdown("branch"), api.breakdown("currency"),
    api.branches().catch(() => []), // only used to show branch names instead of codes
  ]);
  const names = Object.fromEntries(branches.map((b) => [b.branch_id, b.branch_name || b.branch_id]));
  return { stages, topExposures, ageing, ltv, breakdown: { product, segment, branch, currency }, branchNames: names };
}

function BreakdownTable({ rows, selected, onSelect }) {
  return (
    <DataTable
      caption="Loan book breakdown"
      columns={[
        { key: "label", header: "Category" },
        { key: "total_outstanding_usd", header: "Total loans", align: "right", render: (r) => formatUsd(r.total_outstanding_usd) },
        { key: "bad_loan_outstanding_usd", header: "Bad loans", align: "right", render: (r) => formatUsd(r.bad_loan_outstanding_usd) },
      ]}
      rows={rows}
      rowKey={(r) => r.name}
      selectedKey={selected}
      onRowClick={(r) => onSelect(r.name)}
    />
  );
}

function NplReference({ nplRatio }) {
  const scaleMax = Math.max(NPL_REFERENCE_LIMIT_PCT * 2, (nplRatio ?? 0) * 1.2);
  const pct = (v) => `${Math.min(100, (v / scaleMax) * 100)}%`;
  return (
    <div className="card rounded-xl border border-hair bg-surface p-4">
      <div className="flex flex-wrap items-baseline gap-x-3">
        <span className="text-sm font-medium text-ink2">NPL ratio today</span>
        <span className="text-2xl font-semibold tracking-tight text-ink tabular-nums">{formatPercentValue(nplRatio)}</span>
        <span className="text-sm text-ink2">internal limit {NPL_REFERENCE_LIMIT_PCT.toFixed(1)}%</span>
      </div>
      <div className="relative mt-3 h-2 rounded-full" style={{ background: "var(--grid)" }} role="img"
        aria-label={`NPL ratio ${formatPercentValue(nplRatio)} against an internal limit of ${NPL_REFERENCE_LIMIT_PCT}%`}>
        <div className="h-2 rounded-full" style={{ width: pct(nplRatio ?? 0), background: "var(--series-1)" }} />
        <span aria-hidden className="absolute -top-1 h-4 w-0.5" style={{ left: pct(NPL_REFERENCE_LIMIT_PCT), background: "var(--ink-2)" }} />
      </div>
      <p className="mt-3 text-sm text-ink2">
        <strong className="text-ink">The 24-month bad-loan trend and the stage-migration chart aren't shown.</strong> They need
        month-end history that the pipeline doesn't hold yet (it keeps today's snapshot and adds a day each run), and
        nothing here is estimated. Until then, today's ratio is shown against the limit.
      </p>
    </div>
  );
}

export default function Portfolio() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { status, data, error, reload } = useAsync(loadAll, []);
  const filters = useMemo(() => parseFilters(searchParams), [searchParams]);

  // Screen 1's NPL tile links here with ?filter=npl: turn that into the canonical ?bad=1
  useEffect(() => {
    if (searchParams.get("filter") === "npl") {
      const next = new URLSearchParams(searchParams);
      next.delete("filter");
      next.set("bad", "1");
      setSearchParams(next, { replace: true });
    }
  }, [searchParams, setSearchParams]);

  function setFilter(key, value) {
    const next = new URLSearchParams(searchParams);
    if (value === null || value === "" || next.get(key) === value) next.delete(key);   // clicking the same thing again clears it
    else next.set(key, value);
    setSearchParams(next, { replace: true });
  }
  const clearAll = () => setSearchParams(new URLSearchParams(), { replace: true });

  if (status === "loading") return <PageShell title="Portfolio & credit risk"><Loading what="the loan book" /></PageShell>;
  if (status === "error" && !data) return <PageShell title="Portfolio & credit risk"><LoadError error={error} onRetry={reload} /></PageShell>;

  const { stages, topExposures, ageing, ltv, breakdown, branchNames } = data;
  const strip = topStrip(stages, breakdown.product);
  const conc = concentration(topExposures, strip.grossLoans);
  const asOf = stages[0]?.calculation_date;
  const chips = describeFilters(filters, branchNames);
  const params = loanParams(filters);
  const nplStatus = statusOf(KPI_BY_KEY.npl_ratio_pct, strip.nplRatio);

  const chartRows = (dimension) =>
    breakdown[dimension].map((r) => ({
      ...r,
      name: r.dimension_value,
      label: dimension === "branch" ? branchNames[r.dimension_value] ?? r.dimension_value : r.dimension_value,
    }));
  const options = (dimension) => breakdown[dimension].map((r) => r.dimension_value);
  const select = "rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40";

  return (
    <PageShell
      title="Portfolio & credit risk"
      subtitle="Where the loan book is, and how much of it is going bad. Every figure comes from the nightly precomputed tables."
      asOf={asOf}
      actions={<ExportButton label="Export to Excel" onExport={api.exportPortfolio} />}
    >
      <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-5" aria-label="Portfolio summary">
        <StatBox label="Gross loans" value={formatUsdCompact(strip.grossLoans)} hint="Total lent out (USD)" />
        <StatBox label="NPL amount" value={formatUsdCompact(strip.nplAmount)} hint="Loans 90+ days late" />
        <StatBox label="NPL ratio" value={formatPercentValue(strip.nplRatio)} hint={`Internal limit ${NPL_REFERENCE_LIMIT_PCT.toFixed(1)}%`} status={nplStatus} />
        <StatBox label="Coverage ratio" value={formatPercentValue(strip.coverageRatio)} hint="Provisions set aside ÷ NPL amount. Below about 50% is thin" status={coverageStatus(strip.coverageRatio)} />
        <StatBox label="Cost of risk" value="—" hint="Needs the year's provision charge, which the pipeline doesn't hold yet" />
      </ul>

      <Section
        id="filters"
        title="Filters"
        description="The charts always show the whole loan book. These filters narrow the loan list at the bottom of the page and highlight the matching bars. Clicking a bar or a table row sets the same filter."
      >
        <div className="card flex flex-wrap items-center gap-3 rounded-xl border border-hair bg-surface p-3.5">
          {[["product", "Product"], ["segment", "Segment"], ["branch", "Branch"], ["currency", "Currency"]].map(([key, label]) => (
            <label key={key} className="flex items-center gap-2 text-sm text-ink2">
              {label}
              <select className={select} value={filters[key] ?? ""} onChange={(e) => setFilter(key, e.target.value)}>
                <option value="">All</option>
                {options(key).map((v) => (
                  <option key={v} value={v}>{key === "branch" ? branchNames[v] ?? v : v}</option>
                ))}
              </select>
            </label>
          ))}
          <label className="flex items-center gap-2 text-sm text-ink2">
            <input type="checkbox" className="accent-accent" checked={Boolean(filters.bad)} onChange={(e) => setFilter("bad", e.target.checked ? "1" : "")} />
            Bad loans only
          </label>
          {chips.length > 0 && (
            <button type="button" onClick={clearAll} className="ml-auto rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink">
              Clear all filters
            </button>
          )}
        </div>
      </Section>

      <Section id="book" title="The loan book, sliced four ways" description="Two bars per category: everything lent, and the part that is 90+ days late. A product can look large and healthy, or small and on fire.">
        <ul className="grid grid-cols-1 gap-4 lg:grid-cols-2">
          {DIMENSIONS.map(({ dimension, filter, title }) => {
            const rows = chartRows(dimension);
            const select_ = (name) => setFilter(filter, name);
            return (
              <ChartCard key={dimension} title={title} legend={SERIES} table={<BreakdownTable rows={rows} selected={filters[filter]} onSelect={select_} />}>
                <BarPairChart data={rows} series={SERIES} selected={filters[filter]} onSelect={select_} />
              </ChartCard>
            );
          })}
        </ul>
      </Section>

      <Section id="trend" title="Bad-loan trend">
        <NplReference nplRatio={strip.nplRatio} />
      </Section>

      <Section id="ifrs9" title="IFRS 9 staging" description="Stage 2 is the early warning: loans that are not yet late but have got worse. Click a row to see its loans.">
        <DataTable
          caption="IFRS 9 stages"
          columns={[
            { key: "stage", header: "Stage", render: (r) => IFRS_STAGES[r.stage] ?? `Stage ${r.stage}` },
            { key: "loan_count", header: "Loans", align: "right", render: (r) => formatNumber(r.loan_count) },
            { key: "outstanding_usd", header: "Outstanding", align: "right", render: (r) => formatUsd(r.outstanding_usd) },
            { key: "provisions_usd", header: "Provisions", align: "right", render: (r) => formatUsd(r.provisions_usd) },
            { key: "coverage_pct", header: "Coverage %", align: "right", render: (r) => formatPercentValue(r.coverage_pct) },
          ]}
          rows={stages}
          rowKey={(r) => String(r.stage)}
          selectedKey={filters.stage}
          onRowClick={(r) => setFilter("stage", String(r.stage))}
        />
      </Section>

      <Section
        id="top"
        title="Top exposures"
        description={`The largest borrowers. A row is flagged when a customer's exposure is above ${SINGLE_BORROWER_LIMIT_PCT}% of capital (placeholder limit, to be confirmed with the regulator). Click a row to see that customer's loans.`}
      >
        <DataTable
          caption="Top exposures"
          columns={[
            { key: "customer_name", header: "Customer", render: (r) => `${r.customer_name} (${r.customer_id})` },
            { key: "product", header: "Product" },
            { key: "outstanding_usd", header: "Outstanding", align: "right", render: (r) => formatUsd(r.outstanding_usd) },
            { key: "days_past_due", header: "Days late", align: "right" },
            { key: "pct_of_capital", header: "% of capital", align: "right", render: (r) => formatPercentValue(r.pct_of_capital, 2) },
          ]}
          rows={topExposures}
          rowKey={(r) => r.customer_id}
          rowFlag={(r) => (r.pct_of_capital > SINGLE_BORROWER_LIMIT_PCT ? { kind: "loss", label: "Over limit" } : null)}
          selectedKey={filters.customer}
          onRowClick={(r) => setFilter("customer", r.customer_id)}
        />
        {conc.pct !== null && (
          <p className="mt-2 text-sm text-ink2">
            Top {conc.count} {conc.count === 1 ? "borrower" : "borrowers"} = <strong className="text-ink">{formatPercentValue(conc.pct)}</strong> of gross loans
          </p>
        )}
      </Section>

      <Section id="ageing" title="Ageing" description="Loans 31–90 days late aren't officially bad yet, but most will be next quarter. Click a row to see its loans.">
        <DataTable
          caption="Loan ageing"
          columns={[
            { key: "bucket", header: "Days late" },
            { key: "outstanding_usd", header: "Amount", align: "right", render: (r) => formatUsd(r.outstanding_usd) },
            { key: "pct_of_book", header: "% of book", align: "right", render: (r) => formatPercentValue(r.pct_of_book) },
          ]}
          rows={ageing}
          rowKey={(r) => r.bucket}
          rowFlag={(r) => (AGEING_WATCH.has(r.bucket) ? { kind: "watch", label: "Watch" } : null)}
          selectedKey={filters.ageing}
          onRowClick={(r) => setFilter("ageing", r.bucket)}
        />
      </Section>

      <Section id="ltv" title="Collateral and loan-to-value" description="What is still owed against what the security is worth. Above 100% is uncovered: the bank loses money even after selling. Loans with no collateral value count as above 100%.">
        <ul>
          <ChartCard
            title="Loans by LTV bucket"
            table={
              <DataTable
                caption="LTV distribution"
                columns={[
                  { key: "bucket", header: "LTV" },
                  { key: "outstanding_usd", header: "Outstanding", align: "right", render: (r) => formatUsd(r.outstanding_usd) },
                  { key: "loan_count", header: "Loans", align: "right" },
                ]}
                rows={ltv}
                rowKey={(r) => r.bucket}
                selectedKey={filters.ltv}
                onRowClick={(r) => setFilter("ltv", r.bucket)}
              />
            }
            note={`Red = uncovered exposure (LTV above 100%).`}
          >
            <BarPairChart
              data={ltv.map((r) => ({ ...r, name: r.bucket, label: r.bucket === LTV_UNCOVERED ? "Above 100%" : r.bucket }))}
              series={[{ key: "outstanding_usd", label: "Outstanding", color: "var(--series-1)" }]}
              selected={filters.ltv}
              onSelect={(name) => setFilter("ltv", name)}
              cellColor={(name) => (name === LTV_UNCOVERED ? "var(--critical)" : undefined)}
            />
          </ChartCard>
        </ul>
      </Section>

      <Section
        id="loans"
        title="Loans behind the selection"
        description={chips.length ? "Filtered by:" : "No filters set: showing every loan, largest first. Pick a bar, a row or a filter above."}
      >
        {chips.length > 0 && (
          <ul className="mb-3 flex flex-wrap gap-2" aria-label="Active filters">
            {chips.map(([key, text]) => (
              <li key={key}>
                <button type="button" onClick={() => setFilter(key, "")} className="inline-flex items-center gap-1.5 rounded-full border border-accent/30 bg-accent/10 px-2.5 py-1 text-sm text-ink transition-colors hover:bg-accent/20" aria-label={`Remove filter ${text}`}>
                  {text} <span aria-hidden className="text-ink2">×</span>
                </button>
              </li>
            ))}
          </ul>
        )}
        <LoanList params={params} />
      </Section>
    </PageShell>
  );
}
