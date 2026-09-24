-- Relabels flagged_transactions.flag_type from FRAUD / FAULT to THRESHOLD / SUSPICIOUS / OPERATIONAL
-- (client feedback 2026-09-23, FRD-1 in project-docs/CLIENT-FEEDBACK-BACKLOG.md: a large amount
-- alone is not fraud). Same label -> type mapping as FLAG_TYPE_BY_LABEL in
-- notebooks/05_fraud_business_rules.py. Only flag_type changes: status (the reviewer's decision)
-- is left as it is. Robust to whatever Postgres auto-named the inline CHECK constraint. Safe to
-- run more than once. db/schema.sql already contains this for fresh installs.
--
-- Apply AFTER the updated Notebook 5 is in Databricks: from then on the Postgres load only sends
-- the new values, and this CHECK rejects the old ones. Apply with:
--   python db/apply_migration.py db/migrations/006_flag_type_categories.sql
BEGIN;

DO $$
DECLARE
    con text;
BEGIN
    SELECT conname INTO con FROM pg_constraint
    WHERE conrelid = 'flagged_transactions'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%flag_type%';
    IF con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE flagged_transactions DROP CONSTRAINT %I', con);
    END IF;
END $$;

UPDATE flagged_transactions SET flag_type = CASE flag_label
    WHEN 'LARGE_AMOUNT'          THEN 'THRESHOLD'
    WHEN 'VELOCITY_BREACH'       THEN 'SUSPICIOUS'
    WHEN 'STRUCTURING_PATTERN'   THEN 'SUSPICIOUS'
    WHEN 'DUPLICATE_TRANSACTION' THEN 'OPERATIONAL'
END
WHERE flag_type IN ('FRAUD', 'FAULT');

ALTER TABLE flagged_transactions ADD CONSTRAINT flagged_transactions_flag_type_check
    CHECK (flag_type IN ('THRESHOLD', 'SUSPICIOUS', 'OPERATIONAL'));

COMMIT;
