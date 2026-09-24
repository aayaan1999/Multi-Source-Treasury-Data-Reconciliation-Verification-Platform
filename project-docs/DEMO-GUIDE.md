# Demo Guide: every tab, in plain words

A read-before-the-demo guide to what each tab shows, what to click, and what to say. Written 2026-09-25.

**The one-line story:**
> "The bank's numbers come from several systems. This platform collects them every night, checks that
> nothing was lost or changed on the way, shows the ratios the board and regulators care about, and makes
> sure every problem is reviewed by the right people, with no single person approving something big alone,
> and a permanent record of every decision."

---

## Before you start (10 minutes before the demo)

1. **Check the internet.** A weak connection shows "Database unavailable". Wait a moment and refresh; it recovers on its own.
2. **Start everything.** Ask Claude to "start the app and Camunda", or do it by hand:
   - Docker Desktop, then Camunda (`camunda/`: `docker compose up -d elasticsearch`, wait until healthy, then `docker compose up -d`)
   - The three bridge workers (`camunda/bridge/`: `outcome_worker.py`, `poll_worker.py --loop 300`, `breach_check.py --loop 300`)
   - The API and the website (site: http://localhost:5173)
3. **Warm up.** Open every tab once so the database is awake and connections are open.
4. **Logins:** `analyst@bankx.demo`, `reviewer@bankx.demo`, `approver@bankx.demo` (acts as the **CFO**),
   `admin@bankx.demo`. All four use the same password you chose when setting them up.

| Login | Plays the part of |
|---|---|
| analyst@ | Prepares the work, submits a reconciliation run for sign-off |
| reviewer@ | Reviews and decides groups, cases and alerts |
| approver@ | **The CFO**: second approvals, run sign-off, reconciliation gaps, Refresh Now |
| admin@ | Settings, and the one-break override on the Reconciliation tab |

---

## How the data gets here (say this once, early)

> "Every night the bank's files land in a folder. Databricks picks them up automatically, cleans them, checks them
> and calculates every ratio. The results are loaded into the database this app reads. So the screens are fast,
> because the hard work is done overnight, not while you wait."

- About 10 minutes after a file arrives, the pipeline starts by itself.
- **Refresh Now** (on the Executive summary) starts it on demand. Only the CFO or an admin can use it.

---

## 1. Executive summary (the home page)

**What it is:** the bank on one page, for the board and the CFO.

- **Eight KPI tiles:** Capital ratio (CAR), Liquidity ratio (LCR), Bad loans (NPL ratio), Net interest margin,
  Cost-to-income, Return on equity, Total assets, Dollarization ratio. Each is coloured by its limit (green, amber, red).
- **Trend:** how the KPIs have moved over time.
- **What needs attention:** plain-language alerts, e.g. "Capital ratio is below its limit".
- **By country:** the same figures split per country (Lebanon, Saudi Arabia, Qatar).
- **Refresh Now:** re-runs the nightly pipeline on demand (CFO or admin only).

**Click:** any KPI tile. It opens the **KPI detail** page:
- a trend and the data behind it
- "What actually moved", written from the numbers themselves, not an AI summary
- **Suggested actions**, read from the KPI's own formula, e.g. "raise capital or reduce risk-weighted assets"

**Say:** "Every number here was calculated overnight from the bank's own data. Click any tile and it explains itself."

**If asked:** the red/amber limits and three of the KPIs (NIM, cost-to-income, ROE) use **placeholder assumptions**
until the bank confirms them. These are marked on screen.

---

## 2. Portfolio & credit risk

**What it is:** where the loan book is, and how much of it is going bad.

- **Summary boxes:** gross loans, NPL amount, NPL ratio, coverage ratio, cost of risk.
- **The loan book, sliced four ways:** by product, segment, branch and currency. Two bars per category: everything lent,
  and the part that is 90+ days late. "A product can look large and healthy, or small and on fire."
- **Bad-loan trend** over time.
- **IFRS 9 staging:** Stage 1 (fine), Stage 2 (the early warning: got worse but not yet late), Stage 3 (in default).
- **Top exposures:** the biggest borrowers.
- **Ageing:** loans 31–90 days late. "Not officially bad yet, but most will be next quarter."
- **Collateral and loan-to-value (LTV):** what is owed against what the security is worth. Above 100% means the bank
  loses money even after selling the collateral.
- **Filters and click-through:** click any bar or row and the loan list at the bottom narrows to those loans.
- **Export to Excel.**

**Say:** "From the whole book down to the individual loan in two clicks."

---

## 3. Branch & segment performance

**What it is:** who in the bank makes money and who loses it.

- **Summary:** total revenue, total cost, profit, and the number of branches in loss.
- **Branch league table:** worst profit first, loss-makers flagged. Click a branch to see its customers and loans.
- **Regional rollup:** "Is the problem one bad branch or a whole region?"
- **Customer segments** (Retail, SME, Corporate) and **product performance.** Net contribution = interest income minus
  provisions, so "a product can earn a high rate and still lose money once bad loans are counted."
- **Channel usage** and the **efficiency scatter** (revenue against cost-to-income).
- **Export to Excel.**

**If asked:** segment costs are **allocated, not measured** (a documented assumption, marked on screen), and cost means
direct branch cost only.

---

## 4. Scenario modelling (stress testing)

**What it is:** "What happens to our capital if things go wrong?"

- **Four sliders:** currency devaluation (0–50%), interest-rate change (−5 to +5%), rise in bad loans (NPL increase),
  deposit outflow (0–30%).
- **Three presets:** Base, Adverse, Severe.
- **Results after stress:** capital ratio, liquidity ratio, capital surplus or shortfall, profit impact.
- **Waterfall:** "Which factor hurts most?", showing today's capital ratio, then the step each factor takes off it,
  against the dashed minimum line.
- **12-month projection:** the capital ratio month by month under the stress, and the month it breaches, if it does.
- **Scenarios side by side:** the three presets plus any you save.
- **Assumptions:** what the model assumes. "Bankers will ask."

**Say:** "Move a slider and it recalculates instantly. That's done in the browser, with no waiting on the database."
Try: set devaluation to 30% and show the waterfall and the projection react.

---

## 5. Regulatory reporting

**What it is:** the regulator's returns, and proof of where every number came from.

- **Summary:** due this month, submitted, pending approval, overdue.
- **Report calendar:** every return and its due date. Red means overdue or under 5 days left, amber under 10 days,
  green on time or submitted. Only returns that have been built can be opened. Today that's **Capital Adequacy**.
- **Opening a return** shows it in the regulator's format, plus:
  - **Drill-to-source (the differentiator):** click any figure to see its **formula, the source tables and the
    number of records** that produced it.
  - **Validation checks:** a red check blocks submission; an amber one needs a written explanation.
  - **Against the prior period:** what changed since the last return.
  - **Export PDF / Export Excel** in the regulator's format.

**Say:** "Every number on a regulatory return can be traced back to the data that made it. Auditors love this."

**If asked:** a few lines are marked because no source table holds them yet. They show the real total split in the
proportions of the source document's worked example.

---

## 6. Reconciliation

**What it is:** proof that nothing was lost or changed between the bank's systems and our numbers. There are two checks.

### Check A: "Received vs kept, per source" (did we lose anything while cleaning?)
> "Every night we receive files. Before using them we throw out bad records. This check counts what came in against
> what survived, and shows exactly which records were thrown out and why."

- One line per source, country and table: received, kept, rejected, and the amount gap **per currency** (currencies
  are never added together).
- **Click a line** to see the gap per currency and every rejected record with its reason.
- Anything expected but **not delivered** (a country or table missing) also appears as a gap.
- Each gap becomes a **task for the CFO** (see Tasks below).

### Check B: "Our data vs the core banking system"
> "The core banking system is the master record. We compare our copy with it, customer by customer and account by
> account. Every difference is called a **break**."

| Kind of break | Example in the demo data |
|---|---|
| Different value | Account ACN0001: core 122,098.15, ours 122,083.15 |
| Key field different | Customer CN0051: core "SME", ours "Retail" |
| Missing in our data | A customer the core system has that we don't |
| Missing in the core system | An account we have that core doesn't |

- **Harmless differences clear themselves:** "NOUR SAAD" vs "Nour Saad" is marked *Cleared automatically*. It stays
  visible for auditors, but it's never work for anyone. Differences under $1 are ignored.
- **Latest run panel:** breaks found, cleared automatically, open groups, important breaks still open, plus the
  **run sign-off** (see below).

#### Groups (the bank's main complaint: "we can't fix 1,400 differences one by one")
> "Breaks with the same cause are bundled into a **group**. One person makes one decision for the whole group."

- **Groups table:** each group's number, cause, number of breaks, total difference, kind and status.
  **Click a group** to see every break in it.
- **All breaks table:** has a **Group** column, plus a group filter to list one group's breaks.
- **Safety rule:** important breaks are **never bundled**. A missing record, a key-field difference, or a difference
  of 10,000 or more always gets a group of its own, due in 1 day.

The groups in the demo data:

| Group | What | Why it's like this |
|---|---|---|
| #1 | 4 accounts, each exactly +15.00 | Same cause, so one decision |
| #2 | 12 accounts, each −9,000, total −108,000 | Total over 100,000, so it **needs a second approval** |
| #3 | 2 accounts, 240 and −610 | Bundled by size band "100–1,000" |
| #4 | 1 account, 48,000 off | Important (10,000 or more), on its own |
| #5 | Account missing in core | Important (missing record) |
| #6 | CN0051 segment | Important (key field) |
| #7–#10 | Customers missing in our data | Important (missing record). #7 is already decided (Correct) |

#### Run sign-off (once per reconciliation run)
> "At the end, someone formally says 'this reconciliation is complete'. The preparer submits it and a **different**
> person signs it off, like a month-end sign-off."

- The preparer submits it. **If important breaks are still open, they must add a note explaining why.**
- Only the CFO (approver) or an admin can sign it off, and **never the person who submitted it.** The system refuses.

#### What happens on the next run
- Each break shows how long it has been open and how many times it has been seen.
- If someone accepted a break but the difference comes back, it's **reopened and marked Recurring**: "the system never
  quietly re-accepts a problem that keeps coming back."
- **Export CSV** of the breaks for auditors.

---

## 7. Tasks (where the work happens)

**What it is:** every problem that needs a person, in one queue.

> "The other tabs show the problems. **Tasks** is where people decide them, and every decision is recorded."

**What becomes a task:**

| Task type | What it is | Decided by (team) |
|---|---|---|
| Transaction case | Suspicious-transaction flags, bundled per account + day + type | Fraud Investigation / Compliance / Operations |
| Data quality | A record the nightly checks rejected | Operations or Compliance |
| Breach | A KPI crossed a limit | Compliance |
| Reconciliation | A received-vs-kept gap | **CFO** |
| Core-system break | A reconciliation **group** | Operations, plus **CFO** for large groups |
| Possible duplicate | Two customer records that may be the same company | Operations |

**The list:**
- Each task shows its **Severity** (High / Medium / Low) and **Due** date. **Overdue tasks go to the top, in red.**
- Filter by type or name. "How tasks are created" explains every rule in plain words (all placeholders until the bank
  confirms).
- **Daily digest:** low-severity cases don't become tasks. They're listed here, and anyone can **Raise as task**.

**Transaction cases (bundling):**
> "Six alerts on one account on the same day are one case and one decision, not six tasks."

- Severity score: by type, plus 1 for 3 or more flags, plus 1 for 2 or more different rules. High and Medium become
  tasks; Low goes to the digest.
- **Approve all / Reject all** applies to every flag in the case, each with its own record.

**Reconciliation gap (the CFO process):**
1. **CFO review:** the CFO either **approves** it directly or **reassigns** it to a named colleague.
2. **Update values:** the colleague proposes corrections to the rejected records' fields and submits them to the CFO.
3. **CFO final review:** **approve**, or **return** it to the colleague with a reason.
4. When approved, the next pipeline run applies the corrections, so the record passes and the gap closes.

**Core-system group (the two-step check):**
1. **Review group** (Operations): pick **Accept / Correct our data / Dismiss** for the whole group, with a required
   comment. You can **leave some breaks out** ("Accept all except 1"); those come back as separate tasks.
2. **Second approval** (CFO), only when the group totals 100,000 or more (group #2). The decision doesn't take effect
   until the CFO approves. **The person who decided can't approve their own decision.** Return sends it back.

**Breach:**
- **Acknowledge**, **Dismiss**, or **Plan action**, which asks for a written action plan.
- Breaches have three levels:
  - **Early warning:** a notification only, and it clears itself if the KPI recovers.
  - **Appetite:** the bank's own limit was crossed. A task is created, due in the limit's resolution days.
  - **Regulatory:** a task is created, due in **half** that time.

**Possible duplicate:** the two customer records side by side, with their loans. Choose **Same company** (their exposure
is added together from the next refresh; nothing is merged) or **Different companies** (never raised again).

**Every task needs a comment, and every action is written to the audit trail.**

---

## 8. Audit & Oversight

**What it is:** the governance view.

- **Management view:** on-time vs late report submissions, reports overdue, average time to a decision, and open
  breaches by age.
- **Audit trail:** a permanent record of every comment and decision (who, what, when, on which record). **Nothing can
  be edited or deleted.** Filter by record.

**Say:** "If a regulator asks who approved this and when, the answer is here, and it can't be changed after the fact."

(Breaches are no longer listed here. They live on the Tasks tab.)

---

## Suggested demo order (about 15 minutes)

1. **Executive summary.** The eight tiles, click one for KPI detail, then "What needs attention" and "By country".
2. **Portfolio.** Slice the loan book, click a bar to reach the loans, then IFRS 9 staging.
3. **Scenario.** Choose the Severe preset, then show the waterfall and the month the capital ratio breaches.
4. **Regulatory reporting.** Open Capital Adequacy and click a figure to show its formula, source tables and record
   count. Mention the validation checks and the PDF export.
5. **Reconciliation.**
   - Check A: click a gap to show the rejected records.
   - Check B: point out the auto-cleared name.
   - Groups: click group #1 ("4 breaks, one decision"), then point out that important breaks stay on their own.
6. **Tasks.**
   - Decide group #1 as `reviewer@`, leaving one account out.
   - Decide group #2 as `reviewer@`, then log in as `approver@` and approve its **Second approval**.
     The reviewer can't approve their own decision.
   - Open a transaction case: "6 alerts, 1 decision".
7. **Back on the Reconciliation tab:** the decided breaks now show as Accepted.
8. **Run sign-off:** submit as `analyst@`, show that `analyst@` can't sign it off, then sign it off as `approver@`.
9. **Audit & Oversight:** every step you just did is in the audit trail.

---

## Honest answers to likely questions

- **"Can everyone see everything?"** Yes, in this demo every login can see and act on every task. Locking each task to
  the right person comes with single sign-on in the next phase. Two rules are enforced today: the run sign-off
  (a second person, CFO or admin only), and the reviewer can't give their own second approval.
- **"Where do the thresholds come from?"** 100,000 (second approval), 10,000 (important), $1 (ignored), the severity
  scores and the due days are all **placeholders** in the settings table until the bank confirms them. They can be
  changed without code changes.
- **"Does 'Correct our data' change the data?"** For core-system groups it records the decision; the fix happens at
  source. For received-vs-kept gaps, approved corrections **are** applied automatically on the next pipeline run.
- **"Is this real bank data?"** It's generated demo data, with planted cases so every feature has something to show.
- **"Is the data live?"** It's loaded nightly (or on Refresh Now), not second by second, by design, so the screens
  stay fast.

---

## If something goes wrong during the demo

| What you see | What to do |
|---|---|
| "Database unavailable" | Internet or DNS blip: wait 5–10 seconds and refresh |
| Tasks list empty or erroring | Camunda isn't running: start Docker Desktop and Camunda |
| An error after submitting a task | Don't submit again. Close the popup and refresh; if the task is gone, it worked |
| A new group or case doesn't appear | The poll worker runs every 5 minutes; wait, or ask Claude to run one pass |
| "No numbers yet" on the dashboard | The pipeline hasn't loaded data; use Refresh Now (as approver) |
