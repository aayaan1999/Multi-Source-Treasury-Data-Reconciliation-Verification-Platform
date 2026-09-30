# Upload test files, 30 Sep 2026

A full bank snapshot as of **30 Sep 2026**, made with `scripts/generate_next_day.py --date 2026-09-30` from
`bank-data/synthetic_2026-09-23`: 434 new transactions over 24-30 Sep (about 65 a day), a week of liquidity
and FX rates, and two planted rows on 30 Sep.

## Upload box on the Data ingestion tab

Sign in as the **CFO** or the **Platform Administrator** (others see the box but can't upload). The box
checks each file in the browser, then **sends it to the pipeline's landing folder in Databricks**, where it
replaces the file of the same name. Uploading the 8 `.csv` files therefore changes the live demo data
once the pipeline runs (see below).

| File | Expected |
|---|---|
| any of the 8 `.csv` files, or several at once | "Sending…", then "Sent to the pipeline as transactions.csv (N rows)…" on the file and in a toast |
| a renamed copy such as `Transactions_2026-09-30.csv` | Stored as `transactions.csv` |
| `branches.json` | "JSON isn't accepted: the pipeline reads CSV files" |
| a `.csv` with another name (e.g. `loans2.csv`) | "Not one of the pipeline's files (…)" |
| a `.csv` missing a column | The server's reason, e.g. "loans.csv is missing column(s) stage" |
| the same `.csv` dropped twice | The second one: "Already added" (sent once) |
| `bad-files/empty.csv` | "The file is empty" |
| `bad-files/README` | "No file type (add .csv)" |
| `bad-files/branch-notes.docx` | "DOCX isn't accepted: …" |
| `bad-files/archive.csv.zip` | "ZIP isn't accepted: …" |
| signed in as the Reconciliation Analyst | No Browse button; "Only the CFO or the Platform Administrator can upload files." |

## Running the pipeline on the uploaded files (changes the live data)

The job's automatic start (file-arrival trigger) is **paused** on the workspace, so each file's message says
"The automatic start is paused: press Run all sources now once all files are in." Upload all 8 files, then
press **Run all sources now** (top right). If the trigger is switched back on, the job starts by itself about
2 minutes after the last file. Expected afterwards:
- **TNDEMO0930A**: a 65,000 USD deposit on ACN0168 is flagged LARGE_AMOUNT (Threshold), a transaction case
  for the Compliance Officer.
- **TNDEMO0930B**: currency "US$" on ACN0361 is rejected (INVALID_CURRENCY), so "Received vs kept" shows a
  gap for that country's transactions and the Reconciliation Analyst gets a task; the older delivery's
  undecided items are replaced by the new ones.
- The executive summary's KPIs move to 30 Sep.

This snapshot is built from the local 23 Sep data, not from the exact files loaded in Databricks now (those also
hold earlier demo rows such as ACNDEMO1 and TNDEMO11). So a real run also changes existing results: earlier
planted rows disappear from "Received vs kept", and the core-banking comparison can report accounts or customers
as missing. The upload itself replaces the files in the landing folder straight away, so only upload the
8 files when a changed demo state is fine; the refused files (`bad-files/`, `branches.json`) are safe to try.
