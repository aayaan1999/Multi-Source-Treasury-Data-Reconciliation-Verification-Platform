-- Suspicious-pattern rules (client point 5: FRD-2/FRD-3, specs/notebook-05-fraud-business-rules.md):
-- allows Notebook 5's five new flag labels in flagged_transactions, and seeds the rule thresholds in
-- app_settings['fraud.rules'] (read by Notebook 5; placeholder values until the bank gives its AML
-- typologies). Needs migration 012 (app_settings). Keeps a value already changed. Safe to run more
-- than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/013_fraud_rules.sql
BEGIN;

DO $$
DECLARE
    con text;
BEGIN
    SELECT conname INTO con FROM pg_constraint
    WHERE conrelid = 'flagged_transactions'::regclass AND contype = 'c'
      AND pg_get_constraintdef(oid) LIKE '%flag_label%';
    IF con IS NOT NULL THEN
        EXECUTE format('ALTER TABLE flagged_transactions DROP CONSTRAINT %I', con);
    END IF;
END $$;

ALTER TABLE flagged_transactions ADD CONSTRAINT flagged_transactions_flag_label_check CHECK (flag_label IN (
    'LARGE_AMOUNT', 'VELOCITY_BREACH', 'STRUCTURING_PATTERN', 'DUPLICATE_TRANSACTION',
    'DORMANT_REACTIVATION', 'PASS_THROUGH', 'UNUSUAL_FOR_SEGMENT', 'ROUND_AMOUNTS', 'SPLIT_ACROSS_ACCOUNTS'));

INSERT INTO app_settings (key, value, description) VALUES
    ('fraud.rules',
     '{"large_amount_usd": 50000, "velocity_count": 2, "structuring_lower": 8500, "structuring_upper": 10000,
       "dormant_days": 180, "dormant_min_usd": 10000, "pass_through_window_days": 1, "pass_through_min_share": 0.9,
       "pass_through_min_usd": 10000, "segment_multiplier": 10, "segment_min_usd": 5000, "round_step": 1000,
       "round_min_usd": 5000, "round_min_count": 3, "split_min_accounts": 2}',
     'Thresholds for Notebook 5''s transaction rules (large amount, velocity, structuring, dormant account, pass-through, unusual for segment, round amounts, split across accounts)')
ON CONFLICT (key) DO NOTHING;

COMMIT;
