# Upload test files, 1 Oct 2026

The demo's next business day. Made with

    backend/.venv/Scripts/python.exe scripts/generate_next_day.py --date 2026-10-01 \
        --input bank-data/demo-baseline_2026-09-29 --output bank-data/upload-test_2026-10-01

from `bank-data/demo-baseline_2026-09-29/`, the data the demo actually holds (recovered from Databricks on
30 Sep). Unlike the 30 Sep set, this is the **same bank**: customers, accounts, loans, branches and capital
positions are unchanged, byte for byte. What's new:

- **440 transactions** over 29 Sep, 30 Sep and 1 Oct (about 147 a day, resampled from the last week, amounts
  varied by up to ±20%), ids TN01894 to TN02331, none reused.
- **3 liquidity rows** and **18 FX rates**, one per day.
- **Two planted rows on 1 Oct:**
  - **TNDEMO1001A**: a 65,000 USD deposit on ACN0164 (Sabbagh Ventures SAL, Corporate, Beirut): flagged
    LARGE_AMOUNT, a fraud case for the Compliance Officer.
  - **TNDEMO1001B**: currency "US$" on ACN0224 (Daher Ventures LLC, Corporate, a KSA branch): rejected in
    cleaning (INVALID_CURRENCY), so Saudi Arabia's transactions show a gap of 2 instead of 1.

## How to run it

1. Sign in as the **CFO** or the **Platform Administrator** and open **Data ingestion**.
2. Drop all 8 `.csv` files on **Upload files**. Each should say "Sent to the pipeline as … (N rows). The automatic
   start is paused: press Run All Sources once all files are in." None should be held: checked on 30 Sep, the
   files remove no customers, accounts, loans or branches.
3. Press **Run All Sources**. The run takes about 6 minutes; the poll worker picks up its results within 5 more.

## What to expect afterwards

| Where | Expected |
|---|---|
| Data ingestion | A new run: 8 files, 18 loads, no failed loads; about 440 more rows received than the 29 Sep run (2,635), 6 held back instead of 5 |
| Reconciliation / Tasks | A new delivery with **3 gaps**: Lebanon accounts (1 held back), Lebanon transactions (3), Saudi Arabia transactions (**2**: the old one plus TNDEMO1001B). The previous delivery's undecided gap tasks are retired, not duplicated |
| Compliance Officer's tasks | A fraud case for TNDEMO1001A (LARGE_AMOUNT). The resampled transactions may raise a few other rule hits (velocity, round amounts); older cases and their decisions are kept |
| CRM comparison | **3 new breaks** from the day-2 Salesforce changes (`scripts/plant_salesforce_changes_day2.py`, applied 30 Sep): CNCRM02 "Cedar Bay Shipping SAL" in the CRM but missing from our data (Important, goes to the CFO); CN0013 name "Ghosn Traders Group" in the CRM vs "Ghosn Traders SAL" here (key field, Important); CN0015 country United Arab Emirates vs Saudi Arabia (a team decision). CN0022 "SARKIS FOODS L.L.C." is formatting only and cleared automatically. The 4 day-1 breaks are found again, no new tasks for them. These come from Salesforce, not from the files, so any run shows them, with or without this upload |
| Duplicate customers | No new reviews: the customers haven't changed |
| Executive summary | KPIs recalculated for the run date; liquidity and FX move to 1 Oct |

If anything else appears in bulk (hundreds of tasks, a "check the file that was loaded" task), stop and look at
the upload before deciding anything; `demo-baseline_2026-09-29/` is the copy to restore from.

Not checked yet: only the file checks above were run (columns, the upload's replace check against the live
platform, planted rows, no reused ids). The pipeline hasn't been run on this set.
