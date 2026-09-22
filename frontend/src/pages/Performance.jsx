import { useEffect, useMemo } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api";
import AssumptionBadge from "../components/AssumptionBadge";
import BarPairChart from "../components/BarPairChart";
import ChartCard from "../components/ChartCard";
import DataTable from "../components/DataTable";
import EfficiencyScatter from "../components/EfficiencyScatter";
import LoanList from "../components/LoanList";
import PageShell, { ExportButton, LoadError, Loading } from "../components/PageShell";
import Section from "../components/Section";
import StatBox from "../components/StatBox";
import useAsync from "../hooks/useAsync";
import { formatNumber, formatPercentValue, formatUsd, formatUsdCompact } from "../kpi/format";
import { COST_ASSUMPTION, QUADRANTS, SEGMENT_ASSUMPTION, quadrant, regionRollup, stripTotals } from "../performance/derive";

const REVENUE_COST = [
  { key: "revenue_usd", label: "Revenue", color: "var(--series-1)" },
  { key: "cost_usd", label: "Cost", color: "var(--series-2)" },
];

async function loadAll() {
  const [branches, segments, products, channels] = await Promise.all([
    api.branches(), api.segments(), api.products(), api.channels(),
  ]);
  return { branches, segments, products, channels };
}

const branchLabel = (b) => `${b.branch_name || b.branch_id} (${b.branch_id})`;

/** Customers and loans behind a clicked branch or segment. */
function DrillPanel({ kind, id, title, onClose }) {
  const filter = kind === "branch" ? { branch_id: id } : { segment: id };
  const { status, data, error, reload } = useAsync(() => api.customers({ ...filter, limit: 10 }), [kind, id]);
  return (
    <Section
      id="drill"
      title={`Customers and loans: ${title}`}
      action={<button type="button" onClick={onClose} className="rounded-md border border-hair px-2.5 py-1.5 text-sm text-ink2 transition-colors hover:border-accent/40 hover:bg-page hover:text-ink">Close</button>}
    >
      <h3 className="mb-2 text-sm font-medium text-ink2">Customers</h3>
      {status === "error" && !data ? (
        <p role="alert" className="text-sm text-ink">{error.message} <button type="button" onClick={reload} className="underline">Try again</button></p>
      ) : !data ? (
        <p className="text-sm text-ink2" role="status">Loading customers…</p>
      ) : (
        <>
          <DataTable
            caption="Customers"
            columns={[
              { key: "name", header: "Customer", render: (c) => `${c.name} (${c.customer_id})` },
              { key: "segment", header: "Segment" },
              { key: "branch_id", header: "Branch" },
              { key: "risk_rating", header: "Risk rating" },
              { key: "loan_count", header: "Loans", align: "right" },
              { key: "bad_loan_count", header: "Bad loans", align: "right" },
            ]}
            rows={data.items}
            rowKey={(c) => c.customer_id}
            rowFlag={(c) => (c.bad_loan_count > 0 ? { kind: "loss", label: "Has bad loans" } : null)}
            emptyText="No customers found."
          />
          <p className="mt-1 text-sm text-ink2">{data.total > data.items.length ? `Showing ${data.items.length} of ${data.total} customers` : `${data.total} ${data.total === 1 ? "customer" : "customers"}`}</p>
        </>
      )}
      <h3 className="mb-2 mt-5 text-sm font-medium text-ink2">Loans</h3>
      <LoanList params={filter} />
    </Section>
  );
}

export default function Performance() {
  const [searchParams, setSearchParams] = useSearchParams();
  const { status, data, error, reload } = useAsync(loadAll, []);
  const region = searchParams.get("region") ?? "";
  const [drillKind, drillId] = (searchParams.get("drill") ?? "").split(":");
  const view = searchParams.get("view");

  // Screen 1's NIM / cost-to-income / ROE tiles link here with ?view=products|branches|segments
  useEffect(() => {
    if (status === "ready" && view) document.getElementById(view)?.scrollIntoView?.();
  }, [status, view]);

  const setParam = (key, value) => {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next, { replace: true });
  };

  const branches = useMemo(
    () => (data ? (region ? data.branches.filter((b) => b.region === region) : data.branches) : []),
    [data, region],
  );
  const regions = useMemo(() => (data ? [...new Set(data.branches.map((b) => b.region))].sort() : []), [data]);

  if (status === "loading") return <PageShell title="Branch & segment performance"><Loading what="performance figures" /></PageShell>;
  if (status === "error" && !data) return <PageShell title="Branch & segment performance"><LoadError error={error} onRetry={reload} /></PageShell>;

  const totals = stripTotals(branches);
  const rollup = regionRollup(branches);
  const quad = quadrant(branches);
  const asOf = data.branches[0]?.calculation_date;
  const drillTitle = drillKind === "branch" ? branchLabel(data.branches.find((b) => b.branch_id === drillId) ?? { branch_id: drillId }) : drillId;
  const channels = data.channels.channels;
  const totalTx = channels.reduce((n, c) => n + c.transaction_count, 0);
  const costBadge = <AssumptionBadge items={COST_ASSUMPTION} label="Assumption" align="left" />;

  return (
    <PageShell
      title="Branch & segment performance"
      subtitle="Who in the bank is making money and who is losing it. Cost here is direct branch cost only."
      asOf={asOf}
      actions={<ExportButton label="Export to Excel" onExport={api.exportPerformance} />}
    >
      <ul className="mt-6 grid grid-cols-1 gap-5 sm:grid-cols-2 lg:grid-cols-4" aria-label="Performance summary">
        <StatBox label="Total revenue" value={formatUsdCompact(totals.revenue)} hint="Interest income + fee income" />
        <StatBox label="Total cost" value={formatUsdCompact(totals.cost)} hint="Direct branch operating cost" badge={costBadge} />
        <StatBox label="Profit" value={formatUsdCompact(totals.profit)} hint="Revenue minus cost" status={totals.profit < 0 ? "action" : "good"} />
        <StatBox
          label="Branches in loss"
          value={`${totals.inLoss} of ${branches.length}`}
          hint={totals.inLoss > 0 ? "Where profit is below zero" : "Every branch is profitable"}
          status={totals.inLoss > 0 ? "action" : "good"}
        />
      </ul>

      <Section id="filters" title="Filters" description="Region scopes the boxes, the branch table, the regional rollup and the scatter. The segment, product and channel figures cover the whole bank.">
        <div className="card flex flex-wrap items-center gap-3 rounded-xl border border-hair bg-surface p-3.5">
          <label className="flex items-center gap-2 text-sm text-ink2">
            Region
            <select className="rounded-md border border-hair bg-surface px-2 py-1.5 text-sm text-ink transition-colors hover:border-accent/40" value={region} onChange={(e) => setParam("region", e.target.value)}>
              <option value="">All regions</option>
              {regions.map((r) => <option key={r} value={r}>{r}</option>)}
            </select>
          </label>
          <span className="text-sm text-ink2">Period: today's snapshot (history builds up daily)</span>
        </div>
      </Section>

      <Section id="branches" title="Branch league table" description="Worst profit first. Loss-making rows are flagged. Click a row to see that branch's customers and loans.">
        <DataTable
          caption="Branch league table"
          columns={[
            { key: "branch", header: "Branch", render: branchLabel },
            { key: "region", header: "Region" },
            { key: "deposits_usd", header: "Deposits", align: "right", render: (b) => formatUsd(b.deposits_usd) },
            { key: "loans_usd", header: "Loans", align: "right", render: (b) => formatUsd(b.loans_usd) },
            { key: "revenue_usd", header: "Revenue", align: "right", render: (b) => formatUsd(b.revenue_usd) },
            { key: "cost_usd", header: "Cost", align: "right", headerExtra: costBadge, render: (b) => formatUsd(b.cost_usd) },
            { key: "profit_usd", header: "Profit", align: "right", render: (b) => formatUsd(b.profit_usd) },
            { key: "cost_to_income_pct", header: "Cost-to-income", align: "right", title: "Cost ÷ revenue. Above 100% means the branch spends more than it earns", render: (b) => formatPercentValue(b.cost_to_income_pct, 0) },
            { key: "staff_count", header: "Staff", align: "right" },
            { key: "profit_per_staff_usd", header: "Profit / staff", align: "right", render: (b) => formatUsd(b.profit_per_staff_usd) },
          ]}
          rows={branches}
          rowKey={(b) => b.branch_id}
          rowFlag={(b) => (b.profit_usd < 0 ? { kind: "loss", label: "Loss" } : null)}
          selectedKey={drillKind === "branch" ? drillId : undefined}
          onRowClick={(b) => setParam("drill", `branch:${b.branch_id}`)}
          emptyText="No branches in this region."
        />
        <p className="mt-2 text-xs text-ink2">Cost-to-income is blank where a branch has no revenue (cost ÷ nothing is undefined, not zero).</p>
      </Section>

      <Section id="regions" title="Regional rollup" description="Is the problem one bad branch or a whole region?">
        <ul>
          <ChartCard
            title="Revenue and cost by region"
            legend={REVENUE_COST}
            table={
              <DataTable
                caption="Regional rollup"
                columns={[
                  { key: "region", header: "Region" },
                  { key: "branches", header: "Branches", align: "right" },
                  { key: "revenue_usd", header: "Revenue", align: "right", render: (r) => formatUsd(r.revenue_usd) },
                  { key: "cost_usd", header: "Cost", align: "right", render: (r) => formatUsd(r.cost_usd) },
                  { key: "profit_usd", header: "Profit", align: "right", render: (r) => formatUsd(r.profit_usd) },
                ]}
                rows={rollup}
                rowKey={(r) => r.region}
                onRowClick={(r) => setParam("region", r.region)}
              />
            }
          >
            <BarPairChart
              data={rollup.map((r) => ({ ...r, name: r.region, label: r.region }))}
              series={REVENUE_COST}
              ratioLabel="cost-to-income"
              onSelect={(name) => setParam("region", name)}
              selected={region}
            />
          </ChartCard>
        </ul>
      </Section>

      <Section id="segments" title="Customer segments" description="Retail, SME and Corporate.">
        <div role="note" className="card mb-3 flex flex-wrap items-center gap-2 rounded-xl border border-hair bg-surface p-3 text-sm text-ink">
          <AssumptionBadge items={SEGMENT_ASSUMPTION} label="Allocated, not measured" align="left" heading="How segment profit is worked out" footer="Confirm the allocation method with the bank's finance team." />
          <span>
            <strong>Segment profit is not measured.</strong> Nothing in the data attributes branch cost to a segment, so cost is
            allocated in proportion to each segment's loans and deposits.
          </span>
        </div>
        <DataTable
          caption="Segment performance"
          columns={[
            { key: "segment", header: "Segment" },
            { key: "customer_count", header: "Customers", align: "right", render: (s) => formatNumber(s.customer_count) },
            { key: "deposits_usd", header: "Deposits", align: "right", render: (s) => formatUsd(s.deposits_usd) },
            { key: "loans_usd", header: "Loans", align: "right", render: (s) => formatUsd(s.loans_usd) },
            { key: "revenue_usd", header: "Revenue", align: "right", render: (s) => formatUsd(s.revenue_usd) },
            { key: "bad_loans_usd", header: "Bad loans", align: "right", render: (s) => formatUsd(s.bad_loans_usd) },
            { key: "profit_usd", header: "Profit (cost allocated proportionally)", align: "right", render: (s) => formatUsd(s.profit_usd) },
            { key: "revenue_per_customer_usd", header: "Revenue / customer", align: "right", render: (s) => formatUsd(s.revenue_per_customer_usd) },
          ]}
          rows={data.segments}
          rowKey={(s) => s.segment}
          rowFlag={(s) => (s.profit_usd < 0 ? { kind: "loss", label: "Loss (allocated)" } : null)}
          selectedKey={drillKind === "segment" ? drillId : undefined}
          onRowClick={(s) => setParam("drill", `segment:${s.segment}`)}
        />
      </Section>

      <Section id="products" title="Product performance" description="Net contribution is interest income minus provisions. A product can earn a high rate and still lose money once bad loans are counted.">
        <DataTable
          caption="Product performance"
          columns={[
            { key: "product", header: "Product" },
            { key: "outstanding_usd", header: "Outstanding", align: "right", render: (p) => formatUsd(p.outstanding_usd) },
            { key: "avg_interest_rate", header: "Avg rate", align: "right", render: (p) => formatPercentValue(p.avg_interest_rate, 2) },
            { key: "interest_income_usd", header: "Interest income", align: "right", render: (p) => formatUsd(p.interest_income_usd) },
            { key: "npl_pct", header: "NPL %", align: "right", render: (p) => formatPercentValue(p.npl_pct) },
            { key: "net_contribution_usd", header: "Net contribution", align: "right", render: (p) => formatUsd(p.net_contribution_usd) },
          ]}
          rows={data.products}
          rowKey={(p) => p.product}
          rowFlag={(p) => (p.net_contribution_usd < 0 ? { kind: "loss", label: "Loses money" } : null)}
        />
      </Section>

      <Section id="channels" title="Channel usage" description="How customers transact, now. There is no earlier period to compare with yet, so there is no 'then vs now'.">
        <ul>
          <ChartCard
            title="Share of transactions by channel"
            note={
              data.channels.first_date
                ? `${formatNumber(totalTx)} transactions from ${data.channels.first_date} to ${data.channels.last_date}. Counted by number of transactions, since amounts are in mixed currencies.`
                : undefined
            }
            table={
              <DataTable
                caption="Channel usage"
                columns={[
                  { key: "channel", header: "Channel" },
                  { key: "transaction_count", header: "Transactions", align: "right" },
                  { key: "share_pct", header: "Share", align: "right", render: (c) => formatPercentValue(c.share_pct) },
                ]}
                rows={channels}
                rowKey={(c) => c.channel}
              />
            }
          >
            <BarPairChart
              data={channels.map((c) => ({ ...c, name: c.channel, label: c.channel }))}
              series={[{ key: "share_pct", label: "Share of transactions", color: "var(--series-1)" }]}
              format={(v) => `${Math.round(v)}%`}
              formatFull={(v) => formatPercentValue(v)}
              ratioLabel={null}
            />
          </ChartCard>
        </ul>
      </Section>

      <Section id="quadrant" title="Efficiency quadrant" description="Each dot is a branch: revenue across, cost-to-income up, dot size = deposits. The lines split the branches shown at their median.">
        <ul>
          <ChartCard
            title="Revenue against cost-to-income"
            table={
              <DataTable
                caption="Efficiency quadrant"
                columns={[
                  { key: "branch", header: "Branch", render: branchLabel },
                  { key: "revenue_usd", header: "Revenue", align: "right", render: (b) => formatUsd(b.revenue_usd) },
                  { key: "cost_to_income_pct", header: "Cost-to-income", align: "right", render: (b) => formatPercentValue(b.cost_to_income_pct, 0) },
                  { key: "deposits_usd", header: "Deposits", align: "right", render: (b) => formatUsd(b.deposits_usd) },
                  { key: "quadrant", header: "Group", render: (b) => QUADRANTS[b.quadrant].name },
                ]}
                rows={quad.plotted}
                rowKey={(b) => b.branch_id}
              />
            }
            note={
              quad.unplotted.length
                ? `Not plotted (no revenue, so no cost-to-income): ${quad.unplotted.map(branchLabel).join(", ")}.`
                : undefined
            }
          >
            {quad.plotted.length ? (
              <EfficiencyScatter points={quad.plotted} revenueMid={quad.revenueMid} ratioMid={quad.ratioMid} onSelect={(b) => setParam("drill", `branch:${b.branch_id}`)} />
            ) : (
              <p className="text-sm text-ink2">No branch has both revenue and a cost-to-income ratio to plot.</p>
            )}
          </ChartCard>
        </ul>
      </Section>

      {drillKind && drillId && (
        <DrillPanel kind={drillKind} id={drillId} title={drillTitle} onClose={() => setParam("drill", "")} />
      )}
    </PageShell>
  );
}
