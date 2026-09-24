# Spec: Duplicate Companies ("TCS" = "Tata Consultancy Services") (client point 3: DUP-1..4)

**Status:** Implemented 2026-09-24 — `db/migrations/015_entity_matching.sql`, `camunda/bridge/duplicates_db.py`
(+ poll/outcome workers), `GET /api/v1/workflow/entity-matches/{id}`, the review popup, Notebook 6's
top exposures per group. Tested locally; **not yet run against Camunda, Neon or a cluster.**
**Backlog:** DUP-1..4 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`.

## 1. Problem

Customers were matched only by ID: one company recorded twice (under two names) showed as two
smaller customers, so its exposure, the top-20 list and concentration were understated.

## 2. Finding likely duplicates (DUP-1, DUP-2)

- **Clean each name:** upper case; dots dropped ("S.A.L." → "SAL"); other punctuation splits words;
  legal words removed (SAL, SARL, LTD, LLC, INC, PLC, CO, CORP, WLL, FZE, ...); a known abbreviation
  expanded ("TCS" → "TATA CONSULTANCY SERVICES").
- **Score each pair:** 1.0 for the same cleaned name; 0.95 when one is the other's initials; otherwise
  how alike the cleaned names are (difflib ratio). Shared branch, country or segment are listed as
  reasons for the reviewer but **never** make two different names a match on their own (so "Aoun
  Industries" and "Aoun Capital" stay apart).
- Pairs at or above `min_score` (0.85) are saved once as candidates (`entity_match_candidates`),
  with the score and reasons. A pair already pending or decided is never raised again.
- Settings `app_settings['dedup.matching']` (min score, legal words, abbreviations): placeholders.
  The bank's **commercial registration number** would make matches reliable; the data has no such
  field today, so matching is name-based.
- Run by the bridge on every poll, comparing within blocks (same first letter of the cleaned name) —
  fine at demo scale; at millions of customers this belongs in Databricks.

## 3. A person decides every pair (DUP-3)

Each candidate becomes a task (`transaction-review`, `recordType = "entity_match"`, Operations for now,
due in `task.due_days.DUPLICATE` = 10 days). The popup shows both records side by side (name, segment,
branch, country, onboarding, risk rating, loans per currency) and why they were matched. **Same
company** (Approved) or **Different companies** (Rejected), with a mandatory comment; audited.
**Nothing is merged automatically, and the customer records are never changed.**

## 4. Exposure per group (DUP-4)

After each decision, `customer_entity` is rebuilt from every confirmed pair: connected customers form
one group led by the lowest customer id. Notebook 6 reads it from Neon (best-effort) and computes the
top 20 exposures **per group**: outstanding added up, named after the lead record, with
`linked_customer_ids` listing the others; the Portfolio screen shows "+ linked record CN0107". Takes
effect on the next pipeline run (or Refresh Now). Original records are untouched, so a link can be
undone by reversing the decision.

## 5. Open items

1. The bank's company identifier (commercial registration / tax number) and its abbreviation list.
2. Who owns duplicate reviews (Operations is a placeholder) and the deadline.
3. Concentration limits and segment totals still count records, not groups; only top exposures group today.

## 6. Acceptance criteria

- [x] Cleaning, scoring, candidates once, decisions, groups (backend tests)
- [x] Review popup, decision with comment (vitest)
- [x]/[ ] Notebook 6 top exposures per group — implemented; not run on a cluster
- [ ] Run live with planted duplicates in the demo data
