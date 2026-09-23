Think of the bank as a huge shop that has thousands of drawers full of numbers, and nobody has time to open them all.

**The problem today**

A bank knows everything about itself, but the information is scattered. Loan numbers sit in one system, deposits in another, branch costs in a spreadsheet, currency positions somewhere else. When the board asks "how are we doing?", someone spends three days pulling numbers from all these places into Excel. By the time the report is ready, the numbers are already old. And if the Board asks a follow-up question \- "what about just the corporate loans?" \- that's another two days.

**What the product does**

It collects all those numbers automatically every night, does the maths, and shows the answers on a screen.

Three parts, and it helps to think of them separately.

**Part one \- it gathers.** Every night the system quietly goes to each of the bank's systems and copies the latest numbers into one place. Nobody does this by hand. By morning, everything is together and current.

**Part two \- it calculates.** This is the important part. Raw numbers alone mean nothing. "We have 500 million in loans" tells you almost nothing. What matters is: how much of that might not be repaid, how much capital we're holding against it, are we profitable, are we inside the limits the central bank sets. The system does these calculations automatically. What took an analyst three days now takes three seconds, and it happens every day instead of once a month.

**Part three \- it shows.** Clean screens with the numbers that matter. Green when things are fine, red when they aren't. The Board opens it in the morning and sees the health of the bank on one page. If something looks wrong, he clicks it and sees what's underneath \- which branch, which product, which customers.

**The clever bit: asking "what if"**

This is the feature that impresses bankers most. There's a screen with sliders. The CFO drags one that says "currency drops 20%" and instantly sees what happens to the bank's capital. Another says "bad loans increase by 5%" \- same thing, immediate answer.

Today, answering that question means a team working for a week in Excel. With this, it's ten seconds. And because it's fast, they can try twenty scenarios instead of one, which is how you actually plan.

**And the part nobody else offers**

Numbers going to the central bank can't just be emailed by whoever made them. Someone prepares the report, a risk manager checks it, the CFO signs it off, then it's submitted \- and the bank must be able to prove later who approved what and when.

Our system handles that whole chain, with a permanent record of every step. Most analytics companies only show pretty charts \- they can't do the approvals, sign-offs and audit trail. That's what makes us different.

**In one sentence**

The bank's numbers, collected automatically, calculated correctly, shown clearly, with a proper approval process around anything official.

### **THE DATABASE \- think of it as filing cabinets**

There are two kinds of tables. Some hold **things that exist** (customers, accounts, loans, branches). Others hold **things that happened or were measured on a date** (transactions, monthly capital, daily liquidity, exchange rates).

Everything connects through ID numbers, like a customer number written on every file belonging to that customer.

---

**Table 1 \- CUSTOMERS**  
 Who banks with you.

| Column | What it holds | Why it matters |
| ----- | ----- | ----- |
| customer\_id | Unique number | The thread linking everything else |
| name | Customer name | Display |
| segment | Retail / SME / Corporate | Lets you split every report by customer type |
| branch\_id | Which branch owns them | Lets you measure branches |
| onboard\_date | When they joined | Growth trends |
| risk\_rating | Internal score, e.g. A to E | Risk analysis |
| country | Where they are | Country exposure limits |

---

**Table 2 \- ACCOUNTS**  
 Money the bank *owes* customers (deposits).

| Column | What it holds |
| ----- | ----- |
| account\_id | Unique number |
| customer\_id | Links to the customer |
| type | Current / Savings / Term deposit |
| currency | USD / LBP / EUR |
| balance | How much is in it |
| open\_date | When opened |

This table answers: how much money do we hold, in which currencies, from which kinds of customers.

---

**Table 3 \- LOANS**  
 Money customers owe the bank. **This is the most important table** \- most of the bank's risk lives here.

| Column | What it holds | Why it matters |
| ----- | ----- | ----- |
| loan\_id | Unique number |  |
| customer\_id | Who borrowed |  |
| product | Mortgage / Personal / SME / Corporate | Shows which products go bad |
| principal | Original amount |  |
| outstanding | Still owed today | The real exposure |
| currency | USD / LBP / EUR | Currency risk |
| interest\_rate | Rate charged | Income calculations |
| origination\_date | When issued |  |
| maturity\_date | When due |  |
| days\_past\_due | Days late on payment | **90+ days \= a bad loan** |
| stage | IFRS 9 stage 1, 2 or 3 | Accounting classification of risk |
| provision\_amount | Money set aside for expected loss |  |
| collateral\_value | Value of security held | Compared to outstanding \= LTV |

---

**Table 4 \- TRANSACTIONS**  
 Every movement of money. The biggest table by far.

| Column | What it holds |
| ----- | ----- |
| transaction\_id, account\_id, date | Identity and timing |
| amount, currency | Size |
| type | Deposit / Withdrawal / Transfer / Fee |
| channel | Branch / ATM / Mobile / Online |

Answers: is money flowing in or out, which channels customers use, and it feeds the deposit-outflow scenario.

---

**Table 5 \- BRANCHES**

branch\_id, name, region, staff\_count, monthly\_opex. Small table, but it's what lets you say "Branch 14 costs more than it earns."

---

**Table 6 \- CAPITAL\_POSITIONS** (one row per month)

month, tier1\_capital, tier2\_capital, risk\_weighted\_assets.

In plain terms: capital is the bank's own money, its cushion. Risk-weighted assets are the loans adjusted for how risky each one is. The central bank demands the cushion be at least a certain percentage of that. This table is where the headline regulatory ratio comes from.

---

**Table 7 \- LIQUIDITY\_DAILY** (one row per day)

date, hqla (cash and assets sellable instantly), net\_outflows\_30d (money that could leave in a month), stable\_funding, required\_funding.

Capital asks "are we solvent?" Liquidity asks "can we pay people tomorrow?" Different question, equally important.

---

**Table 8 \- FX\_RATES** (one row per currency per day)

date, currency\_pair, rate. Everything must be convertible to one reporting currency, and this is also what powers the devaluation scenario.

---

**How they join up:** a customer has many accounts and many loans; a branch has many customers; an account has many transactions. So when someone clicks "Corporate segment" on a dashboard, the system filters customers by segment, finds their loans and accounts, and recalculates everything underneath.

---

### **THE SIX SCREENS**

#### **Screen 1 \- Executive Summary**

**Who:** board. **Used:** every morning, two minutes.

Eight tiles across the top, each showing today's number, the change since last month, and a colour.

* **Capital ratio (CAR)** \- from capital\_positions. Is our cushion big enough?  
* **Liquidity ratio (LCR)** \- from liquidity\_daily. Can we survive a month of outflows?  
* **Bad loan ratio (NPL)** \- loans where days\_past\_due ≥ 90, divided by all loans  
* **Net interest margin** \- what we earn on loans minus what we pay on deposits  
* **Cost-to-income** \- branch costs versus income. Are we efficient?  
* **Return on equity** \- profit versus shareholders' money  
* **Total assets** \- overall size  
* **Dollarization ratio** \- foreign-currency deposits as a share of all deposits

Below, a 24-month trend chart, and an alert strip: *"Capital ratio 12.4% \- 0.4 points above minimum."*

Green means fine, amber means watch, red means act. That's the whole design.

#### **Screen 2 \- Portfolio & Credit Risk**

**Who:** Chief Risk Officer, credit committee.

The loan book sliced four ways \- by product, customer segment, branch, and currency \- so they can find where risk is concentrated. A 24-month bad-loan trend line. The IFRS 9 stage split (stage 1 healthy, stage 2 warning signs, stage 3 already impaired) with the money set aside for each. A top-20 largest borrowers table, because if one huge customer fails it can hurt the whole bank. And an ageing table: how much is current, 30, 60, 90, 180+ days late.

All from the loans table, grouped and summed different ways.

#### **Screen 3 \- Regulatory Reporting**

**Who:** compliance and finance teams.

A list of the reports the central bank requires, each showing status \- draft, under review, approved, submitted \- and its deadline. Open one and it's laid out in the format the regulator expects.

The critical feature: **click any number and see where it came from.** Which table, which formula, which loans made up that total. Regulators ask "how did you get this figure?" and the bank must be able to answer. Plus proper PDF and Excel export, because that's how reports actually get filed.

#### **Screen 4 \- Scenario Modelling**

**Who:** CFO, risk, board planning. **This is the screen that sells the product.**

Four sliders: currency devaluation (0–50%), interest rate change (±5%), bad loans increase (0–15%), deposit outflow (0–30%).

Move one and every number below recalculates instantly \- capital ratio, liquidity ratio, capital surplus or shortfall, profit impact. The bank can save scenarios side by side: base case, adverse, severe.

Why it matters so much: this normally takes a team a week in Excel. Here it's ten seconds, so they can test twenty scenarios instead of one.

#### **Screen 5 \- Branch & Segment Performance**

**Who:** COO, retail head.

Every branch in one ranked table: deposits held, loans issued, revenue, cost, profit, efficiency. Same for customer segments and products. Sorted worst to best, so the underperformers are immediately obvious.

Built from branches joined to customers joined to their accounts and loans.

#### **Screen 6 \- Report Workflow**

**Who:** everyone who touches an official number.

An analyst prepares a report and submits it. The risk manager reviews, comments, and either returns or approves it. The CFO signs off. Only then can it be submitted. Every step is recorded permanently \- who did what, when, and what changed.

And when a number breaches a limit, the system automatically creates a task with an owner and a due date, so someone is accountable for fixing it.

**Screen 1 \- Executive Summary**

### **What's physically on the screen**

**Top strip:** the bank's name, today's date, and "data as of" with a timestamp. That timestamp matters more than it sounds — a CEO needs to know if he's looking at last night's numbers or last week's.

**Main area: eight boxes, arranged four across and two down.** Each box is identical in layout:

* The name of the measure, in small text at the top  
* The number itself, large and bold — this is the only thing you read from across the room  
* Underneath: the change since last month, with an arrow up or down  
* A thin coloured bar along the bottom: green, amber or red

**The eight boxes, in plain language:**

*Capital Ratio (CAR)* — "Do we have enough of our own money as a cushion?" Shows something like 12.4%. Red if it's close to the legal minimum.

*Liquidity Ratio (LCR)* — "If lots of people withdrew money tomorrow, could we pay them?" Different question from capital, and equally serious.

*Bad Loans (NPL Ratio)* — "What share of our loans aren't being repaid?" Usually 3-5% is normal; rising is the warning.

*Net Interest Margin* — "What do we earn on loans, after paying depositors?" This is the core of how a bank makes money.

*Cost-to-Income* — "How much do we spend to earn each dollar?" Lower is better. Above 60% and the CEO starts asking about branches.

*Return on Equity* — "What return are shareholders getting?" The number the board cares about most.

*Total Assets* — "How big are we?" Mainly for the trend.

*Dollarization Ratio* — "How much of our deposits are in foreign currency?" In Lebanon this is arguably the most important number on the screen.

### **The parts that make it feel real**

**Below the boxes, one large chart.** Twenty-four months of history, with lines for the three or four most important ratios. Dotted horizontal lines show the regulatory minimums, so you can see how close you've been running. A CEO reads a trend far faster than a table.

**Below that, an alert strip.** Plain sentences, not codes:

> ⚠️ Capital ratio at 12.4% — only 0.4 points above the regulatory minimum  
>  ⚠️ Bad loans in SME lending have risen for 6 consecutive months  
>  ✅ Liquidity comfortable at 142%

Three to five lines maximum. This is where the screen stops being a report and starts being useful — it does the noticing *for* the CEO.

**Everything is clickable.** Click the bad-loans box and it opens Screen 2 filtered to bad loans. Click the alert about SME lending and it opens the SME portfolio. Nobody should ever have to hunt for the detail behind a number.

**One filter, top right:** a date selector, so they can look at last month or last quarter.

### **How it actually works underneath**

Every night the system reads from the tables — capital\_positions for CAR, liquidity\_daily for LCR, loans for the bad-loan ratio, accounts for dollarization — runs each formula, and stores the eight results in a small summary table with the date.

That last part matters for the demo: the screen reads from the pre-calculated summary, not from millions of rows. That's why it loads in under two seconds even with two million transactions behind it. If you calculate live on the fly, the demo will feel slow and the CEO will lose interest before the numbers appear.

The colours come from thresholds stored in a small settings table — each measure has a red limit and an amber limit, adjustable, because every country's regulator sets different floors.

**Screen 2 — Portfolio & Credit Risk**

Screen 1 tells the CEO *something is wrong*. Screen 2 is where the risk team finds out *what and where*. Everything on it comes from one table — `loans` — sliced and summed in different ways.

Before the sections, two definitions the whole screen rests on:

**A bad loan (NPL)** is any loan where `days_past_due` is 90 or more. Ninety days is the standard line worldwide — before that it's "late," after that it's "probably not coming back."

**A provision** is money the bank sets aside from its profits because it expects to lose some of a loan. It's already in the `provision_amount` column.

---

### **Section 1 — The top strip: five summary boxes**

| Box | Plain meaning | Calculation |
| ----- | ----- | ----- |
| Gross Loans | Total we've lent out | `SUM(outstanding)` |
| NPL Amount | How much is 90+ days late | `SUM(outstanding) WHERE days_past_due >= 90` |
| NPL Ratio | That as a percentage | NPL Amount ÷ Gross Loans × 100 |
| Coverage Ratio | Have we set aside enough for the bad ones? | `SUM(provision_amount)` ÷ NPL Amount × 100 |
| Cost of Risk | What bad loans cost us this year | Provision charge for the year ÷ average gross loans × 100 |

On coverage ratio: if bad loans are 100 million and provisions are 70 million, coverage is 70%. Below about 50% means the bank hasn't faced up to its losses yet — regulators look hard at this.

---

### **Section 2 — The loan book, sliced four ways**

Four charts side by side, each answering "where is our money?"

**By product** (bar chart) — group loans by the `product` column, sum outstanding. Mortgage, Personal, SME, Corporate.

**By segment** (donut) — join loans to customers, group by `customers.segment`.

**By branch** (ranked bar) — join through customers to `branch_id`, sum outstanding, sort descending.

**By currency** (bar) — group by the `currency` column. In Lebanon this chart is the one people stare at.

Here's the important design point: each of these charts should show **two bars per category — total loans and bad loans**. A product with 200 million lent and 4 million bad is healthy. A product with 50 million lent and 9 million bad is a fire. Showing only totals hides exactly what the screen exists to reveal.

---

### **Section 3 — The bad-loan trend**

A line chart, 24 months, showing the NPL ratio each month.

To build it: for each of the last 24 month-ends, calculate bad loans ÷ total loans as of that date, and plot the points.

Then add a second set of lines — one per product — so you can see *which* product is driving the trend. This is where your demo's story lives: four lines flat, one climbing steadily for six months. That single chart makes the whole product feel valuable.

---

### **Section 4 — IFRS 9 staging**

IFRS 9 is the accounting rule banks follow worldwide. In plain words it sorts every loan into three buckets:

**Stage 1 — healthy.** Paying normally. The bank sets aside a small amount, covering 12 months of possible loss.

**Stage 2 — worrying.** Not yet late, but something has changed for the worse — a credit downgrade, an industry collapse, repeated near-misses. The bank must now set aside enough for losses over the *whole remaining life* of the loan. This is the bucket that matters most, because it's the early warning.

**Stage 3 — already bad.** The customer has effectively defaulted. Heavy provisions.

Build it as a table:

| Stage | Number of loans | Outstanding | Provisions | Coverage % |
| ----- | ----- | ----- | ----- | ----- |
| Stage 1 | count | sum | sum | provisions ÷ outstanding |
| Stage 2 | count | sum | sum |  |
| Stage 3 | count | sum | sum |  |

All of it is `GROUP BY stage` on the loans table.

Next to it, a small chart showing how many loans moved between stages over the last six months. Loans sliding from Stage 1 into Stage 2 is the single best predictor of trouble coming — it appears months before anything shows up as a bad loan.

---

### **Section 5 — Top 20 exposures**

Why this exists: if one huge borrower fails, it can damage the whole bank. Regulators limit how much you can lend to any single customer as a percentage of your capital.

Build it: group loans by `customer_id`, sum outstanding, sort descending, take 20\. Join to customers for name and segment. For each row show outstanding, product, days past due, and **exposure as a percentage of the bank's capital** — that last one being outstanding ÷ (tier1 \+ tier2 from `capital_positions`) × 100\.

Colour the row red if that percentage breaches the regulatory single-borrower limit. Add a line underneath: "Top 20 borrowers \= 34% of gross loans" — a number risk committees always want.

---

### **Section 6 — Ageing table**

Every loan sorted by how late it is:

| Bucket | Condition | Amount | % of book |
| ----- | ----- | ----- | ----- |
| Current | days\_past\_due \= 0 |  |  |
| 1–30 days | 1 to 30 |  |  |
| 31–60 days | 31 to 60 |  |  |
| 61–90 days | 61 to 90 |  |  |
| 90–180 days | 91 to 180 |  |  |
| 180+ days | over 180 |  |  |

The 31–90 day buckets are the ones to watch. Those loans aren't officially bad yet, but most of them will become bad next quarter. A bank that watches this bucket sees its problems a quarter early.

---

### **Section 7 — Collateral and LTV**

LTV means loan-to-value: what's still owed divided by what the security is worth. `outstanding ÷ collateral_value × 100`.

If someone owes 800,000 on a property worth 1,000,000, LTV is 80% — the bank is covered. If the property drops to 700,000, LTV is 114% and the bank loses money even after selling.

Show a distribution chart: how much of the book sits under 50%, 50–80%, 80–100%, and over 100%. Anything above 100% is uncovered exposure and should be red.

---

### **How the whole screen behaves**

**One filter bar at the top** — date, product, segment, branch, currency. Every chart and table on the page responds to it together. Pick "SME" and the entire screen becomes the SME story.

**Everything drills down.** Click a bar in the product chart and you get the loan list behind it. Click a row in top-20 and you see that customer's full relationship.

**One export button** that sends the current view to Excel, because risk teams live in Excel and will ask.

**Screen 3 — Regulatory Reporting**

This one is for *filing*. Every country's central bank demands specific reports, on specific forms, by specific dates. Late or wrong means fines, and in serious cases restrictions on the bank's licence. So this screen isn't about pretty charts — it's about producing an exact document, proving where every figure came from, and tracking whether it got submitted on time.

---

### **Section 1 — The report calendar (the main view)**

A table listing every report the bank owes the regulator.

| Report name | Frequency | Period | Due date | Days left | Status | Owner |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Capital Adequacy | Quarterly | Q3 2026 | 15 Oct | 29 | Draft | Finance |
| Liquidity Coverage | Monthly | Sep 2026 | 10 Oct | 24 | Under review | Treasury |
| Credit Classification | Quarterly | Q3 2026 | 20 Oct | 34 | Not started | Risk |
| Large Exposures | Quarterly | Q3 2026 | 20 Oct | 34 | Approved | Risk |
| FX Position | Monthly | Sep 2026 | 8 Oct | 22 | Submitted | Treasury |

Status moves through five stages: Not started → Draft → Under review → Approved → Submitted.

Colour by urgency, not by status: red if fewer than 5 days remain and it isn't submitted, amber under 10 days, green if submitted. A compliance head should be able to glance at this and know what's at risk.

Above the table, four small boxes: reports due this month, submitted, pending approval, overdue.

**Data needed:** a small `report_definitions` table (name, frequency, due-day rule, owner) and a `report_instances` table (which report, which period, status, owner, dates, submitted timestamp).

---

### **Section 2 — An open report**

Click any row and it opens the actual document, laid out as the regulator expects — not as a dashboard.

This looks like a form: sections, numbered line items, values in columns. For a capital adequacy return, roughly:

SECTION A — CAPITAL  
A.1  Paid-up capital                      150,000,000  
A.2  Retained earnings                     45,000,000  
A.3  Reserves                              20,000,000  
A.4  Deductions                            (8,000,000)  
A.5  TIER 1 CAPITAL                       207,000,000

A.6  Subordinated debt                     30,000,000  
A.7  General provisions                     9,000,000  
A.8  TIER 2 CAPITAL                        39,000,000  
A.9  TOTAL CAPITAL                        246,000,000

SECTION B — RISK WEIGHTED ASSETS  
B.1  Credit risk                        1,650,000,000  
B.2  Market risk                          120,000,000  
B.3  Operational risk                     215,000,000  
B.4  TOTAL RWA                          1,985,000,000

SECTION C — RATIOS  
C.1  Tier 1 ratio                              10.43%  
C.2  Total capital ratio                       12.39%  
C.3  Regulatory minimum                        12.00%  
C.4  Surplus / (Shortfall)                  7,700,000

Where each line comes from: capital figures from the `capital_positions` table. Risk-weighted assets from the loans table, where each loan is multiplied by a risk weight based on its type and rating — a government bond might weight 0%, a mortgage 35%, an unsecured corporate loan 100%. Store those weights in a small `risk_weights` table so they can be changed without touching code. The ratios are then simple division.

---

### **Section 3 — Drill to source (the feature that matters most)**

Every single number on that form must be clickable.

Click "B.1 Credit risk — 1,650,000,000" and a panel opens showing: the formula used, which table the data came from, how many loans were included, the risk weights applied, when it was calculated, and a button to see the full underlying loan list.

Why this is the most important feature on the screen: regulators and auditors ask "how did you arrive at this figure?" Today, someone spends a day rebuilding it in Excel. With this, it's one click. Bankers who have lived through an audit will react to this more strongly than to any chart you show them.

**To build it:** store, alongside every calculated figure, the formula text, the source tables, the filters applied, the record count, and a timestamp. A `calculation_audit` table.

---

### **Section 4 — Validation checks**

Before a report can be approved, the system runs checks automatically and shows the results:

* ✅ All required fields completed  
* ✅ Section totals equal the sum of their line items  
* ✅ Tier 1 \+ Tier 2 equals total capital  
* ⚠️ Credit risk RWA rose 12% from last quarter — explanation required  
* ❌ Three loans missing collateral values

Green passes, amber needs a comment, red blocks submission entirely.

This catches the ordinary human errors — a total that doesn't add up, a missing field — before the regulator catches them. Store rules in a `validation_rules` table so new checks can be added without a code release.

---

### **Section 5 — Comparison with prior periods**

A small table beside the report: this period, last period, the change, and the percentage change, for the key lines.

Regulators notice big swings and ask about them. So should the bank, before filing. Any line moving more than 10% should be flagged for a written explanation, which gets stored with the report.

---

### **Section 6 — Export**

Two buttons that must genuinely work in the demo:

**Export to PDF** — the regulator's exact format, with bank name, period, page numbers, and signature blocks at the bottom. Use ReportLab or WeasyPrint.

**Export to Excel** — the same figures in the regulator's template layout, because many central banks require upload in a specific spreadsheet format. Use openpyxl.

I'd stress this to your team: exports look boring but they are what a compliance officer actually judges you on. A beautiful screen with a broken PDF button loses the deal. Test both thoroughly before demo day.

---

### **Section 7 — Submission record**

Once submitted: the date, who submitted it, the reference number from the regulator, and the exact file that was sent, stored permanently and unchangeable.

If the regulator later queries a figure, the bank needs to produce precisely what was filed — not a version regenerated afterwards from data that may have since changed. Store the actual file, not just the parameters to rebuild it.

---

### **Database additions for this screen**

report\_definitions   — report\_id, name, frequency, due\_day\_rule,  
                       owner\_department, template\_format  
report\_instances     — instance\_id, report\_id, period, status, owner,  
                       created\_date, approved\_by, approved\_date,  
                       submitted\_date, regulator\_reference  
report\_line\_items    — instance\_id, section, line\_code, description,  
                       value, source\_formula, source\_tables  
validation\_rules     — rule\_id, report\_id, rule\_type, condition,  
                       severity (block/warn/info), message  
calculation\_audit    — calc\_id, instance\_id, line\_code, formula\_text,  
                       source\_query, record\_count, calculated\_at  
risk\_weights         — asset\_class, rating, weight\_percentage  
submitted\_files      — instance\_id, file\_blob, file\_hash, submitted\_at

**Screen 4 — Scenario Modelling**

The other screens show what *has happened*. This one answers "what if?" — and that question is what keeps bank executives awake.

The whole idea: take today's real numbers, apply a bad event to them, and instantly show what breaks.

---

### **The layout**

Split the screen down the middle. **Left side: the controls.** **Right side: the results.** Move a control on the left, the right side updates immediately — no "calculate" button, no page reload. That instant response is what makes people lean forward.

---

### **Left side — four sliders**

**Slider 1: Currency devaluation, 0% to 50%**

In plain terms: what if the local currency loses value against the dollar?

Why it hurts a bank: if the bank lent money in dollars but the borrower earns in local currency, that borrower now needs far more local money to repay. Many simply can't. Also, the bank's capital is usually held in local currency, while a chunk of its loans are in dollars — so the loan book inflates in local terms while the capital cushion doesn't.

*For a Lebanese bank, this is the single most important slider on the screen.*

**Slider 2: Interest rate change, −5% to \+5%**

If rates rise, the bank pays more on deposits fairly quickly, but many loans are on fixed rates, so income doesn't rise as fast. Margin gets squeezed. Also, borrowers on floating rates find repayments harder, so bad loans tick up.

**Slider 3: Bad loans increase, 0% to \+15%**

A recession, an industry collapse, a major customer failing. More loans go unpaid, which means more provisions, which come straight out of profit and capital.

**Slider 4: Deposit outflow, 0% to 30%**

Customers withdraw money — panic, loss of confidence, better rates elsewhere. This is a liquidity event, not a capital one, and it can kill a solvent bank in days.

Under the sliders: three preset buttons — **Base**, **Adverse**, **Severe** — that set all four at once. Base is everything at zero. Adverse might be 20% devaluation, \+2% rates, \+5% NPL, 10% outflow. Severe doubles that. Presets matter because regulators require banks to run standard stress scenarios, and a CFO will recognise the language immediately.

---

### **Right side — the results**

**Top: four big result boxes.** Each shows the number *before* and *after*, with the change:

|  | Before | After | Change |
| ----- | ----- | ----- | ----- |
| Capital ratio | 12.4% | 9.1% | ▼ 3.3pp |
| Liquidity ratio | 142% | 88% | ▼ 54pp |
| Capital surplus | \+7.7m | −58m | Shortfall |
| Profit impact | — | −92m |  |

Colour them green, amber or red against the regulatory minimum. The moment a box turns red and says "shortfall," the room goes quiet — that's the demo working.

**Middle: a waterfall chart.** Start at today's capital ratio on the left, then a downward step for each stressed factor, ending at the final ratio. This answers the question a CFO always asks next: *which of these is hurting me most?* Often it's one factor doing 70% of the damage, and seeing that is genuinely useful.

**Below: a 12-month projection line.** Show capital ratio month by month under the stress, with the regulatory minimum as a dotted line. The powerful part is the crossing point — "you breach the minimum in month 7." That converts an abstract percentage into a deadline.

**Bottom: a comparison table.** Save scenarios side by side, so the board can see base, adverse and severe together in one view.

---

### **The calculations, step by step**

I'll walk through each slider's effect in the order they should be computed, because some feed into others.

**Currency devaluation of X%**

Take every loan where currency is not the reporting currency and revalue it: `new_value = outstanding × (1 + X)`. The foreign-currency loan book grows in local terms.

Then, because borrowers earning locally now struggle: apply a stress factor to those loans' default probability. A reasonable rule for a POC is that a 20% devaluation pushes an additional 3-5% of foreign-currency loans into default. Make this assumption visible and editable, not buried in code.

Risk-weighted assets rise by the revalued loan amounts. Capital stays roughly flat. So the ratio falls on both sides — bigger denominator, plus new provisions eating the numerator.

**Bad loans up by Y%**

Additional bad loans \= gross loans × Y. New provisions on those, at whatever coverage ratio the bank currently runs — say 70%. That provision amount is subtracted from profit and therefore from Tier 1 capital. Recalculate the capital ratio.

**Interest rates change by Z%**

New interest income \= balance on floating-rate loans × Z. New interest expense \= balance on floating-rate deposits × Z. The net difference flows to profit and then to capital.

Keep a `floating_rate_flag` on loans and accounts so the team can separate fixed from floating — otherwise this calculation is meaningless.

**Deposit outflow of W%**

This one hits liquidity, not capital. Money leaving \= total deposits × W. High-quality liquid assets fall by that amount. Recalculate: `LCR = (HQLA − outflow) ÷ net 30-day outflows`.

If HQLA runs out before the outflow is covered, flag it hard — that's the scenario where a bank fails while still technically solvent.

**Then recalculate everything together**, because these interact. The correct order: apply devaluation → revalue the book → apply the extra defaults it causes → add the independent NPL stress → compute new provisions → apply rate effects to profit → reduce capital by total losses → recompute RWA → recompute the capital ratio → separately recompute liquidity.

---

### **What your team needs to build technically**

The whole thing must run in under a second, which means **you cannot query millions of rows on every slider movement.**

The approach: when the screen loads, pull today's position into memory once — total loans by currency, by product, by rate type, capital figures, liquidity figures, deposits by type. That's maybe fifty numbers. Every slider movement then recalculates against those fifty numbers in the browser, not against the database.

Store the assumptions — the default-uplift per devaluation percentage, the coverage ratio used for new provisions, the risk weights — in a settings table, and put a small "Assumptions" link on the screen that shows them. Bankers will ask what's behind the model, and being able to show it immediately is the difference between a toy and a credible tool.

Scenario saving needs a simple table: scenario name, the four input values, the calculated outputs, who created it, when.

**Screen 5 — Branch & Segment Performance**

Screens 1 to 4 are about risk and survival. This one is about money — who in the bank is making it and who is losing it.

The question it answers: *if I have 40 branches, which ones are worth keeping?* Most banks genuinely don't know, because the costs sit in one system and the revenue in another, and nobody joins them up.

---

### **Section 1 — Top strip, four boxes**

| Box | Plain meaning | Calculation |
| ----- | ----- | ----- |
| Total revenue | What the bank earned this period | Interest income \+ fee income |
| Total cost | What it spent running branches | `SUM(branches.opex_monthly)` for the period |
| Profit | The difference | Revenue − cost |
| Branches in loss | How many are losing money | Count of branches where profit \< 0 |

That last box is the one a COO looks at first. "Six branches are unprofitable" is a sentence that starts a meeting.

---

### **Section 2 — The branch league table (the heart of the screen)**

Every branch, one row each, sorted worst to best:

| Branch | Region | Deposits | Loans | Revenue | Cost | Profit | Cost-to-income | Staff | Profit/staff |
| ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- | ----- |
| Tripoli North | North | 18m | 12m | 640k | 810k | **−170k** | 127% | 14 | −12k |
| Saida Central | South | 34m | 29m | 1.4m | 950k | 450k | 68% | 16 | 28k |
| Beirut Main | Beirut | 210m | 180m | 8.2m | 2.1m | 6.1m | 26% | 42 | 145k |

**How each column is built:**

*Deposits* — join accounts → customers → branch\_id, sum balances.

*Loans* — join loans → customers → branch\_id, sum outstanding.

*Revenue* — two parts. Interest income is `SUM(loans.outstanding × interest_rate)` for that branch's customers, adjusted to the period. Fee income comes from the transactions table where type is 'Fee'. Add them.

*Cost* — `branches.opex_monthly × number of months`. For a POC this is enough; in production a bank would also allocate head-office costs.

*Profit* — revenue minus cost.

*Cost-to-income* — cost ÷ revenue × 100\. **Above 100% means the branch spends more than it earns.** This is the single most-watched number in retail banking.

*Profit per staff* — profit ÷ staff\_count. Useful because it separates "small but efficient" from "big but bloated." A 14-person branch making 400k is doing better work than a 42-person branch making 900k.

Colour the whole row red where profit is negative. Make every row clickable through to that branch's customers and loans.

---

### **Section 3 — Regional rollup**

The same figures grouped by `region` instead of branch. A simple bar chart: revenue and cost side by side per region, so you can see whether a problem is one bad branch or a whole region struggling.

Add deposit growth per region over 12 months as a line — regions losing deposits are usually losing customers, which shows up in profit a year later.

---

### **Section 4 — Customer segment performance**

Group by `customers.segment` — Retail, SME, Corporate.

| Segment | Customers | Deposits | Loans | Revenue | Bad loans | Profit |
| :---: | :---: | :---: | :---: | :---: | :---: | :---: |

The insight banks always find here: corporate banking usually shows the biggest revenue but also the biggest concentration risk, while retail shows small revenue per customer but far more stability. SME is often where the bad loans hide.

Add **revenue per customer** — revenue ÷ customer count. A segment with 40,000 customers producing less revenue than one with 200 tells the bank where its effort is going versus where its money comes from.

---

### **Section 5 — Product performance**

Group loans by `product`:

| Product | Outstanding | Avg rate | Interest income | NPL % | Net contribution |
| ----- | ----- | ----- | ----- | ----- | ----- |
| Mortgage |  |  |  |  |  |
| Personal |  |  |  |  |  |
| SME |  |  |  |  |  |
| Corporate |  |  |  |  |  |

**Net contribution is the important column:** interest income minus provisions for that product. A product earning 8% interest but running 9% bad loans is losing money while appearing profitable on the revenue line. Banks discover this far too late, and this column is how you show it in ten seconds.

Same for deposits — group accounts by type, show volume and the interest being paid out.

---

### **Section 6 — Channel usage**

From the transactions table, group by `channel`: branch, ATM, mobile, online.

Show the mix now versus 12 months ago. If mobile has gone from 30% to 55% of transactions while branch costs have stayed flat, the bank is paying for capacity nobody uses. That's a strategic conversation, and it comes straight out of one table.

---

### **Section 7 — The efficiency quadrant (the chart that impresses)**

A scatter plot. Each dot is a branch. Horizontal axis: revenue. Vertical axis: cost-to-income ratio. Dot size: deposits held.

This splits naturally into four groups:

* **Low cost ratio, high revenue** — your stars, protect them  
* **Low cost ratio, low revenue** — efficient but small, grow them  
* **High cost ratio, high revenue** — big but wasteful, fix the costs  
* **High cost ratio, low revenue** — the closure candidates

Executives understand this chart instantly without explanation, and it turns forty rows of table into four decisions.

---

### **How the screen behaves**

One filter bar across the top: period, region, segment, product, currency. Everything below responds together.

Every row drills down — click a branch and see its customers, its loans, its bad loans.

An Excel export, because the retail team will want to work with it.

---

### **Technical notes for your team**

**Pre-calculate monthly.** Branch profitability joins three or four tables across millions of transaction rows. Run it nightly into a `branch_performance_monthly` summary table with columns for branch, month, deposits, loans, revenue, cost, profit. The screen then reads a few hundred rows instead of millions, and loads instantly.

**Be honest about cost allocation.** In a real bank, "branch cost" includes a share of head office, IT, and central functions, and how you allocate those is genuinely contentious. For the POC, use direct branch opex only, and say so in the demo: *"this is direct cost; full allocation methodology would be configured with your finance team."* Claiming more precision than you have is how you lose credibility with a CFO.

**Screen 6 — Report Workflow**

### **Section 1 — My Tasks (the landing view)**

Whoever logs in sees only what's waiting for them.

| Task | Report | Period | Assigned | Due | Priority |
| ----- | ----- | ----- | ----- | ----- | ----- |
| Review and approve | Capital Adequacy | Q3 2026 | 2 days ago | 15 Oct | High |
| Prepare report | FX Position | Sep 2026 | Today | 8 Oct | Medium |
| Resolve breach | NPL limit exceeded | — | 1 day ago | 20 Sep | Critical |

Three buttons on each row: Open, Approve, Return with comment.

This is the difference between a dashboard and a system people actually use. A dashboard tells you things. This tells you what *you* need to do today.

---

### **Section 2 — The approval chain, shown visually**

When a report is open, show its journey as a horizontal set of steps:

Prepared ✅ → Reviewed ✅ → Approved ⏳ → Submitted ○  
  Rana          Karim          Nadia         —  
  12 Sep        14 Sep        pending  
  09:14         16:40

Green tick for done, clock for in progress, empty circle for not started. Each step shows who and when.

Anyone can see at a glance where a report is stuck and who is holding it. In most banks today that question requires three phone calls.

---

### **Section 3 — The review screen**

When a reviewer opens a report, they see the figures plus three things:

**Comments** — a thread against the report, and ideally against individual line items. "B.1 rose 12%, please explain" with a reply underneath.

**Changes since last version** — what was edited, by whom, from what value to what value.

**Two buttons:** Approve, or Return for correction with a mandatory comment. You cannot return something without saying why — that rule alone removes a lot of back-and-forth in real banks.

---

### **Section 4 — Breach alerts and remediation**

When any monitored number crosses a limit, the system creates a task automatically. Nobody has to notice it.

> 🔴 **NPL ratio 5.8% — internal limit 5.0%**  
>  Detected: 14 Sep · Owner: Head of Credit Risk · Due: 28 Sep  
>  Status: In progress  
>  Action plan: "Reviewing SME portfolio, restructuring 12 accounts"

The point: a breach becomes a named person with a deadline, not an observation in a report nobody read.

Build it from a `limits` table — metric name, threshold, direction, owner, and how many days to resolve. A nightly job compares each calculated metric against its limit and creates tasks where breached.

---

### **Section 5 — Audit trail**

A permanent, unchangeable log. Every row: timestamp, user, action, object, old value, new value.

16 Sep 10:42  Nadia Khoury   Approved      Capital Adequacy Q3  
14 Sep 16:40  Karim Assaf    Reviewed      Capital Adequacy Q3  
14 Sep 15:20  Rana Haddad    Edited A.4    \-7,200,000 → \-8,000,000  
12 Sep 09:14  Rana Haddad    Created       Capital Adequacy Q3

Searchable and filterable by user, date and report. **Nothing in this table can ever be edited or deleted** — that's the whole point of an audit trail. Enforce it at the database level: grant insert only, no update or delete, on that table.

---

### **Section 6 — A small management view**

Three or four simple charts: reports submitted on time versus late over the last 12 months, average days spent at each approval stage (this shows where the bottleneck is — usually one person), and open breaches by age.

---

### **The database**

users              — user\_id, name, email, role, department  
roles              — role\_id, name, permissions  
workflow\_steps     — step\_id, report\_id, sequence, role\_required, action\_type  
workflow\_instances — instance\_id, report\_instance\_id, current\_step, status,  
                     started\_at, completed\_at  
tasks              — task\_id, workflow\_instance\_id, assigned\_to, task\_type,  
                     status, created\_at, due\_date, completed\_at  
comments           — comment\_id, report\_instance\_id, line\_code, user\_id,  
                     comment\_text, created\_at, parent\_comment\_id  
audit\_log          — log\_id, timestamp, user\_id, action, object\_type,  
                     object\_id, old\_value, new\_value, ip\_address  
limits             — limit\_id, metric\_name, threshold\_value, direction,  
                     owner\_role, resolution\_days  
breaches           — breach\_id, limit\_id, detected\_at, actual\_value,  
                     assigned\_to, status, action\_plan, resolved\_at  
---

### **Open-source stack for this**

**Backend:** Python with FastAPI. It's fast to build, has automatic API documentation, and your team will move quickly in it.

**Database:** PostgreSQL. Free, handles everything here comfortably, and its row-level security helps enforce who sees what.

**Frontend:** React with Tailwind, and Recharts for the charts — the same stack as your other five screens, so it all feels like one product.

**Workflow logic:** honestly, don't reach for a workflow engine for a POC. Six status values in a table and a few API endpoints will do everything you need. If you want something more formal later, Camunda is the open-source standard, but it's overkill here and will cost you a week of setup.

**Background jobs** for the nightly breach checks: APScheduler is enough for a POC; Celery with Redis if you want something closer to production.

**Authentication:** for a demo, a simple login with four seeded users — analyst, reviewer, approver, admin — is plenty. Keycloak if you need real SSO later.

**PDF and Excel export:** ReportLab and openpyxl.

