# Spec: Core-System Reconciliation, Grouped by Cause (client point 1: REC-1..5, 7, 8)

**Status:** Implemented 2026-09-24 — `db/migrations/016_reconciliation_groups.sql`, the reconciliation
notebook and the load, `camunda/bridge/recon_groups_db.py` + `reconciliation-group-review.bpmn`,
backend endpoints, the Tasks popup and the Reconciliation tab's core-system section. Tested locally;
**not yet run against Camunda, Neon or a cluster.** Transaction-level matching (REC-6) stays blocked
on a transaction export from the bank.
**Backlog:** point 1 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md`. Separate from
`specs/pipeline-reconciliation.md` (received vs kept), which has its own CFO workflow.

## 1. Problem

"Reconciliation can't be done one by one." Every difference between our data and the core system
was a row resolved alone in a popup — 1,417 of them at one point.

## 2. Automatic clearing (REC-1)

In `multi_source_reconciliation.py`: numeric differences within the tolerance ($1) aren't recorded;
a text difference that disappears once case, spaces and punctuation are ignored ("AL-HASSAN" vs
"Al Hassan") is recorded as `AUTO_ACCEPTED` with `resolved_rule = FORMATTING_ONLY` — visible,
filterable, never a task.

## 3. Groups by cause (REC-2) and safety rules (REC-3)

The bridge groups every `OPEN` break not yet in a group (`app_settings['recon.rules']`, placeholders):

- **Important → always a group of one, never bulk:** a missing record, a key field (name, currency,
  type, segment), or a difference ≥ 10,000. Due in 1 day, severity High.
- **The rest group by** source + record type + field + mismatch + pattern. Pattern = the exact
  difference ("+15.00") when at least 3 breaks share it, else a size band ("difference 100-1,000").
  Split at 1,000 breaks per group. Due in `task.due_days.RECON_GROUP` (3).
- **Second approval:** a bulk group whose total absolute difference is ≥ 100,000 needs a second
  person (the CFO) to approve the decision before it takes effect.
- A carved-out break becomes a group of one next poll.

## 4. Group tasks (REC-4): `reconciliation-group-review`

```
Review group (owning team) ─► second approval needed? ── no ──► write decision ─► end
                                        └── yes ─► Second approval (CFO) ── approve ──┘
                                                         └── return ─► back to Review group
```

The reviewer sees the group's summary and every break; decides **Accept / Correct our data /
Dismiss** for all of them, optionally **leaving some out** ("Accept all except 3"), with a mandatory
comment. The outcome worker applies the decision to every open break in the group except the
carve-outs, one audit row per break (`reconciliation_exception`, "group #N"). Owning team:
Operations until the bank names one (`recon.rules.owner_team`).

## 5. Ageing and recurring breaks (REC-5)

- The notebook updates `last_seen` and `times_seen` on a break it finds again; `first_seen` is kept.
- The load reopens a break a person had resolved (Accepted / Corrected / Dismissed) if it's seen
  again after that decision: status `OPEN`, `recurring = true`, out of its old group — a new task,
  never silently re-accepted. Auto-cleared breaks aren't reopened (a formatting difference persists).
- **Bug fixed:** missing-record breaks (no field) were re-inserted on every load, because the old
  unique key treated empty field names as all different. Migration 016 removes the duplicates
  (keeping the oldest, reviewed row) and the key is now `UNIQUE NULLS NOT DISTINCT`.

## 6. Run sign-off (REC-7)

The latest run of a source (its breaks' last-seen date): a preparer submits it (a note is required
while important breaks are still open); the CFO/approver or an admin — never the preparer — signs
it off or returns it with a reason. Audited (`reconciliation_run`).

## 7. The Reconciliation tab (REC-8)

The core-system section becomes the overview: the latest run (breaks, auto-cleared, open groups,
important open, recurring) with its sign-off; the groups (with where each is decided); every break
with type tabs, status (including "Cleared automatically"), "Recurring only", age and times seen,
and CSV export. Decisions are made in Tasks; the per-break resolve remains only as an **admin
override** (the backend refuses it for anyone else).

## 8. Open items

1. Tolerances, key fields, the important amount, the second-approval total and the owning team.
2. The notebook isn't in the nightly job (it needs the demo core-system Neon project and its own
   secret scope); run it by hand until the core system feed is real.
3. REC-6 transaction-level matching needs a transaction export from core banking.

## 9. Acceptance criteria

- [x] Grouping, important singles, second-approval flag, decisions with carve-outs, idempotent (backend tests)
- [x] Recurring reopen, auto-cleared stays, no duplicate missing-record breaks (load test)
- [x] Run sign-off rules and admin-only override (backend tests)
- [x] Group popup, carve-outs, second approval; tab helpers (vitest)
- [x]/[ ] Notebook auto-clearing and seen-again updates — implemented; not run on a cluster
- [ ] Run live against Camunda and the demo core system
