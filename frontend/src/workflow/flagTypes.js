// What kind of alert each Notebook 5 rule raises, and why it matters, in the bank's words (FRD-1 in
// project-docs/CLIENT-FEEDBACK-BACKLOG.md: a large amount alone is not fraud). Keyed by flag label,
// not by the task's flagType variable, so tasks started before the relabel (flagType "FRAUD") show
// the new wording too. Must match FLAG_TYPE_BY_LABEL in notebooks/05_fraud_business_rules.py.
export const TRANSACTION_FLAGS = {
  LARGE_AMOUNT: {
    type: "Threshold",
    reason: "The amount is above the reporting limit. That is a reporting event, not a sign of fraud on its own.",
  },
  VELOCITY_BREACH: {
    type: "Suspicious",
    reason: "Unusually many transactions on one account in a single day. Worth checking for unusual activity.",
  },
  STRUCTURING_PATTERN: {
    type: "Suspicious",
    reason: "Several amounts just under a reporting limit on the same day, a known money-laundering pattern (structuring).",
  },
  DUPLICATE_TRANSACTION: {
    type: "Operational",
    reason: "The same transaction appears to be recorded twice. A processing error to correct, not a customer concern.",
  },
};

const RECORD_TYPE_ALERT = { data_quality: "Data quality", breach: "Breach", reconciliation: "Reconciliation" };

/** The Tasks list's "Type" cell: Threshold / Suspicious / Operational for a transaction alert,
 * otherwise Data quality or Breach. */
export function alertType(vars) {
  if (vars.recordType === "fraud") return TRANSACTION_FLAGS[vars.flagLabel]?.type || "Transaction alert";
  return RECORD_TYPE_ALERT[vars.recordType] || vars.recordType;
}
