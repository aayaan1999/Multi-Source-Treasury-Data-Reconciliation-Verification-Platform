-- Ask a question history (specs/ask-a-question.md): each user's recent answers, saved on the server
-- so they come back after logging out and in again (they used to live only in the browser tab and
-- were wiped on every login). Only ever read by the user who asked; the backend keeps the newest 20
-- per user. audit_log still records every question permanently, separately from this list.
-- Safe to run more than once. db/schema.sql already contains this for fresh installs. Apply with:
--   python db/apply_migration.py db/migrations/017_ask_history.sql
BEGIN;

CREATE TABLE IF NOT EXISTS ask_history (
    history_id  bigserial PRIMARY KEY,
    user_id     integer NOT NULL REFERENCES users (user_id) ON DELETE CASCADE,
    answer      jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ask_history_user_idx ON ask_history (user_id, history_id DESC);

COMMIT;
