// Scenario engine (Screen 4). Pure functions: the browser fetches today's position ONCE (the "snapshot", ~50 numbers) and
// every slider move recomputes against it here, so there is no backend call per slider tick.
//
// Calculation order follows the source document exactly (these steps interact, so the order matters):
//   1. devaluation revalues the foreign-currency loan book        2. ...and pushes some of it into default
//   3. independent bad-loan (NPL) stress                          4. new provisions on both sets of defaults
//   5. interest-rate change on floating-rate loans and deposits   6. capital falls by the total loss, RWA rises
//                                                                     by the revaluation, capital ratio recomputed
//   7. separately: deposit outflow reduces liquid assets, liquidity ratio recomputed
import { isNum } from "../kpi/format";

// ---- slider ranges and presets (illustrative; the source document says to confirm the real ones with the client) -------
export const SLIDERS = [
  { key: "devaluationPct", label: "Currency devaluation", unit: "%", min: 0, max: 50, step: 1,
    hint: "The local currency loses value against the dollar. Dollar loans balloon in local terms; capital doesn't." },
  { key: "rateChangePct", label: "Interest-rate change", unit: "%", min: -5, max: 5, step: 0.5,
    hint: "Deposits reprice quickly; many loans don't. Only floating-rate balances move." },
  { key: "nplIncreasePct", label: "Bad loans increase", unit: "%", min: 0, max: 15, step: 0.5,
    hint: "A recession or a major customer failing: more loans go unpaid." },
  { key: "depositOutflowPct", label: "Deposit outflow", unit: "%", min: 0, max: 30, step: 1,
    hint: "Customers withdraw money. A liquidity event, not a capital one." },
];

export const PRESETS = {
  base: { label: "Base", inputs: { devaluationPct: 0, rateChangePct: 0, nplIncreasePct: 0, depositOutflowPct: 0 } },
  adverse: { label: "Adverse", inputs: { devaluationPct: 20, rateChangePct: 2, nplIncreasePct: 5, depositOutflowPct: 10 } },
  severe: { label: "Severe", inputs: { devaluationPct: 40, rateChangePct: 4, nplIncreasePct: 10, depositOutflowPct: 20 } },
};

// ---- every assumption the maths uses -----------------------------------------------------------------------------------
// The Assumptions panel renders THIS list, and the engine reads ONLY from an assumptions object with these keys, so the
// panel cannot show a partial list (a test checks that every key the engine reads is defined here).
export const ASSUMPTION_DEFS = [
  { key: "localCurrency", label: "Local (reporting) currency", type: "text", default: "LBP",
    why: "Loans in any other currency are 'foreign' and are revalued when the local currency devalues. LBP is what the dollarization KPI treats as local (Notebook 3)." },
  { key: "defaultUpliftPerDevaluationPct", label: "Extra foreign-loan defaults per 1% devaluation (percentage points)", type: "number", unit: "pp", default: 0.2, step: 0.05,
    why: "Source document: a 20% devaluation pushes an extra 3–5% of foreign-currency loans into default. 0.2 × 20 = 4%, the middle of that range." },
  { key: "coveragePct", label: "Provision coverage on new bad loans", type: "number", unit: "%", default: 70, step: 1, derivedFromSnapshot: true,
    why: "Provisions set aside per $ of new bad loans. Defaults to the bank's current coverage of its bad loans (provisions ÷ NPL amount) when the snapshot allows, otherwise the source document's 70%." },
  { key: "revaluedRiskWeightPct", label: "Risk weight on revalued foreign loans", type: "number", unit: "%", default: 100, step: 5,
    why: "Risk-weighted assets rise by the revalued loan amounts. 100% is the standard weight for unsecured lending." },
  { key: "phaseInMonths", label: "Months over which the stress phases in (projection)", type: "number", unit: "months", default: 12, step: 1,
    why: "The 12-month projection applies the total stress in equal steps over this many months. A modelling choice, not sourced from the data." },
  { key: "minimumCarPct", label: "Regulatory minimum capital ratio", type: "number", unit: "%", default: 12, step: 0.5,
    why: "The floor the capital ratio is judged against. Same 12% used for Screen 1 and the Capital Adequacy return." },
  { key: "minimumLcrPct", label: "Regulatory minimum liquidity ratio (LCR)", type: "number", unit: "%", default: 100, step: 5,
    why: "The Basel liquidity floor." },
  { key: "carWatchPoints", label: "Capital ratio 'watch' band above the minimum", type: "number", unit: "points", default: 3, step: 0.5,
    why: "Result boxes turn amber when the capital ratio is above the minimum by less than this." },
  { key: "lcrWatchPoints", label: "Liquidity ratio 'watch' band above the minimum", type: "number", unit: "points", default: 20, step: 5,
    why: "Result boxes turn amber when the liquidity ratio is above the minimum by less than this." },
  { key: "surplusWatchPct", label: "Capital surplus 'watch' band (% of required capital)", type: "number", unit: "%", default: 5, step: 1,
    why: "The surplus box turns amber when the cushion above the requirement is thinner than this share of required capital." },
];

// Shown read-only next to the editable ones: assumptions already baked into the pipeline's snapshot (notebooks/06).
export const PIPELINE_ASSUMPTIONS = [
  { label: "PRODUCT_RATE_TYPE", value: "Mortgage: fixed · Personal: fixed · SME: floating · Corporate: floating",
    why: "Decides which loans reprice when rates move. An assumption, not sourced from the schema or the brief: confirm with the client." },
  { label: "ACCOUNT_RATE_TYPE", value: "Current: floating · Savings: floating · Term deposit: fixed",
    why: "Decides which deposits reprice. Same caveat." },
  { label: "Snapshot currencies", value: "Loan and deposit amounts are converted to USD at the live rate on the run date",
    why: "So devaluation is applied to USD-valued balances by currency of origin." },
];

export const NOT_MODELLED = [
  "Floating-rate borrowers defaulting more when rates rise (the source document mentions it; its calculation list doesn't include it).",
  "Tax, dividends, new lending or retained earnings during the projection.",
  "Second-round effects (for example a deposit outflow forcing asset sales at a loss).",
];

export function defaultAssumptions(snapshot) {
  const defaults = Object.fromEntries(ASSUMPTION_DEFS.map((d) => [d.key, d.default]));
  const npl = snapshot?.current_npl_pct;
  const coverageOnAll = snapshot?.current_coverage_pct;
  // The snapshot's coverage is provisions over ALL loans; the coverage that matters for a *new* bad loan is provisions over
  // BAD loans, i.e. that figure divided by the NPL ratio (the same definition Screen 2 shows).
  if (isNum(npl) && npl > 0 && isNum(coverageOnAll) && coverageOnAll > 0) {
    defaults.coveragePct = Math.min(100, (coverageOnAll / npl) * 100);
  }
  return defaults;
}

const REQUIRED_NUMBERS = ["tier1_capital_usd", "tier2_capital_usd", "risk_weighted_assets_usd", "hqla_usd", "net_outflows_30d_usd"];

/** Names of snapshot fields the engine cannot work without (empty list = fine). */
export function missingSnapshotFields(snapshot) {
  if (!snapshot) return ["snapshot"];
  const missing = REQUIRED_NUMBERS.filter((k) => !isNum(snapshot[k]));
  if (isNum(snapshot.risk_weighted_assets_usd) && snapshot.risk_weighted_assets_usd <= 0) missing.push("risk_weighted_assets_usd > 0");
  if (isNum(snapshot.net_outflows_30d_usd) && snapshot.net_outflows_30d_usd <= 0) missing.push("net_outflows_30d_usd > 0");
  if (!snapshot.loans_by_currency || typeof snapshot.loans_by_currency !== "object") missing.push("loans_by_currency");
  return missing;
}

const sumValues = (obj) => Object.values(obj ?? {}).reduce((n, v) => n + (isNum(v) ? v : 0), 0);
const ratio = (numerator, denominator) => (denominator > 0 ? (numerator / denominator) * 100 : null);

/**
 * Applies a stress to today's position. `inputs` = { devaluationPct, rateChangePct, nplIncreasePct, depositOutflowPct }
 * (whole percents); `a` = an assumptions object (see ASSUMPTION_DEFS). All money is USD.
 */
export function computeScenario(snapshot, inputs, a) {
  const d = inputs.devaluationPct / 100;
  const rate = inputs.rateChangePct / 100;
  const npl = inputs.nplIncreasePct / 100;
  const outflowShare = inputs.depositOutflowPct / 100;
  const coverage = a.coveragePct / 100;

  const grossLoans = sumValues(snapshot.loans_by_currency);
  const foreignLoans = Object.entries(snapshot.loans_by_currency).reduce((n, [ccy, v]) => n + (ccy !== a.localCurrency && isNum(v) ? v : 0), 0);
  const floatingLoans = snapshot.loans_by_rate_type?.floating ?? 0;
  const floatingDeposits = snapshot.deposits_by_rate_type?.floating ?? 0;
  const totalDeposits = sumValues(snapshot.deposits_by_type);

  const capital = snapshot.tier1_capital_usd + snapshot.tier2_capital_usd;
  const rwa = snapshot.risk_weighted_assets_usd;
  const hqla = snapshot.hqla_usd;
  const netOutflows = snapshot.net_outflows_30d_usd;

  // 1-2  devaluation: the foreign book grows in local terms, and a share of it defaults
  const revaluation = foreignLoans * d;
  const rwaIncrease = revaluation * (a.revaluedRiskWeightPct / 100);
  const devaluationDefaultShare = (a.defaultUpliftPerDevaluationPct * inputs.devaluationPct) / 100;
  const devaluationDefaults = (foreignLoans + revaluation) * devaluationDefaultShare;
  // 3    independent bad-loan stress, on the unstressed book
  const nplDefaults = grossLoans * npl;
  // 4    provisions on both
  const devaluationProvisions = devaluationDefaults * coverage;
  const nplProvisions = nplDefaults * coverage;
  const totalProvisions = devaluationProvisions + nplProvisions;
  // 5    rates: floating loans earn more, floating deposits cost more
  const netInterestDelta = floatingLoans * rate - floatingDeposits * rate;
  // 6    losses come out of capital; the revalued book adds to RWA
  const profitImpact = netInterestDelta - totalProvisions;
  const capitalAfter = capital + profitImpact;
  const rwaAfter = rwa + rwaIncrease;

  const min = a.minimumCarPct / 100;
  const car = ratio(capital, rwa);
  const carAfter = ratio(capitalAfter, rwaAfter);
  const surplus = capital - min * rwa;
  const surplusAfter = capitalAfter - min * rwaAfter;

  // 7    liquidity: outflow uses up liquid assets one-for-one
  const outflow = totalDeposits * outflowShare;
  const hqlaAfter = hqla - outflow;
  const lcr = ratio(hqla, netOutflows);
  const lcrAfter = ratio(Math.max(0, hqlaAfter), netOutflows);

  // Waterfall: today's capital ratio, then the drop each factor causes, in calculation order.
  const afterDevaluation = ratio(capital - devaluationProvisions, rwa + rwaIncrease);
  const afterNpl = ratio(capital - devaluationProvisions - nplProvisions, rwa + rwaIncrease);
  const afterRates = ratio(capital - totalProvisions + netInterestDelta, rwa + rwaIncrease);
  const steps = [
    { key: "devaluation", label: "Currency devaluation", delta: afterDevaluation - car },
    { key: "npl", label: "Bad loans increase", delta: afterNpl - afterDevaluation },
    { key: "rates", label: "Interest-rate change", delta: afterRates - afterNpl },
    { key: "outflow", label: "Deposit outflow", delta: 0, note: "Affects liquidity only, not the capital ratio" },
  ];

  // 12-month projection: the total stress phases in evenly over `phaseInMonths`.
  const phase = Math.max(1, a.phaseInMonths);
  const projection = Array.from({ length: 13 }, (_, month) => {
    const f = Math.min(1, month / phase);
    return { month, car: ratio(capital + f * profitImpact, rwa + f * rwaIncrease) };
  });
  const breach = projection.find((p) => p.car !== null && p.car < a.minimumCarPct);

  return {
    before: { car, lcr, surplus, capital, rwa, hqla },
    after: { car: carAfter, lcr: lcrAfter, surplus: surplusAfter, capital: capitalAfter, rwa: rwaAfter, hqla: hqlaAfter, profitImpact },
    detail: {
      grossLoans, foreignLoans, revaluation, rwaIncrease, devaluationDefaults, nplDefaults, devaluationProvisions,
      nplProvisions, totalProvisions, netInterestDelta, totalDeposits, outflow, floatingLoans, floatingDeposits,
    },
    steps,
    projection,
    breachMonth: breach ? breach.month : null,
    hqlaExhausted: hqlaAfter < 0,
  };
}

/** Loans as a % of risk-weighted assets. Stress applied to a loan book that is a sliver of RWA can barely move the ratio. */
export function loanBookShare(snapshot) {
  return ratio(sumValues(snapshot.loans_by_currency), snapshot.risk_weighted_assets_usd);
}

/** "good" | "watch" | "action" against a floor with a watch band above it (used for the capital and liquidity ratios). */
export function ratioStatus(value, minimum, watchBand) {
  if (!isNum(value)) return "unknown";
  if (value < minimum) return "action";
  return value < minimum + watchBand ? "watch" : "good";
}

export function surplusStatus(surplus, rwa, minimumPct, watchPct) {
  if (!isNum(surplus)) return "unknown";
  if (surplus < 0) return "action";
  const required = (minimumPct / 100) * rwa;
  return surplus < (watchPct / 100) * required ? "watch" : "good";
}

/** The four figures the comparison table keeps for a scenario (also what gets saved with it). */
export function summarise(result) {
  return {
    carAfter: result.after.car,
    lcrAfter: result.after.lcr,
    surplusAfter: result.after.surplus,
    profitImpact: result.after.profitImpact,
  };
}
