import { describe, expect, it } from "vitest";
import { quadrant, regionRollup, stripTotals } from "./derive";

const b = (id, region, revenue_usd, cost_usd, cost_to_income_pct) => ({ branch_id: id, region, revenue_usd, cost_usd, profit_usd: revenue_usd - cost_usd, cost_to_income_pct });

describe("branch performance", () => {
  const branches = [b("B1", "Beirut", 100, 60, 60), b("B2", "Beirut", 50, 80, 160), b("B3", "KSA", 200, 100, 50), b("B4", "KSA", 10, 12, 120)];
  it("strip totals count branches in loss", () => {
    expect(stripTotals(branches)).toEqual({ revenue: 360, cost: 252, profit: 108, inLoss: 2 });
  });
  it("region rollup sums branches, worst profit first", () => {
    const r = regionRollup(branches);
    expect(r.map((x) => x.region)).toEqual(["Beirut", "KSA"]);
    expect(r[0]).toMatchObject({ branches: 2, revenue_usd: 150, cost_usd: 140, profit_usd: 10 });
  });
  it("quadrant splits at the medians", () => {
    const q = quadrant(branches);
    const of = Object.fromEntries(q.plotted.map((x) => [x.branch_id, x.quadrant]));
    expect(of).toEqual({ B1: "star", B2: "closure", B3: "star", B4: "closure" });
    expect(q.revenueMid).toBe(75);
    expect(q.ratioMid).toBe(90);
  });
  it("a branch with no revenue is listed, not plotted as zero", () => {
    const q = quadrant([...branches, b("B5", "KSA", 0, 5, null)]);
    expect(q.unplotted.map((x) => x.branch_id)).toEqual(["B5"]);
    expect(q.plotted).toHaveLength(4);
  });
});
