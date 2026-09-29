# Spec: Ask a Question on Reports (client point 7: CHT-1..5)

**Status:** First version built 2026-09-28 — backend `backend/app/ask/` + `routers/ask.py`, panel
`frontend/src/ask/AskPanel.jsx` on its own "Ask a question" tab (`/ask`, `pages/Ask.jsx`, styled after
`project-docs/client-demo/Client-Demo-Overview.html`), golden set `backend/tests/ask_questions.json`, evaluation
`scripts/eval_ask.py`. Backend (pytest, fake model) and frontend (vitest) tests pass; **not yet checked in
a browser by a user yet**. Evaluations against the real model (Ollama, qwen2.5:3b, CPU):

| Run | Right type | Fully right | Wrong table | Time |
|---|---|---|---|---|
| 1st, golden 54 | 37 (69%) | 35 (65%) | **13** | 5.1 s |
| After fixes, golden 54 | 52 (96%) | 53 (98%) | **0** | 3.4 s |
| After fixes, held-out 30 (`ask_questions_holdout.json`) | 26 (87%) | 27 (90%) | **1** | 3.4 s |

Fixes (2026-09-28): the question's own words decide the type where they name it (`service.text_entry`),
the model's metric is used only for questions the word lists can't read, its split and sort order never;
requests to change anything are refused; worked examples in the prompt. The held-out run then found two
gaps, now fixed ("which 3 branches" as a count; "profitable") - so the held-out set is **no longer
blind**: write a fresh one before trusting a new score. Known remaining oddity: "What's the time in
Riyadh?" asks which branch measure instead of refusing (safe - a question, not a table).
**Backlog:** CHT-1..CHT-5 in `project-docs/CLIENT-FEEDBACK-BACKLOG.md` (section 7, "Conversational reporting").
**Changes a recorded decision:** the backlog's 2026-09-24 decision was *rule-based, no AI*. This spec
replaces the rule-based parser (CHT-2) with a **self-hosted language model** at the manager's request
(vLLM as the target server). CHT-1, CHT-3, CHT-4 and CHT-5 keep their original meaning — the backlog
already anticipated this: "a controlled AI parser can replace CHT-2 later without touching CHT-1/3/4".

## 1. Objective

A question box on the Reports screen: the user types *"NPL ratio by country"* or *"top 5 branches by
profit"* and gets a table they can export to Excel. Every number comes from the database, the user
sees exactly which filters were applied, and every question is audited.

**Done when** (unchanged from the backlog): a typed question returns an exportable table whose every
number came from the database, with the filters shown and the request audited; anything it can't
parse gets a follow-up question.

## 2. The one rule that makes this safe

**The model chooses; it never writes SQL and never produces a number.**

- The model's only job is to classify the question: *which* approved query, *which* metric, *which*
  way to split it. Its output is forced into a JSON schema whose fields are fixed lists (enums), so
  it can only pick from values we defined.
- Filter values that must be exact — dates, numbers, countries, branches — are taken from the
  question text by plain code (section 6), not from the model. The model's value is used only when
  the question text supports it.
- The SQL is fixed per catalogue entry (section 5), parameterised, and run by the backend.
- The answer is a table straight from that SQL. No model-written sentence in v1 (section 12).

Consequence: the worst a wrong model answer can do is pick the wrong approved query — which the user
sees immediately in the "What I understood" chips and can correct. It can't invent a figure, reach a
table outside the catalogue, or change data.

## 3. How it works

```
User types a question on Reports
        │
        ▼
POST /api/v1/ask ──► 1. Model (Ollama now, vLLM later): question -> {query, metric, dimension, sort}
        │             2. Code: extract dates, top N, country / branch / region / product / segment / stage
        │             3. Code: merge + validate against the catalogue entry
        │                 ├─ something required missing or conflicting -> "clarify" + buttons
        │                 └─ not a supported question               -> "unsupported" + examples
        │             4. Run the entry's fixed SQL with the validated filters
        │             5. Write one audit_log row
        ▼
Answer panel: "What I understood" chips · table · source + as-of date · Export to Excel
```

## 4. Where the model runs

The backend talks to the model through the **OpenAI-compatible chat-completions API**. vLLM and
Ollama both serve it, so the same backend code works against either — moving from the laptop to a
server is a configuration change, not a code change.

| Stage | Server | Model | Notes |
|---|---|---|---|
| **Now — development and demo** | **Ollama** on the developer laptop (`http://localhost:11434/v1`) | `qwen2.5:3b` (~1.9 GB) | Installed 2026-09-28: 4.6 GB disk in total. CPU only (no NVIDIA GPU): **~6 s per question** measured. |
| **Later — bank deployment** | **vLLM** on a GPU server inside the bank | Same family, larger if needed (e.g. Qwen2.5-7B-Instruct) | Expected well under 1 s per question; not measured. Nothing leaves the bank's network. |

vLLM was not used on the laptop: it is built for NVIDIA GPUs, and its CPU build needs ~15-20 GB of
disk and Docker memory already used by Camunda. Ollama gives the same API in 4.6 GB.

**Configuration** (`backend/.env`, never committed; add blank keys to `.env.example`):

| Setting | Meaning | Laptop value |
|---|---|---|
| `LLM_BASE_URL` | OpenAI-compatible base URL | `http://localhost:11434/v1` |
| `LLM_MODEL` | Model name as the server knows it | `qwen2.5:3b` |
| `LLM_API_KEY` | Only if the server requires one (vLLM `--api-key`) | blank |
| `LLM_TIMEOUT_SECONDS` | Give up and say so | `90` (was 30: a first question after Ollama had unloaded the idle model timed out on 2026-09-29; opening the Ask a question tab now loads the model in the background) |

**If the model server is down or not configured:** `POST /ask` returns 503 "Ask a question isn't
available right now"; the panel shows that line and the rest of Reports works as today. No silent
fallback to guessing.

**Structured output:** requests send `response_format: {type: "json_schema", ...}`. Ollama supports
it; vLLM supports the same field (guided decoding). Temperature 0, so the same question gives the same
answer on the same model.

## 5. Query catalogue (CHT-1)

Each entry is defined once in the backend (`backend/app/ask/catalogue.py`): id, description (also
given to the model), source table, fixed SQL, filters (required / optional / default), result
columns with units, and which roles may run it. Every entry reads a **precomputed summary table** that
the screens already use, so answers are fast and match what the screens show.

| Entry id | Answers | Source table | Filters (default) |
|---|---|---|---|
| `kpi_value` | One or all headline KPIs on a date, or their trend | `kpi_daily_summary` | metric (all), date (latest) or date range |
| `country_breakdown` | Deposits, loans, NPL, customers, transactions per country | `country_performance_summary` | metric (required), country (all), date (latest) |
| `branch_ranking` | Branches ranked by a measure | `branch_performance_summary` | metric (required), top N (all), order (by metric, see 6.4), region / country (all), date (latest) |
| `segment_performance` | Retail / SME / Corporate figures | `segment_performance_summary` | metric (all), segment (all), date (latest) |
| `product_performance` | Mortgage / Auto / Personal / SME / Corporate loan products | `product_performance_summary` | metric (all), product (all), date (latest) |
| `loan_breakdown` | Loan book and bad loans by branch / product / segment / currency | `loan_breakdown_by_dimension` | dimension (required), date (latest) |
| `ifrs9_stages` | IFRS 9 stage 1/2/3 counts, outstanding, provisions, coverage | `loan_stage_summary` | stage (all), date (latest) |
| `top_exposures` | Largest borrowers | `top_exposures` | top N (20, max 20), product (all), date (latest) |
| `loan_ageing` | Days-past-due buckets | `loan_ageing_summary` | date (latest) |
| `data_quality` | Rejected / flagged records by table or flag | `exception_summary_by_table`, `exception_summary_by_flag` | table (all), flag (all), date (latest) |
| `limit_breaches` | Current and past limit breaches | `breaches` + `limits` | metric (all), status (open), level (all) |
| `unsupported` | Anything else | — | — |

Excluded on purpose in v1: customer-level transaction search (personal data, not a summary table),
regulatory report *lines* (Screen 3 already shows them with drill-to-source; revisit once the bank
says which lines people ask about — backlog "Bank input" for CHT-1), and anything that writes.

Every entry returns at most 500 rows.

## 6. Understanding a question (CHT-2)

### 6.1 Step 1 — the model classifies

The model gets a system prompt listing each catalogue entry's id and one-line description, the metric
names with their synonyms ("bad loans", "non-performing" = NPL; "capital adequacy" = CAR; "cost
income" = cost-to-income; ...), and returns JSON matching this schema — every field an enum or null:

```json
{
  "query":     "kpi_value | country_breakdown | branch_ranking | ... | unsupported",
  "metric":    "car | lcr | npl_ratio | nim | cost_to_income | roe | total_assets | dollarization | deposits | loans | profit | revenue | ... | null",
  "dimension": "branch | product | segment | currency | null",
  "sort":      "best | worst | highest | lowest | null"
}
```

The metric enum is limited per entry after the fact (step 3): e.g. `branch_ranking` accepts only the
columns of `branch_performance_summary`.

### 6.2 Step 2 — code extracts exact values from the text

Independent of the model, a deterministic extractor reads the question:

| What | How | Examples |
|---|---|---|
| Dates | Fixed phrase list + ISO / "25 Sep" / "September 2026" patterns, relative to today | "today", "latest", "yesterday", "last week", "last month", "this month", "as of 2026-09-25", "last 7 days" |
| Top N | "top 5", "best 3", "worst 10", "5 largest" | top N = 5 |
| Countries | Names + aliases, matched as words | Lebanon; KSA = Saudi = Saudi Arabia; Qatar |
| Branches, regions | Loaded from `branches` at startup; fuzzy match (difflib ratio ≥ 0.85) for typos | "Riyad central" → Riyadh Central (BN07) |
| Products, segments, IFRS 9 stage | From the summary tables' distinct values | "mortgages" → Mortgage; "stage 3" |

### 6.3 Step 3 — merge and validate

1. The **query** comes from the model. If the model says `unsupported`, answer "unsupported".
2. **Named values** (country, branch, region, product, segment, stage) come **only from step 2**. If
   the model's output implies a country the text doesn't mention, it is dropped. (Measured: the 3B
   model added "KSA" to 5 of 8 test questions that never mentioned it — see section 13.)
3. **Dates and top N** come **only from step 2**; defaults from the catalogue entry otherwise.
4. **Metric**: the model's value if it's valid for the entry; otherwise a synonym found in the text;
   otherwise the entry's default; otherwise **clarify**.
5. Anything required still missing, or two conflicting values (e.g. two different countries for an
   entry that takes one), → **clarify**.

### 6.4 Sort order

"Top / best / highest" and "worst / lowest" depend on the metric: the worst branch on **profit** is
the lowest, the worst on **cost-to-income** is the highest. Each metric declares whether higher is
better; the model's `sort` word is mapped through that, and the chips show the result in words
("highest cost-to-income first").

### 6.5 Dates and missing data

The summary tables hold **one row set per pipeline run** (`calculation_date`): today 21-28 Sep 2026
only. A period maps to the latest `calculation_date` inside it ("last month" → the last snapshot in
August). **If the period has no data, the answer says so** — "No data for August 2026; available:
21-28 Sep 2026" with a button for the latest date — never silently substitutes another date.

### 6.6 Clarify, never guess

A clarify response carries one question and up to 5 buttons, each a complete filter set:

> *Which measure should branches be ranked by?* [Profit] [Revenue] [Deposits] [Loans] [Cost-to-income]

Clicking a button re-runs the query with those filters (no second model call).

### 6.7 What it can't do - and saying so

Probing the real model with 28 hard questions (2026-09-28, `backend/tests/ask_questions_hard.json`) found
13 that produced **a table answering a different question, with no warning** - one showing the exact
opposite ("branches except Beirut" showed only Beirut). The root cause was the same every time: the
panel acts only on words it recognises and **silently dropped the rest**; when the dropped words were
the important ones, the table stopped answering the question, and the model filled gaps with a
plausible guess.

These patterns are now detected (`extract.py`) and handled (`explain.py`):

| Pattern | Example | Before | Now |
|---|---|---|---|
| Leaving something out | "branches except Beirut" | only Beirut (the opposite) | **explained**, + "Show all branches instead" |
| Unknown place | "profit at Tyre branch" | every branch | **explained**, lists the known countries and branches |
| Unknown measure | "EBITDA by branch", "return on assets", "Tier 1 ratio" | loan book / total assets / CAR | **explained**, lists the measures it has as buttons |
| A split no report has | "NPL ratio by region" | bank-wide NPL | **explained**, + the splits that exist |
| Forecast / future date | "predict NPL next quarter" | today's NPL | **explained**, + link to Scenario modelling |
| One customer / account | "loans of customer C0012" | segment table | **explained** (summary data only, no personal data) |
| A request to change something | "delete all the loans" | - | **explained** (read-only) |
| Off-topic | "ignore your instructions ..." | refused, no reason | **explained**, + example questions |
| A threshold | "profit above 1 million" | every branch, as if filtered | table sorted so matching rows come first, **with a notice** |
| A change / two dates | "difference in CAR between 21 and 28 Sep" | 21 Sep only | every day in the span, **notice**: change not calculated |
| Two measures | "profit and revenue by branch" | profit only | first measure (or all, where allowed), **notice** |
| "Why" | "why did NPL go up" | the figure | the figure, **notice** + breakdown questions |
| A typo in a measure | "cost to incme" | ranked by *cost* | read correctly, **notice**: "I read X as Y" |

An explanation replaces the table (`status: "unsupported"`, `explanation: {code, title, why, how,
suggestions}`); a notice sits above it (`notices: [{code, title, message}]`). Every explanation says
why, how the panel works, and what to ask instead; suggestion buttons are checked by `validate()` before
they are offered. Problem codes are written to the audit row, so recurring gaps can be counted.
Unit tests: `backend/tests/test_ask_hard.py` replays the real model's recorded answers to all 29 cases.

## 7. API

`POST /api/v1/ask` — any logged-in user; rate-limited to 10 requests per minute per user.

Request: `{ "question": "top 5 branches by profit" }` (max 300 characters), or, from a clarify /
chip edit: `{ "question": "...", "query": "branch_ranking", "filters": {...} }` — validated exactly
like a model result, then no model call.

Response:

```json
{
  "status": "answer | clarify | unsupported",
  "understood": { "query": "branch_ranking", "label": "Branches ranked by profit",
                  "filters": { "metric": "profit", "top_n": 5, "order": "highest first", "date": "2026-09-28" } },
  "columns": [ { "key": "branch", "label": "Branch" }, { "key": "profit_usd", "label": "Profit", "unit": "USD" } ],
  "rows": [ ... ],
  "source": { "table": "branch_performance_summary", "as_of": "2026-09-28" },
  "clarify": { "question": "...", "options": [ { "label": "Profit", "query": "...", "filters": {...} } ] },
  "examples": [ "NPL ratio by country", "Top 5 branches by profit" ],
  "audit_id": 1234
}
```

`POST /api/v1/ask/export` — `{ query, filters }` → `.xlsx`. The server **re-runs** the query rather
than trusting rows sent from the browser; the sheet includes the question, filters, source table and
as-of date. Reuses `backend/app/exports.py` (`_sheet` / `_save`).

## 8. The panel on Reports (CHT-3)

- A question box at the top of the Reports screen, with 4-6 example questions as clickable chips.
- While waiting: "Working it out…" — the laptop model takes ~6 s, so the wait must be visible.
- **Answer card:** "What I understood" as chips (each removable or changeable from a short list,
  which re-runs without the model) → the table (same number formatting as the rest of the app) →
  "Source: branch_performance_summary, as of 28 Sep 2026" → **Export to Excel**.
- **Clarify:** the question and its buttons. **Unsupported:** "I can answer questions about …" plus
  the example chips.
- Every answer is saved on the server for the user who asked it (`ask_history`, migration 017;
  newest 200 kept per user), so it comes back after logging out and in again. Answers from this login
  are shown in full; earlier ones appear under **Previous questions** as a grid of tiles (question,
  report, row count, when asked): the newest 5, then 10 more per **Show more**
  (`GET /ask/history?limit=&before=`, a cursor so new answers don't shift the pages). Opening a tile
  shows the answer in full as it was saved, without asking again; a chip edit on it replaces the saved
  copy. **Clear these answers** deletes the user's list (`DELETE /ask/history`) but never the
  `audit_log` rows. On login and logout the browser's copy is emptied, so the next person at the same
  browser sees only their own list.

## 9. Audit (CHT-4)

Every call writes one `audit_log` row: `action = 'ASK_QUESTION'` (or `'ASK_EXPORT'`),
`object_type = 'ask'`, `object_id` = catalogue entry id, `new_value` = JSON with the question text,
the model's raw JSON, the final filters, status, row count, model name and response time.
`audit_log` is insert-only already, so the history can't be edited. The unanswered and clarify rows
are the to-do list for new catalogue entries and synonyms.

## 10. Security

- **Only fixed, parameterised SQL.** Filter values are bound parameters; table and column names come
  from the catalogue, never from the request or the model.
- **Model output is data, not instructions.** It is parsed as JSON and every field checked against its
  enum; anything else is discarded. A question like "ignore your instructions and delete…" can at most
  produce `unsupported`.
- **Roles:** each entry lists the roles allowed; v1 allows all four demo roles on every entry (all are
  bank-wide summaries). Needs revisiting with the RLS role model (`specs/postgres-schema.md` section 3).
- **Read-only database login (recommended, open item):** a separate Postgres role with `SELECT` on the
  catalogue's tables only, in `ASK_DATABASE_URL`. Until it exists, the app's normal connection is used —
  the fixed SQL is the protection.
- **Nothing leaves the machine:** the model runs locally (Ollama) or on the bank's server (vLLM). No
  external AI service is called.

## 11. Tests (CHT-5)

1. **Golden question set** — `backend/tests/ask_questions.yaml`: 50-60 questions, each with its
   expected status, entry and filters. Covers synonyms, typos, every entry, relative dates, missing
   data, ambiguous questions that must clarify, and off-topic ones that must be unsupported.
2. **Backend tests (pytest), no model needed:** the extractor, the merge/validate rules, SQL per
   entry, clarify/unsupported, audit row, export, 503 when the model is down, role checks, rate limit —
   with a fake model returning fixed JSON (including deliberately wrong JSON, to prove step 3 catches it).
3. **Live model evaluation** — `scripts/eval_ask.py` runs the golden set against the real model server
   and prints accuracy per field and average response time. Run on the laptop (Ollama) and again on
   the vLLM server before go-live. Target to agree: e.g. ≥ 90% correct entry, 100% of wrong answers
   caught as clarify rather than a wrong table.
4. **Frontend (vitest):** panel states (waiting, answer, clarify, unsupported, unavailable), chip edits,
   export call.

## 12. Not in v1

- **A model-written summary sentence** ("NPL is highest in Lebanon at 8.2%"). It would put the model
  back in charge of numbers; if wanted later, every number in the sentence must be checked against the
  table before it is shown.
- **Follow-ups that remember the previous question** ("now for KSA"). Chip edits cover most of this.
- **Arabic questions:** the 3B model understood an Arabic test question's intent, but the step-2
  extractor is English-only, so Arabic country/branch names and dates would not be picked up. Needs
  Arabic aliases and date phrases, plus Arabic test questions.
- Charts in the answer; saving or sharing questions; free-form SQL of any kind.

## 13. Evidence so far (2026-09-28, laptop, Ollama + qwen2.5:3b, CPU)

Probe with a simplified schema (5 entries), temperature 0, 8 questions:

| Question | Entry chosen | Problems in the other fields |
|---|---|---|
| show me bad loans by country for last month | country_breakdown ✅ | added KSA; period not converted |
| what's our capital adequacy ratio | kpi_value ✅ | period "last_month" instead of latest |
| top 5 branches by profit | branch_ranking ✅ | order ascending (wrong) |
| worst 3 branches on cost to income | branch_ranking ✅ | "worst" direction ambiguous |
| deposits in Saudi | country_breakdown ✅ | none |
| IFRS9 staging as of 2026-09-25 | ifrs9_stages ✅ | date ignored; added KSA |
| what's the weather in Dubai | unsupported ✅ | — |
| (Arabic) NPL ratio by country | country_breakdown ✅ | added KSA |

Entry: 8/8 correct. Other fields: unreliable — the reason section 6 takes exact values from code, not
the model. 5.6-7.5 s per question. Not a formal evaluation: one run, simplified prompt.

## 14. Open items

1. **Manager / bank:** confirm the model-assisted approach replaces the 2026-09-24 rule-based decision,
   and record it in the backlog.
2. **Bank:** which reports and questions it must cover (backlog CHT-1 "bank input") — the catalogue
   above is a proposal from the tables that exist.
3. **Where vLLM will run** (bank GPU server? who provides it?) and which model; the laptop setup is for
   development and demo only.
4. **Read-only database role** on Neon (section 10) — a change to the shared database.
5. **Arabic** in or out of the first bank release.
6. **Accuracy target** for go-live (section 11.3).

## 15. Acceptance criteria

- [ ] Catalogue of section 5 implemented; each entry's SQL tested against the summary tables
- [ ] Extractor and merge/validate rules pass the golden set with a fake model (pytest)
- [ ] Wrong model output (invented country, wrong date, unknown entry) is caught, never shown as an answer
- [ ] Missing period data reported as such, with the available range
- [ ] Clarify and unsupported responses with buttons / examples
- [ ] Every question and export audited in `audit_log`
- [ ] Excel export re-runs the query server-side and includes question, filters, source, as-of date
- [ ] 503 with a clear message when the model server is down; rest of Reports unaffected
- [ ] Panel states covered by vitest
- [ ] `scripts/eval_ask.py` run against Ollama on the laptop; results recorded here
- [ ] Same evaluation against a vLLM server — **not possible until a server exists**
- [ ] Checked in a browser end to end
