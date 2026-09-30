# User roles: who uses the platform, what each person sees, and the demo logins

**Status:** Draft for discussion (2026-09-30). Nothing built yet. Replaces the four generic demo logins
(analyst, reviewer, approver, admin) with the people a Middle Eastern bank would actually put on this
platform, each with their own home screen and a shorter menu.

> **Security warning.** The GitHub repository is **public**. The passwords in section 5 are published the
> moment this file is pushed. They are demo passwords for demo data only: never reuse them anywhere, never
> put real bank data behind them, and change them (section 6) before the app is hosted anywhere others can
> reach it. An admin login can connect source systems and start the Databricks pipeline.

## 1. The problem

Every login sees all 11 screens and every task, whatever their job. A reconciliation analyst sees scenario
modelling; the CFO's task list is mixed with data-quality flags; four logins called "analyst", "reviewer",
"approver" and "admin" don't tell a demo audience who does what. The approval rules (two different people,
CFO approval, run sign-off) are also hard to show when everyone looks the same.

## 2. The people

Seven users, each a real job at the bank, each tied to the work the platform already does:

| # | User | Does in the platform | Home screen | Role (permissions) |
|---|---|---|---|---|
| 1 | **Chief Financial Officer (CFO)** | Watches the headline ratios; approves important reconciliation tasks and data fixes; signs off each reconciliation run; gives final approval on regulatory returns; can start a data refresh | Executive summary | approver |
| 2 | **Chief Risk Officer (CRO)** | Owns credit risk and limits: portfolio, IFRS 9 staging, stress scenarios; handles limit-breach tasks; reviews regulatory returns before the CFO | Portfolio & credit risk | risk (new) |
| 3 | **Reconciliation Analyst** (Operations team) | Decides reconciliation tasks (rows not loaded, data differs), data-quality flags and possible duplicate customers; enters corrected values | Tasks, filtered to reconciliation | analyst |
| 4 | **Regulatory Reporting Officer** | Prepares the regulator's returns, runs validation checks, exports PDF/Excel, answers review comments | Regulatory reporting | preparer (new) |
| 5 | **Compliance Officer** (AML / fraud) | Investigates suspicious and threshold transaction cases | Tasks, filtered to transaction cases | compliance (new) |
| 6 | **Internal Auditor** | Reads everything, changes nothing: audit trail, approvals, who decided what | Audit & Oversight | auditor (new, read-only) |
| 7 | **Platform Administrator** (IT) | Connects source systems, runs the pipeline, manages users; can override a single break (audited) | Data ingestion | admin |

Why these seven: each owns one part of the flow the platform already runs (data in → checks → decisions
→ approvals → reports → audit), and together they make every "two different people" rule visible:
the analyst decides and the CFO approves; the reporting officer prepares, the CRO reviews and the CFO
approves; the auditor checks it all afterwards.

Left out on purpose (add later if the demo needs them): a Branch / Country Manager (would see only their
own branches, needs row-level security), a Board member (a read-only Executive summary), a Treasury dealer.

## 3. What each person sees

The menu shows only the screens a person uses (✓), or reads without acting (read). A hidden screen is also
refused by the server, not just left off the menu.

| Screen | CFO | CRO | Recon analyst | Reporting officer | Compliance | Auditor | Admin |
|---|---|---|---|---|---|---|---|
| Executive summary (+ KPI detail) | ✓ | ✓ | read | ✓ | read | read | read |
| Portfolio & credit risk | ✓ | ✓ | | read | | read | |
| Branch & segment | ✓ | ✓ | | | | read | |
| Scenario modelling | ✓ | ✓ | | | | | |
| Regulatory reporting | approve | review | | prepare | | read | |
| Reconciliation | read | | ✓ | | | read | read |
| Tasks | ✓ | ✓ | ✓ | ✓ | ✓ | | ✓ |
| Audit & Oversight | ✓ | | | | | ✓ | ✓ |
| Data ingestion | refresh only | | read | | | read | ✓ |
| AI assistant | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

Seven screens for the CFO instead of eleven; four for the analyst; three for compliance.

## 4. Which tasks each person gets

Camunda routes tasks to groups; the Tasks screen shows a person only their groups' tasks (Tasklist has no
per-person logins, so the app filters by role).

| Camunda group | Tasks | Who |
|---|---|---|
| `operations` | Reconciliation team review, data-quality flags, possible duplicates | Reconciliation Analyst |
| `cfo` | CFO approval of important reconciliation tasks, run sign-off | CFO (Admin as deputy) |
| `fraud-investigation`, `compliance` | Transaction cases (suspicious, threshold) | Compliance Officer |
| limit breaches (today routed as `compliance`) | KPI limit breaches | **CRO** — needs a new `risk` group |
| report workflow | Prepare → review → approve a return | Reporting Officer → CRO → CFO |

## 5. Demo logins

The same on every machine this project runs on: `backend/seed_demo_users.py` will set exactly these (it
lets each person choose today).

| User | Email (login) | Password |
|---|---|---|
| Chief Financial Officer (CFO) | `cfo@bankx.demo` | `BankX-Cfo-2026` |
| Chief Risk Officer (CRO) | `cro@bankx.demo` | `BankX-Cro-2026` |
| Reconciliation Analyst | `recon.analyst@bankx.demo` | `BankX-Recon-2026` |
| Regulatory Reporting Officer | `reporting@bankx.demo` | `BankX-Report-2026` |
| Compliance Officer | `compliance@bankx.demo` | `BankX-Comply-2026` |
| Internal Auditor | `auditor@bankx.demo` | `BankX-Audit-2026` |
| Platform Administrator | `admin@bankx.demo` | `BankX-Admin-2026` |

The four current logins: `approver@` becomes the CFO, `reviewer@` the CRO, `analyst@` the Reconciliation
Analyst and `admin@` stays the Administrator. The existing rows are renamed, not deleted, so the audit
trail's "who did what" keeps pointing at the right person.

## 6. To build (after this is agreed)

1. Migration: roles `risk`, `preparer`, `compliance`, `auditor`; rename the four existing users; add the
   three new ones.
2. `seed_demo_users.py`: set the passwords above by default (an environment variable can still override
   them for a hosted copy); `setup-new-machine` and `run-local` skills updated.
3. One role table (backend) that says which screens and which task groups each role has: the menu, the
   home screen, the Tasks filter and the server's checks all read it.
4. A `risk` Camunda group for limit breaches; the approval checks (`recon_tasks_db`, `recon_runs_db`) keep
   "the CFO or an admin" and add "never the auditor".
5. Login page: a "Demo users" list with each person's job, so a demo audience sees who is who.

## 7. Open questions

1. Is seven right for the demo, or should the Compliance Officer and the Reporting Officer wait?
2. Should the CRO, not Compliance, get limit-breach tasks (section 4)?
3. Keep the passwords in this public file, or move them to a file that isn't pushed (e.g. `DEMO-LOGINS.md`
   listed in `.gitignore`, shared by hand)?
