# Demo Guide: every tab, in plain words

A read-before-the-demo guide to what each tab shows, what to click, and what to say. Rewritten 2026-10-01 for
the current app (seven people with their own screens, the reconciliation approvals, Data ingestion, the CRM
comparison). The 25 Sep version is in Git history.

**The one-line story:**
> "The bank's numbers come from several systems. This platform brings them in, checks that nothing was lost or
> changed on the way, shows the ratios the board and regulators care about, and makes sure every problem is
> decided by the right person, with the CFO approving anything important and a permanent record of every decision."

---

## Before you start (15 minutes before the demo)

1. **Check the internet.** A weak connection shows "Database unavailable". Wait a moment and refresh; it recovers.
2. **Start Camunda:** Docker Desktop, then in `camunda/`: `docker compose up -d elasticsearch`, wait until it's
   healthy, then `docker compose up -d`.
3. **Start the app:** `.\scripts\run-local.ps1` (or ask Claude to "start the app"). It starts the API, the website
   (http://localhost:5173) and the three bridge workers that connect the app to Camunda:
   - `outcome_worker.py`: writes every task decision back to the database
   - `poll_worker.py`: turns new flags, gaps, breaks and duplicates into tasks, every 5 minutes
   - `breach_check.py`: turns KPI limit breaches into tasks for the Chief Risk Officer, every 5 minutes

   If Camunda isn't up, the script warns and skips the workers; run it again once Camunda is running.
   `.\scripts\run-local.ps1 -Stop` stops everything except Camunda.
4. **Warm up.** Sign in and open each tab once, so the database is awake.
5. **If you'll show a new day arriving** (recommended), upload the 1 Oct files and press **Run All Sources** about
   15 minutes before you need the results (see "Showing a new day arrive" below).

### The people (logins)

Seven people, one per job. Each has their own home screen, a menu of only their screens and a task list of only
their tasks. Passwords are fixed and the same on every machine: see `specs/user-roles.md` section 5.

| Login | Who | Lands on after sign-in | Does in the demo |
|---|---|---|---|
| `cfo@bankx.demo` | Chief Financial Officer | Data ingestion | Approves important tasks and data fixes, signs off each reconciliation run, can upload and run the pipeline |
| `cro@bankx.demo` | Chief Risk Officer | Portfolio & credit risk | Credit risk, stress tests, limit-breach tasks |
| `recon.analyst@bankx.demo` | Reconciliation Analyst (Operations) | Data ingestion | Decides reconciliation tasks, data-quality flags and possible duplicates |
| `reporting@bankx.demo` | Regulatory Reporting Officer | Regulatory reporting | Prepares the regulator's returns |
| `compliance@bankx.demo` | Compliance Officer | Tasks | Investigates suspicious and threshold transactions |
| `auditor@bankx.demo` | Internal Auditor | Data ingestion | Reads everything, changes nothing |
| `admin@bankx.demo` | Platform Administrator | Data ingestion | Connects sources, runs the pipeline, deputises for the CFO |

**Tip:** each browser tab keeps its own sign-in, so you can have the analyst in one tab and the CFO in another and
switch between them during the demo. A menu tab click reloads that page with fresh data.

---

## How the data gets here (say this once, early)

> "The bank's systems deliver their files every day. Databricks picks them up, cleans them, checks them and
> calculates every ratio, then loads the results into the database this app reads. So the screens are fast,
> because the heavy work is done before anyone opens them."

- **Run All Sources** (Data ingestion, top right) starts the pipeline now. Only the CFO or the admin can press it.
  A run takes about 6 minutes; new tasks appear within the next 5.
- **Refresh Now** on the Executive summary does the same from there.
- The pipeline can also start by itself about 2 minutes after the last file lands. **That automatic start is
  paused at the moment**, so press Run All Sources after uploading.
- Each run also pulls the CRM (Salesforce) and compares it with our customers.

---

## 1. Data ingestion (where most people land)

**What it is:** where the data comes from, and whether each load worked.

- **Four cards:** sources connected, files in the latest run, records ingested (kept · held back with a reason),
  failed loads (red if any).
- **Upload files** (CFO and admin): drop the day's core banking CSVs (customers, accounts, loans, transactions,
  branches, capital_positions, liquidity_daily, fx_rates). Each file is checked in the browser and again on the
  server (the right name and columns, not empty, at most 100 MB), then sent straight to the pipeline's landing folder.
  - **Safety check:** a customers, accounts, loans or branches file that would remove more than 20% of the records
    the platform has is **held**: "would remove 186 of the 214 customers and add 372 new ones". It's sent only if you
    press **Send anyway**. "That's how a wrong file can't quietly replace the bank."
- **Connect a source:** Salesforce, PostgreSQL, REST API, AWS S3, Snowflake. Test connection, Connect & Save,
  Configure, Disconnect, Sync. Secrets go to Databricks' secret store, never to our database.
- **Recent ingestions:** one line per source, country and file: received, kept, held back, status, when. Sort by
  any column.
- **Scheduled pulls:** labelled *Demo data* (planned, not running yet).

**Say:** "Every load is counted, tagged with where it came from, and checked before it reaches a single report."

---

## 2. Executive summary

**What it is:** the bank on one page, for the board and the CFO. It's the CFO's home screen (the name in the
header goes there) and is in every person's menu.

- **Eight KPI tiles:** capital ratio (CAR), liquidity ratio (LCR), bad loans (NPL ratio), net interest margin,
  cost-to-income, return on equity, total assets, dollarization. Each is coloured by its limit (green, amber, red).
- **Trend**, **What needs attention** (plain-language alerts), **By country** (Lebanon, Saudi Arabia, Qatar).
- **Refresh Now** (CFO or admin).

**Click** any tile for **KPI detail**: the trend, the data behind it, suggested actions read from the KPI's formula,
and **Why it looks like this**: code works out the facts (the move, the trend, where it stands against its limits,
and for CAR and LCR which part moved); the local AI model only rewrites them into plain sentences, and every number
it writes is checked against the facts. Without the model, the code's own sentences are shown.

**If asked:** the limits and three KPIs (NIM, cost-to-income, ROE) use **placeholder assumptions** until the bank
confirms them. These are marked on screen.

---

## 3. Portfolio & credit risk (the CRO's home)

**What it is:** where the loan book is, and how much of it is going bad.

- Summary boxes: gross loans, NPL amount and ratio, coverage, cost of risk.
- The loan book by product, segment, branch and currency: everything lent, and the part 90+ days late.
  "A product can look large and healthy, or small and on fire."
- Bad-loan trend, **IFRS 9 staging** (Stage 2 is the early warning), top exposures, ageing (31–90 days late),
  collateral and loan-to-value (above 100%: the bank loses money even after selling the collateral).
- Click any bar or row and the loan list narrows to those loans. Export to Excel.

**Say:** "From the whole book down to the individual loan in two clicks."

---

## 4. Analysis & reporting (one menu, three screens)

### Branch & segment
Who makes money and who loses it: branch league table (worst first, loss-makers flagged; click a branch for its
customers and loans), regional rollup, segments and products (net contribution after provisions), channels, the
efficiency scatter. **If asked:** segment costs are allocated, not measured (marked on screen).

### Scenario modelling (CFO and CRO)
"What happens to our capital if things go wrong?" Four sliders (devaluation, rate change, NPL increase, deposit
outflow), Base / Adverse / Severe presets, results after stress, the **waterfall** (which factor hurts most), the
**12-month projection** with the month it breaches, scenarios side by side, the assumptions.
**Say:** "It recalculates instantly in the browser." Try devaluation 30%.

### Regulatory reporting (the Reporting Officer's home)
The report calendar (red: overdue or under 5 days), and **Capital Adequacy** in the regulator's format with
**drill-to-source**: click any figure for its formula, source tables and record count. Validation checks (red blocks
submission, amber needs an explanation), prior-period comparison, PDF and Excel export.
**Say:** "Every number on a return can be traced back to the data that made it."

---

## 5. Reconciliation

**What it is:** proof that nothing was lost or changed between the bank's systems and our numbers. Read-only here;
the decisions happen in **Tasks**.

### Check A: received vs kept (did we lose anything while cleaning?)
One line per source, country and file: received, kept, rejected, and the amount gap per currency (never added
across currencies). Click a line for every rejected row and its reason. A file or country that delivered nothing
also shows as a gap. Each gap is a task.

Today: **Lebanon accounts** (1 row, unknown currency), **Lebanon transactions** (3 rows), **Saudi Arabia
transactions** (1 row).

### Check B: our data vs the source systems
Two systems are compared customer by customer and account by account; every difference is a **break**:

- **Core banking** (the master record). Examples today: 12 accounts each 9,000 lower in core banking; ACN0020
  48,000 higher; CN0051 "SME" there, "Retail" here; customers CB-EXTRA-001/002 and CNCORE01 missing from our data;
  ACNDEMO2 missing from core banking.
- **The CRM (Salesforce).** Day 1: CN0008's name differs, CN0002's country differs, CN0027 missing from the CRM,
  CNCRM01 only in the CRM, CN0001's name in capitals (cleared automatically). Day 2 (picked up by the next run):
  a new prospect CNCRM02, CN0013 renamed "Ghosn Traders Group", CN0015 moved to the UAE, CN0022 retyped (cleared).

- **Harmless differences clear themselves** (case, spaces, punctuation; differences under $1). They stay visible
  for auditors but are never anyone's work.
- **Groups:** breaks with the same cause become one task with one decision ("4 accounts, each +15.00").
  Important breaks are never bundled: a missing record, a key field (name, currency, type, segment) or a difference
  of 10,000 or more is always its own task, marked **Important**.
- **Bad-file guard:** if 20 or more records go missing the same way at once, that's a wrong or partial file, not
  20 problems: they become **one** task for the CFO, "… check the file that was loaded".
- **Each source's run** and where its sign-off stands. Breaks show how long they've been open and how often seen;
  one that was accepted but comes back is **reopened and marked Recurring**. Export CSV.

---

## 6. Tasks (where the work happens)

> "The other tabs show the problems. Tasks is where people decide them, and every decision is recorded."

Each person sees only their own tasks:

| Task | What it is | Who decides |
|---|---|---|
| Reconciliation: rows not loaded / data differs | A received-vs-kept gap, or a group of breaks | Reconciliation Analyst, then the **CFO** if Important or a data fix |
| Reconciliation: run sign-off | Closing a run | **CFO** (admin as deputy) |
| Transaction case | Suspicious-transaction flags, bundled per account + day + type | Compliance Officer |
| Data quality | A record the nightly checks rejected | Reconciliation Analyst |
| Possible duplicate | Two customer records that may be the same company | Reconciliation Analyst |
| Limit breach | A KPI crossed a limit | **Chief Risk Officer** (Risk Review) |

**The list:** severity and due date, overdue first in red. Filters: type, **Important only**, **Sent back to me**,
**Carried over**, Reconciliation (all). "How tasks are created" explains every rule. Low-severity transaction cases
go to the **daily digest** instead (anyone can *Raise as task*).

### A reconciliation task, step by step
The task shows a progress line: **Team review → CFO approval (or "not needed") → Run sign-off**, with who acts.

1. **Team review** (Reconciliation Analyst), with a required comment:
   - **Approve changes** / **Approve all changes**: the difference is explained and fine.
   - **Assign to CFO**: our copy is wrong. The analyst enters the fixed values (filled in with the source system's
     value, editable) and the CFO approves them.
   - **Dismiss**: not a real problem.
   - On a group, tick records to **leave out**; each comes back as its own task.
2. **CFO approval**, only for **Important** tasks and data fixes: **Approve**, or **Send back to the team** with a
   reason. The CFO can't approve their own decision. An Important task says in its header "Whatever you decide,
   this task goes to the CFO for approval next", so an analyst's approval isn't mistaken for the final one.
3. **Run sign-off** (CFO), once per run: when every task is decided, or from **08:00 the next morning**. The CFO
   signs off the decided tasks; any still open are **carried over** into the next run as high priority (escalated
   after 3 carries), so one stuck task doesn't block the day. The CFO can also send chosen tasks back.

Sent-back tasks say who sent them back, from which step and why, in the list, the task and its comments.
Approved fixes on a received-vs-kept gap are applied on the next pipeline run.

### Other tasks
- **Transaction case:** "Six alerts on one account on one day are one case and one decision." Approve all /
  Reject all, each flag with its own record.
- **Limit breach** (CRO): Acknowledge, Dismiss or Plan action (asks for a plan). Early warnings are notifications
  only; a breach of the bank's own limit is due in the limit's resolution days, a regulatory one in half that time.
- **Possible duplicate:** the two records side by side with their loans: **Same company** (exposure added together
  from the next refresh; nothing merged) or **Different companies** (never asked again). At most 25 are open at once,
  best match first; the rest wait.

**Every decision needs a comment, and every action goes into the audit trail.**

---

## 7. Audit & Oversight (CFO, auditor, admin)

- **Management view:** on-time vs late submissions, overdue reports, average time to a decision, open breaches by age.
- **Audit trail:** every comment and decision (who, what, when, on which record), including uploads, pipeline runs
  and the demo restore of 30 Sep. **Nothing can be edited or deleted.**

**Say:** "If a regulator asks who approved this and when, the answer is here, and it can't be changed."

---

## 8. AI assistant (everyone)

**Ask about your data** in plain English ("Which branch has the most loans 90 days late?"). A local model on this
machine (no bank data leaves it) only chooses which of the platform's prepared questions fits and with which filters;
**it never writes SQL and never produces a number**. The answer is a table straight from the database, with the
filters shown, exportable to Excel, and every question is audited. A question it can't answer that way, it says so.

---

## Showing a new day arrive (the 1 Oct files)

`bank-data/upload-test_2026-10-01/` is the demo bank's next days: 440 new transactions (29 Sep–1 Oct), liquidity and
FX, the same customers, plus two planted rows. Its `TEST-GUIDE.md` has the full table of what to expect.

1. As the **CFO**, drop all 8 files on **Upload files**. None is held ("same bank, so the safety check lets them through").
2. Press **Run All Sources**. About 6 minutes for the run, up to 5 more for the tasks.
3. Afterwards:
   - Data ingestion: a new run, no failed loads.
   - Reconciliation: Saudi Arabia's transactions gap is now **2** rows (planted **TNDEMO1001B**, currency "US$").
     The previous delivery's undecided gap tasks are replaced by the new ones, not duplicated.
   - Compliance Officer: a new case for **TNDEMO1001A**, a 65,000 USD deposit (Large amount).
   - The CRM day-2 changes: CNCRM02 and CN0013 as Important tasks for the CFO, CN0015 for the team, CN0022 cleared.
   - Executive summary: liquidity and FX move to 1 Oct.

Upload these files **once**. Don't upload `upload-test_2026-09-30/` except to show the safety check holding a
wrong file (press **Don't send**). `demo-baseline_2026-09-29/` is the backup copy, not for uploading.

---

## Suggested demo order (about 20 minutes)

Before you start: upload the 1 Oct files and press Run All Sources (as the CFO) ~15 minutes ahead.

1. **Sign in as the CFO.** Point out the landing page (Data ingestion), the new run and the upload safety check
   (optionally drop the 30 Sep `customers.csv` to show it held, then **Don't send**).
2. **Executive summary:** the eight tiles, click one for **Why it looks like this**, then "What needs attention".
3. **Portfolio:** slice the loan book, click a bar down to the loans, IFRS 9 staging.
4. **Scenario:** Severe preset, the waterfall and the month the capital ratio breaches.
5. **Regulatory reporting:** open Capital Adequacy, click a figure for its formula and sources.
6. **Reconciliation:** click a received-vs-kept gap for its rejected rows; show a core banking break, a CRM break and
   an auto-cleared name.
7. **Tasks, as the Reconciliation Analyst** (second browser tab): filter **Important only**; decide the
   "5 accounts: balance 250.00 lower" group with **Approve all changes** (not Important: done, no CFO); decide an
   Important one (e.g. CN0051's segment) and see "goes to the CFO next".
8. **Back as the CFO:** the Important task waits for **CFO approval**: send it back with a reason, show the analyst
   sees "Sent back" and why; then approve after the analyst decides again.
9. **Run sign-off** (CFO): sign off the decided tasks and carry the open ones; show "Carried over" on the analyst's list.
10. **Compliance Officer:** the TNDEMO1001A case, "one case, one decision".
11. **Internal Auditor:** sees everything, can't change anything; Audit & Oversight shows every step just taken.

---

## Honest answers to likely questions

- **"Can everyone see everything?"** No. Each person sees only their screens and tasks, and the server refuses the
  rest, not just the menu. The auditor can read everything and change nothing. Single sign-on comes next phase;
  today the logins are demo accounts with fixed passwords.
- **"Where do the thresholds come from?"** 10,000 (Important), 20% (upload held), 20 missing at once (one file task),
  25 open duplicate reviews, 08:00 sign-off, 3 carries, $1 ignored, severities and due days: all **placeholders** in
  the settings until the bank confirms them, changeable without code.
- **"Does 'Assign to CFO' change the data?"** For a received-vs-kept gap, the approved fixed values are applied on the
  next pipeline run. For a core banking or CRM break it records the decision; the fix happens in the source system.
- **"What if someone uploads the wrong file?"** The upload holds it if it would remove much of the data; if sent
  anyway, missing records come up as one task, not hundreds, and the audit trail records who pressed Send anyway.
- **"Is this real bank data?"** Generated demo data, with planted cases so every feature has something to show.
- **"Is the data live?"** Loaded per run (daily, or Run All Sources / Refresh Now), not second by second, so the
  screens stay fast.
- **"Does the AI make the numbers up?"** No. In the AI assistant the model only picks the question; the table comes
  from the database. On KPI detail, code works out the facts and the model only words them; its sentences are
  checked against the figures before they're shown.

---

## If something goes wrong during the demo

| What you see | What to do |
|---|---|
| "Database unavailable" | Internet or DNS blip: wait 5–10 seconds and refresh |
| Tasks list empty or erroring | Camunda isn't running: start Docker Desktop and Camunda, then `.\scripts\run-local.ps1` again to start the workers |
| A new task doesn't appear | The poll worker runs every 5 minutes; wait, or check it's running (`run-local.ps1` starts it) |
| "You were signed out because this tab's sign-in changed to someone else" | A sign-in in another tab replaced this one's; sign in again here |
| An error after submitting a task | Don't submit again. Close the popup and refresh; if the task is gone, it worked |
| Run All Sources says a run is already going | Wait for it to finish (about 6 minutes) |
| An upload is held ("would remove …") | That's the safety check: it's the wrong file. Press **Don't send** |
| Hundreds of new tasks after a run | A wrong file was loaded. Stop deciding; restore from `bank-data/demo-baseline_2026-09-29/` (see `bank-data/upload-test_2026-09-30/TEST-GUIDE.md`) |
| "No numbers yet" on the dashboard | The pipeline hasn't loaded data: Run All Sources as the CFO |
