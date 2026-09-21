import { describe, expect, it } from "vitest";
import engineSource from "./engine.js?raw";
import {
  ASSUMPTION_DEFS, PRESETS, SLIDERS, computeScenario, defaultAssumptions, loanBookShare, missingSnapshotFields,
  ratioStatus, summarise, surplusStatus,
} from "./engine";

// A bank-sized position: loans are 70% of RWA, so a stress on loans is visible in the ratio.
const SNAP = {
  loans_by_currency: { LBP: 400e6, USD: 900e6, SAR: 100e6 },        // gross 1,400m; foreign (non-LBP) 1,000m
  loans_by_rate_type: { fixed: 300e6, floating: 1100e6 },
  deposits_by_type: { Current: 600e6, Savings: 300e6, "Term deposit": 100e6 },   // 1,000m
  deposits_by_rate_type: { fixed: 100e6, floating: 900e6 },
  tier1_capital_usd: 207e6, tier2_capital_usd: 39e6, risk_weighted_assets_usd: 1985e6,   // capital 246m
  hqla_usd: 515e6, net_outflows_30d_usd: 356e6,
  current_npl_pct: 6, current_coverage_pct: 3.6,                    // -> coverage on bad loans = 3.6 / 6 = 60%
};
const A = defaultAssumptions(SNAP);
const NONE = PRESETS.base.inputs;
const only = (patch) => ({ ...NONE, ...patch });
const run = (inputs, snapshot = SNAP, assumptions = A) => computeScenario(snapshot, inputs, assumptions);
const near = (actual, expected, digits = 4) => expect(actual).toBeCloseTo(expected, digits);

describe("defaults", () => {
  it("derives coverage on bad loans from the snapshot (provisions over ALL loans / NPL ratio), else 70%", () => {
    near(A.coveragePct, 60);
    expect(defaultAssumptions({ current_npl_pct: 0, current_coverage_pct: 5 }).coveragePct).toBe(70);
    expect(defaultAssumptions({}).coveragePct).toBe(70);
    expect(defaultAssumptions({ current_npl_pct: 2, current_coverage_pct: 5 }).coveragePct).toBe(100);   // capped at 100%
  });

  it("uses the source document's regulatory floors and devaluation rule", () => {
    expect(A.minimumCarPct).toBe(12);
    expect(A.minimumLcrPct).toBe(100);
    expect(A.defaultUpliftPerDevaluationPct * 20).toBeCloseTo(4);          // 20% devaluation -> +4% defaults (3-5% range)
  });

  it("presets: base is zeros, severe is double adverse", () => {
    expect(Object.values(PRESETS.base.inputs)).toEqual([0, 0, 0, 0]);
    for (const k of Object.keys(PRESETS.adverse.inputs)) expect(PRESETS.severe.inputs[k]).toBe(PRESETS.adverse.inputs[k] * 2);
  });

  it("slider ranges match the source document", () => {
    const range = Object.fromEntries(SLIDERS.map((s) => [s.key, [s.min, s.max]]));
    expect(range).toEqual({ devaluationPct: [0, 50], rateChangePct: [-5, 5], nplIncreasePct: [0, 15], depositOutflowPct: [0, 30] });
  });
});

describe("the base scenario changes nothing", () => {
  const r = run(NONE);
  it("after equals before for every measure", () => {
    near(r.before.car, (246 / 1985) * 100);
    near(r.after.car, r.before.car, 10);
    near(r.after.lcr, r.before.lcr, 10);
    near(r.after.surplus, r.before.surplus, 2);
    expect(r.after.profitImpact).toBe(0);
    expect(r.steps.every((s) => Math.abs(s.delta) < 1e-9)).toBe(true);
    expect(r.breachMonth).toBeNull();
    expect(r.hqlaExhausted).toBe(false);
  });
});

describe("each stress on its own, hand-calculated", () => {
  it("devaluation 20%: foreign loans revalue, 4% of them default, provisions at 60%", () => {
    const r = run(only({ devaluationPct: 20 }));
    near(r.detail.foreignLoans, 1000e6, 0);
    near(r.detail.revaluation, 200e6, 0);
    near(r.detail.devaluationDefaults, 1200e6 * 0.04, 0);                  // (1,000 + 200)m x 4% = 48m
    near(r.detail.devaluationProvisions, 48e6 * 0.6, 0);                   // 28.8m
    near(r.after.car, ((246e6 - 28.8e6) / (1985e6 + 200e6)) * 100);        // 9.9405%
    near(r.after.lcr, r.before.lcr, 10);                                   // liquidity untouched
  });

  it("bad loans +5%: gross loans x 5% new defaults, provisions at 60%, RWA unchanged", () => {
    const r = run(only({ nplIncreasePct: 5 }));
    near(r.detail.nplDefaults, 70e6, 0);
    near(r.detail.nplProvisions, 42e6, 0);
    near(r.after.rwa, 1985e6, 0);
    near(r.after.car, ((246e6 - 42e6) / 1985e6) * 100);                    // 10.2771%
  });

  it("rates +2%: floating loans earn 22m more, floating deposits cost 18m more, net +4m to capital", () => {
    const up = run(only({ rateChangePct: 2 }));
    near(up.detail.netInterestDelta, 4e6, 0);
    near(up.after.profitImpact, 4e6, 0);
    near(up.after.car, (250e6 / 1985e6) * 100);
    const down = run(only({ rateChangePct: -2 }));
    near(down.detail.netInterestDelta, -4e6, 0);
    expect(down.after.car).toBeLessThan(down.before.car);
  });

  it("deposit outflow 10%: 100m leaves, LCR = (515 - 100) / 356; capital ratio untouched", () => {
    const r = run(only({ depositOutflowPct: 10 }));
    near(r.detail.outflow, 100e6, 0);
    near(r.after.hqla, 415e6, 0);
    near(r.after.lcr, (415 / 356) * 100);
    near(r.after.car, r.before.car, 10);
  });

  it("an outflow larger than the liquid assets is flagged hard, and LCR floors at 0 (never negative)", () => {
    const thin = { ...SNAP, hqla_usd: 50e6 };
    const r = run(only({ depositOutflowPct: 30 }), thin);                   // 300m out against 50m of HQLA
    expect(r.hqlaExhausted).toBe(true);
    expect(r.after.hqla).toBeLessThan(0);
    expect(r.after.lcr).toBe(0);
  });
});

describe("the combined scenario applies the source document's order and attributes the damage", () => {
  const adverse = run(PRESETS.adverse.inputs);

  it("waterfall steps add up exactly to the change in the capital ratio", () => {
    const total = adverse.steps.reduce((n, s) => n + s.delta, 0);
    near(total, adverse.after.car - adverse.before.car, 9);
  });

  it("each factor only moves its own step, in the documented order", () => {
    const keys = (r) => r.steps.filter((s) => Math.abs(s.delta) > 1e-12).map((s) => s.key);
    expect(adverse.steps.map((s) => s.key)).toEqual(["devaluation", "npl", "rates", "outflow"]);
    expect(keys(run(only({ devaluationPct: 20 })))).toEqual(["devaluation"]);
    expect(keys(run(only({ nplIncreasePct: 5 })))).toEqual(["npl"]);
    expect(keys(run(only({ rateChangePct: 2 })))).toEqual(["rates"]);
    expect(keys(run(only({ depositOutflowPct: 20 })))).toEqual([]);          // liquidity only: no capital step
    expect(adverse.steps.find((s) => s.key === "outflow").note).toMatch(/liquidity only/i);
  });

  it("stresses add up: provisions and profit impact combine", () => {
    const d = adverse.detail;
    near(d.totalProvisions, d.devaluationProvisions + d.nplProvisions, 4);
    near(adverse.after.profitImpact, d.netInterestDelta - d.totalProvisions, 4);
    near(adverse.after.capital, 246e6 + adverse.after.profitImpact, 0);
    near(adverse.after.rwa, 1985e6 + d.rwaIncrease, 0);
  });

  it("severe hurts more than adverse, which hurts more than base", () => {
    const severe = run(PRESETS.severe.inputs);
    expect(severe.after.car).toBeLessThan(adverse.after.car);
    expect(adverse.after.car).toBeLessThan(run(NONE).after.car);
    expect(severe.after.lcr).toBeLessThan(adverse.after.lcr);
    expect(severe.after.surplus).toBeLessThan(adverse.after.surplus);
  });

  it("a shortfall shows as a negative surplus", () => {
    const severe = run(PRESETS.severe.inputs);
    expect(severe.before.surplus).toBeGreaterThan(0);                        // 246m - 12% x 1,985m = 7.8m today
    near(severe.before.surplus, 7.8e6, 0);
    expect(severe.after.surplus).toBeLessThan(0);
  });
});

describe("the 12-month projection", () => {
  it("starts at today's ratio and ends at the stressed ratio, falling steadily", () => {
    const r = run(PRESETS.adverse.inputs);
    expect(r.projection).toHaveLength(13);
    near(r.projection[0].car, r.before.car, 10);
    near(r.projection[12].car, r.after.car, 10);
    for (let m = 1; m <= 12; m++) expect(r.projection[m].car).toBeLessThan(r.projection[m - 1].car);
  });

  it("names the first month below the minimum, converting a percentage into a deadline", () => {
    const r = run(PRESETS.severe.inputs);
    const month = r.breachMonth;
    expect(month).toBeGreaterThan(0);
    expect(r.projection[month].car).toBeLessThan(12);
    expect(r.projection[month - 1].car).toBeGreaterThanOrEqual(12);
  });

  it("no breach means no month; already-breached means month 0", () => {
    // today's cushion is only 7.8m, so even +1% NPL (8.4m of provisions) breaches; +0.5% (4.2m) does not
    expect(run(only({ nplIncreasePct: 1 })).breachMonth).toBe(12);
    expect(run(only({ nplIncreasePct: 0.5 })).breachMonth).toBeNull();
    const already = run(NONE, { ...SNAP, tier1_capital_usd: 150e6, tier2_capital_usd: 30e6 });
    expect(already.breachMonth).toBe(0);
  });

  it("a shorter phase-in reaches the full stress sooner and then stays there", () => {
    const r = run(PRESETS.adverse.inputs, SNAP, { ...A, phaseInMonths: 6 });
    near(r.projection[6].car, r.after.car, 10);
    near(r.projection[12].car, r.after.car, 10);
    expect(r.projection[3].car).toBeGreaterThan(r.after.car);
  });
});

describe("assumptions really drive the answer", () => {
  it("the local currency decides which loans count as foreign", () => {
    const usdLocal = run(only({ devaluationPct: 20 }), SNAP, { ...A, localCurrency: "USD" });
    near(usdLocal.detail.foreignLoans, 500e6, 0);                            // LBP + SAR
    expect(usdLocal.after.car).toBeGreaterThan(run(only({ devaluationPct: 20 })).after.car);
  });

  it("higher coverage means bigger provisions and a lower ratio", () => {
    const thin = run(only({ nplIncreasePct: 5 }), SNAP, { ...A, coveragePct: 30 });
    const heavy = run(only({ nplIncreasePct: 5 }), SNAP, { ...A, coveragePct: 90 });
    expect(heavy.after.car).toBeLessThan(thin.after.car);
  });

  it("the default-uplift rule scales the damage", () => {
    const off = run(only({ devaluationPct: 20 }), SNAP, { ...A, defaultUpliftPerDevaluationPct: 0 });
    expect(off.detail.devaluationDefaults).toBe(0);
    expect(off.after.car).toBeGreaterThan(run(only({ devaluationPct: 20 })).after.car);
  });

  it("a different regulatory minimum changes the surplus and the breach month", () => {
    const strict = run(PRESETS.adverse.inputs, SNAP, { ...A, minimumCarPct: 14 });
    expect(strict.after.surplus).toBeLessThan(run(PRESETS.adverse.inputs).after.surplus);
    expect(strict.breachMonth).toBe(0);                                      // 12.39% is already below a 14% floor
  });
});

describe("the Assumptions panel cannot show a partial list", () => {
  it("every assumption key the engine reads is defined in ASSUMPTION_DEFS", () => {
    const used = new Set([...engineSource.matchAll(/\ba\.([A-Za-z]+)/g)].map((m) => m[1]));
    const defined = new Set(ASSUMPTION_DEFS.map((d) => d.key));
    const undeclared = [...used].filter((k) => !defined.has(k));
    expect(undeclared).toEqual([]);
    expect(used.size).toBeGreaterThanOrEqual(6);
  });

  it("every definition has a default and an explanation", () => {
    for (const d of ASSUMPTION_DEFS) {
      expect(d.default, d.key).not.toBeUndefined();
      expect(d.why.length, d.key).toBeGreaterThan(20);
    }
  });
});

describe("robustness", () => {
  it("does not modify the snapshot or the inputs it is given", () => {
    const freeze = (o) => {
      Object.values(o).forEach((v) => v && typeof v === "object" && freeze(v));
      return Object.freeze(o);
    };
    const snap = freeze(structuredClone(SNAP));
    const inputs = freeze({ ...PRESETS.severe.inputs });
    expect(() => run(inputs, snap)).not.toThrow();
  });

  it("copes with missing rate-type and deposit breakdowns (treated as zero)", () => {
    const bare = { ...SNAP, loans_by_rate_type: null, deposits_by_rate_type: undefined, deposits_by_type: null };
    const r = run(PRESETS.adverse.inputs, bare);
    expect(r.detail.netInterestDelta).toBe(0);
    expect(r.detail.outflow).toBe(0);
    expect(Number.isFinite(r.after.car)).toBe(true);
  });

  it("reports which snapshot fields are missing instead of computing nonsense", () => {
    expect(missingSnapshotFields(SNAP)).toEqual([]);
    expect(missingSnapshotFields(null)).toEqual(["snapshot"]);
    expect(missingSnapshotFields({ ...SNAP, tier1_capital_usd: null })).toContain("tier1_capital_usd");
    expect(missingSnapshotFields({ ...SNAP, risk_weighted_assets_usd: 0 })).toContain("risk_weighted_assets_usd > 0");
    expect(missingSnapshotFields({ ...SNAP, loans_by_currency: null })).toContain("loans_by_currency");
  });

  it("summarise keeps the four comparison figures", () => {
    const r = run(PRESETS.adverse.inputs);
    expect(Object.keys(summarise(r))).toEqual(["carAfter", "lcrAfter", "surplusAfter", "profitImpact"]);
    expect(summarise(r).carAfter).toBe(r.after.car);
  });
});

describe("status colours are judged against the regulatory minimum", () => {
  it("capital and liquidity ratios: red below the floor, amber inside the watch band, green above", () => {
    expect(ratioStatus(11.9, 12, 3)).toBe("action");
    expect(ratioStatus(12, 12, 3)).toBe("watch");
    expect(ratioStatus(14.9, 12, 3)).toBe("watch");
    expect(ratioStatus(15, 12, 3)).toBe("good");
    expect(ratioStatus(null, 12, 3)).toBe("unknown");
  });

  it("surplus: red when negative (a shortfall), amber when thin, green when comfortable", () => {
    expect(surplusStatus(-1, 1985e6, 12, 5)).toBe("action");
    expect(surplusStatus(7.8e6, 1985e6, 12, 5)).toBe("watch");               // 7.8m < 5% of 238.2m required (11.9m)
    expect(surplusStatus(30e6, 1985e6, 12, 5)).toBe("good");
  });
});

describe("data scale", () => {
  it("measures how big the loan book is compared with RWA", () => {
    near(loanBookShare(SNAP), (1400 / 1985) * 100);
    // the real snapshot the pipeline loaded into Neon from bank-data/*.csv: $2.1M of loans against $1.985bn of RWA
    const sample = {
      loans_by_currency: { QAR: 38461.54, SAR: 480000, USD: 1580000 },
      loans_by_rate_type: { fixed: 280000, floating: 1818461.54 },
      deposits_by_type: { Current: 577912.09, Savings: 15464.3, "Term deposit": 91817.35 },
      deposits_by_rate_type: { fixed: 91817.35, floating: 593376.39 },
      tier1_capital_usd: 207e6, tier2_capital_usd: 39e6, risk_weighted_assets_usd: 1985e6,
      hqla_usd: 515e6, net_outflows_30d_usd: 356e6, current_npl_pct: 23.83, current_coverage_pct: 12.75,
    };
    expect(loanBookShare(sample)).toBeLessThan(0.2);                                  // 0.11%
    const severe = computeScenario(sample, PRESETS.severe.inputs, defaultAssumptions(sample));
    // the model is right; the sample loan book is simply too small for a loan-book stress to matter
    expect(Math.abs(severe.after.car - severe.before.car)).toBeLessThan(0.02);   // under two hundredths of a point
    expect(Math.abs(severe.after.lcr - severe.before.lcr)).toBeLessThan(0.5);          // deposits are $1M against $515M of HQLA
  });
});
