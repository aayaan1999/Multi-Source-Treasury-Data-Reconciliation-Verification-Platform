import { isNum } from "../kpi/format";

// The assumptions behind Screen 5's numbers, copied from notebooks/06 (they are baked into the pipeline's output, so the UI
// can only describe them). Shown next to every figure they touch.
export const REGION_CURRENCY = { Beirut: "USD", North: "USD", South: "USD", KSA: "SAR", Qatar: "QAR" };

export const COST_ASSUMPTION = [
  "REGION_CURRENCY: each branch's monthly operating cost is treated as being in its region's currency and converted to USD at the live rate — " +
    Object.entries(REGION_CURRENCY).map(([r, c]) => `${r} ${c}`).join(", "),
  "Cost is direct branch cost only. Head-office, IT and central functions are not allocated.",
];

export const SEGMENT_ASSUMPTION = [
  "SEGMENT_COST_ALLOCATION: nothing in the data attributes branch cost to a customer segment, so each branch's cost is split across its segments in proportion to their share of that branch's loans + deposits.",
  "So segment profit is an allocation, not a measurement.",
];

const sum = (rows, key) => rows.reduce((total, r) => total + (isNum(r[key]) ? r[key] : 0), 0);

/** The four boxes at the top of Screen 5. */
export function stripTotals(branches) {
  const revenue = sum(branches, "revenue_usd");
  const cost = sum(branches, "cost_usd");
  return { revenue, cost, profit: revenue - cost, inLoss: branches.filter((b) => isNum(b.profit_usd) && b.profit_usd < 0).length };
}

/** Regional rollup: the same branch figures grouped by region, worst profit first. */
export function regionRollup(branches) {
  const byRegion = new Map();
  for (const b of branches) {
    const r = byRegion.get(b.region) ?? { region: b.region, branches: 0, revenue_usd: 0, cost_usd: 0, profit_usd: 0 };
    r.branches += 1;
    r.revenue_usd += b.revenue_usd ?? 0;
    r.cost_usd += b.cost_usd ?? 0;
    r.profit_usd += b.profit_usd ?? 0;
    byRegion.set(b.region, r);
  }
  return [...byRegion.values()].sort((a, b) => a.profit_usd - b.profit_usd);
}

const median = (values) => {
  const sorted = [...values].sort((a, b) => a - b);
  const mid = Math.floor(sorted.length / 2);
  return sorted.length % 2 ? sorted[mid] : (sorted[mid - 1] + sorted[mid]) / 2;
};

export const QUADRANTS = {
  star: { name: "Stars", advice: "Low cost ratio, high revenue: protect them" },
  small: { name: "Efficient but small", advice: "Low cost ratio, low revenue: grow them" },
  wasteful: { name: "Big but wasteful", advice: "High cost ratio, high revenue: fix the costs" },
  closure: { name: "Closure candidates", advice: "High cost ratio, low revenue" },
};

/**
 * The efficiency quadrant: revenue (x) against cost-to-income (y). A branch with no revenue has no cost-to-income
 * (it is undefined, not zero), so it cannot be plotted and is listed separately. The four groups are split at the
 * median of the branches shown, since the source document sets no fixed line.
 */
export function quadrant(branches) {
  const plotted = branches.filter((b) => isNum(b.revenue_usd) && isNum(b.cost_to_income_pct));
  const unplotted = branches.filter((b) => !plotted.includes(b));
  const revenueMid = plotted.length ? median(plotted.map((b) => b.revenue_usd)) : null;
  const ratioMid = plotted.length ? median(plotted.map((b) => b.cost_to_income_pct)) : null;
  const which = (b) => {
    const highRevenue = b.revenue_usd >= revenueMid;
    const highCost = b.cost_to_income_pct >= ratioMid;
    if (highCost) return highRevenue ? "wasteful" : "closure";
    return highRevenue ? "star" : "small";
  };
  return { plotted: plotted.map((b) => ({ ...b, quadrant: which(b) })), unplotted, revenueMid, ratioMid };
}
