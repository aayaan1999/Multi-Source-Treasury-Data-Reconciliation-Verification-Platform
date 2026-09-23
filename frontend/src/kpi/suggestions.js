// What lever would move this KPI, in plain terms - derived directly from the KPI's own formula
// (which component is the numerator vs. denominator, and this KPI's direction), quoting the real
// current numbers from its /breakdown response. No AI: every sentence here is a fixed template per
// KPI, filled in with live data - the "suggestion" is the formula read backwards, not generated advice.

function find(components, substr) {
  const c = components.find((c) => c.label.includes(substr));
  return c ? c.formatted : "—";
}

const SUGGESTIONS = {
  car_pct: (c) =>
    `CAR rises with (Tier 1 + Tier 2 capital) ÷ risk-weighted assets. Raising Tier 1 capital ` +
    `(currently ${find(c, "Tier 1")}) or Tier 2 capital (currently ${find(c, "Tier 2")}), or shifting toward ` +
    `lower-risk-weight exposures to bring down risk-weighted assets (currently ${find(c, "Risk-weighted")}), would improve it.`,
  lcr_pct: (c) =>
    `LCR rises with HQLA ÷ 30-day net cash outflows. Building up high-quality liquid assets ` +
    `(currently ${find(c, "HQLA")}) or reducing projected 30-day net cash outflows ` +
    `(currently ${find(c, "Net cash outflows")}) would improve it.`,
  npl_ratio_pct: (c) =>
    `The NPL ratio falls as loans 90+ days past due (currently ${find(c, "90+")}) shrink relative to total loans ` +
    `outstanding (currently ${find(c, "Total loans")}). Collections/recovery or restructuring on the past-due book, ` +
    `or growing the performing loan book, would improve it.`,
  nim_pct: (c) =>
    `NIM rises with interest income minus interest paid on deposits, relative to loans outstanding. Growing interest ` +
    `income (currently ${find(c, "Interest income")}) - loan growth or rate repricing - or shifting the deposit mix ` +
    `toward lower-cost account types to reduce interest paid on deposits (currently ${find(c, "Interest paid")}) would improve it.`,
  cost_to_income_pct: (c) =>
    `Cost-to-income falls as branch operating expense (currently ${find(c, "operating expense")}) shrinks relative to ` +
    `revenue - interest income (${find(c, "Interest income")}) plus fee income (${find(c, "Fee income")}). Cutting opex ` +
    `or growing either revenue line would improve it.`,
  roe_pct: (c) =>
    `ROE rises with profit (currently ${find(c, "Profit")}) relative to Tier 1 capital, used here as the equity base ` +
    `(currently ${find(c, "Tier 1")}). Growing revenue or cutting operating expense to raise profit would improve it.`,
  dollarization_ratio_pct: (c) =>
    `The dollarization ratio falls as non-LBP account balances (currently ${find(c, "Non-LBP")}) shrink relative to ` +
    `total account balances (currently ${find(c, "Total account")}). Growing the LBP-denominated deposit base would improve it.`,
};

/** null when this KPI has no fix-it lever worth suggesting (total_assets_usd has no target - it's tracked for scale only). */
export function suggestionFor(key, components) {
  const fn = SUGGESTIONS[key];
  return fn ? fn(components) : null;
}
