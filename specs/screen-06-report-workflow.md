# Spec: Screen 6 — Report Workflow

**Status:** Spec only — not yet implemented
**Plan reference:** `3-WEEK-POC-PLAN.md` — **not shallow-scoped like Screens 1-5**, this is the
direct replacement for the original brief's exception workflow and the main new capability the
3-week Camunda extension is about
**Depends on:** `specs/camunda-bpmn-process-design.md` (the actual workflow engine — Screen 6 is
a UI over Camunda, not its own workflow implementation), `specs/fastapi-backend.md` section 2.6

---

## 1. Objective

Whoever logs in sees only what's waiting for them, reviews it, and takes action with a mandatory
comment — the difference between a dashboard and a system people actually use, per the source doc.

## 2. Sections

1. **My Tasks landing view**: task / report-or-transaction / period / assigned / due / priority,
   sourced from **Camunda Tasklist's API** (`GET` against Tasklist, filtered to the logged-in
   user's candidate groups — `fraud-investigation`/`compliance`/`operations` per
   `specs/camunda-bpmn-process-design.md` section 3's `flagCategory` routing), not a Postgres
   query — Camunda is the source of truth for "what's open," per `specs/postgres-schema.md`
   section 2.4's note
2. **Approval chain, visual**: horizontal steps (Prepared → Reviewed → Approved → Submitted, or
   the FRAUD/COMPLIANCE/OPERATIONS-specific variant per the BPMN process), green tick/clock/empty
   circle, who and when — driven by the current task's process-instance state (Zeebe/Operate),
   surfaced through Tasklist's API where possible
3. **Review screen**: full record detail (joined from `data_quality_exceptions`/
   `flagged_transactions` plus the underlying source row), a comment thread (`POST
   /api/v1/exceptions/{id}/comments`), and the actual action buttons —
   **Approve / Reject / Corrected-with-mandatory-comment** — submitted directly to **Camunda's
   Tasklist API** to complete the task, per `CLAUDE.md`'s Workflow Engine Decision (not a FastAPI
   endpoint)
4. **Breach alerts**: auto-created from Phase 1's `limits`/`breaches` tables — a nightly job
   compares calculated metrics against thresholds and creates a task automatically; this becomes
   another `flagCategory`-routed Camunda process instance, not a separate alert system
5. **Audit trail**: `audit_log`, insert-only (DB grants enforce this — no `UPDATE`/`DELETE`
   permission on the table, per `CLAUDE.md`), filterable by date/entity/user/action type. Every
   comment and every task completion writes a row here, mirroring what Camunda/Zeebe already
   tracked internally — this is the human-readable, permanently-queryable version
6. **Small management view**: on-time vs. late submission rate, average time per approval stage
   (surfaces bottlenecks — usually one person), open breaches by age — aggregated from
   `audit_log`/Tasklist data, built last since it's the least load-bearing part of this screen for
   the demo narrative

## 3. Why This Screen Isn't Shallow-Scoped

Unlike Screens 1-5 (which are cut down to single-snapshot data due to volume/history
constraints), Screen 6 works fully against real, currently-flowing data
(`data_quality_exceptions`, `flagged_transactions`) — there's no historical-depth problem to work
around here. Build it to the spec, not a reduced version.

## 4. Acceptance Criteria

- [ ] My Tasks view correctly filters to the logged-in user's candidate group(s)
- [ ] Completing a task (Approve/Reject/Corrected) via this screen actually completes the Camunda
      task — verified in Operate/Tasklist, not just optimistically updated in the frontend
- [ ] A "Corrected" action's new value round-trips into `review_outcomes`
      (`specs/bidirectional-sync.md`) correctly, including the corrected field and value
- [ ] `audit_log` gains a row for every comment and every task completion, with no gaps
- [ ] Not yet implemented

## 5. Non-Goals

- No workflow logic implemented in this screen or the FastAPI backend — Camunda owns process
  state, this screen only displays and acts on it
- No custom notification system (email/SMS on task assignment) — out of scope for the demo
