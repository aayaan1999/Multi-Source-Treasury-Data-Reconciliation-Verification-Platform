"""Plant known demo cases into a copy of the bank CSVs, so every new feature has something to show
(client points 1, 3, 5, 6 and the agreed flow's reconciliation / completeness checks). The source
files are never changed; the planted copy goes to --output, with a CASES.md saying what each planted
row should trigger, so the live run can be checked against it.

    python scripts/make_demo_cases.py --input <folder with the 8 live CSVs> [--output resources/demo-cases]

Every planted row has "DEMO" in its id. Planted transactions use USD accounts that have no other
transactions, so each rule fires for exactly the planted reason. Deterministic: same input, same output.

Not planted here: breaches (point 8) come from the KPI history the pipeline builds day by day; the
core-system comparison (point 1) needs breaks in the separate demo core-system database, not these files.
"""
import argparse
import csv
import pathlib
from collections import Counter

FILES = ["accounts", "branches", "capital_positions", "customers", "fx_rates", "liquidity_daily", "loans", "transactions"]


def read(folder, name):
    with open(folder / f"{name}.csv", newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return reader.fieldnames, list(reader)


def write(folder, name, fields, rows):
    with open(folder / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=pathlib.Path)
    parser.add_argument("--output", default=pathlib.Path("resources/demo-cases"), type=pathlib.Path)
    args = parser.parse_args()
    data = {name: read(args.input, name) for name in FILES}
    args.output.mkdir(parents=True, exist_ok=True)

    _, customers = data["customers"]
    _, accounts = data["accounts"]
    tx_fields, transactions = data["transactions"]
    cases = []

    # Quiet USD accounts (no transactions at all), by segment, whose customer exists.
    busy = Counter(t["account_id"] for t in transactions)
    customer_by_id = {c["customer_id"]: c for c in customers}
    quiet = [a for a in accounts if a["currency"] == "USD" and busy[a["account_id"]] == 0 and a["customer_id"] in customer_by_id]
    by_segment = {seg: [a for a in quiet if customer_by_id[a["customer_id"]]["segment"] == seg] for seg in ("Retail", "SME", "Corporate")}
    pool = iter(by_segment["Corporate"] + by_segment["SME"])
    n = 0

    def tx(account, day, amount, kind, channel="Branch", currency="USD"):
        nonlocal n
        n += 1
        transactions.append({"transaction_id": f"TNDEMO{n:02d}", "account_id": account["account_id"], "date": day,
                             "amount": amount, "currency": currency, "type": kind, "channel": channel})
        return f"TNDEMO{n:02d}"

    # ---- Point 5: suspicious patterns (FRD-2) ----------------------------------------------------
    a = next(pool)
    ids = [tx(a, "2026-02-10", "150.00", "Deposit"), tx(a, "2026-09-20", "30000.00", "Deposit")]
    cases.append(("5", "DORMANT_REACTIVATION", f"{ids[1]} on {a['account_id']}: quiet since {ids[0]} (2026-02-10), then 30,000 USD"))

    a = next(pool)
    ids = [tx(a, "2026-09-15", "25000.00", "Deposit", "Online"), tx(a, "2026-09-15", "-24000.00", "Withdrawal", "Online")]
    cases.append(("5", "PASS_THROUGH", f"{ids[0]} in, {ids[1]} out the same day on {a['account_id']} (both flagged)"))

    a = next(pool)
    ids = [tx(a, "2026-09-18", amt, "Deposit") for amt in ("5000.00", "10000.00", "20000.00")]
    cases.append(("5", "ROUND_AMOUNTS", f"{', '.join(ids)} on {a['account_id']}, 2026-09-18"))

    # A second account for the owner of a quiet one, so one customer has two quiet accounts.
    first = next(pool)
    second = {**first, "account_id": "ACNDEMO2", "type": "Savings", "balance": "40000.00"}
    accounts.append(second)
    twin = [first, second]
    ids = [tx(twin[0], "2026-09-19", "-9200.00", "Withdrawal", "ATM"), tx(twin[1], "2026-09-19", "-9300.00", "Withdrawal", "ATM")]
    cases.append(("5", "SPLIT_ACROSS_ACCOUNTS", f"{ids[0]} and {ids[1]}: customer {twin[0]['customer_id']} just under 10,000 on two accounts, 2026-09-19"))

    r = by_segment["Retail"][0]
    rid = tx(r, "2026-09-21", "80000.00", "Deposit")
    cases.append(("5", "UNUSUAL_FOR_SEGMENT (+ LARGE_AMOUNT, Threshold)", f"{rid}: 80,000 USD for Retail customer {r['customer_id']}"))
    cases.append(("6", "Task cases", "the planted flags group into cases per account + day + type: e.g. the 3 round amounts are one case, "
                  "the pass-through pair one case; the 80,000 deposit makes one Suspicious case and one Threshold case"))

    # ---- Agreed flow step 3: received vs kept (FLOW-3) -------------------------------------------
    lebanon_usd = next(acc for acc in accounts if acc["currency"] == "USD" and customer_by_id.get(acc["customer_id"], {}).get("country") == "Lebanon")
    bad_amount = tx(lebanon_usd, "2026-09-22", "", "Deposit")
    bad_channel = tx(lebanon_usd, "2026-09-22", "4000.00", "Deposit", "Cheque")
    cases.append(("FLOW-3", "Rejected transactions", f"{bad_amount} (no amount, INVALID_AMOUNT) and {bad_channel} (channel Cheque, INVALID_CHANNEL) "
                  f"on {lebanon_usd['account_id']}: a Lebanon transactions gap, 2 rows / 4,000 USD, opening onto both records"))
    accounts.append({**lebanon_usd, "account_id": "ACNDEMO1", "currency": "XYZ", "balance": "50000.00"})
    cases.append(("FLOW-3", "Rejected account", "ACNDEMO1 with currency XYZ (INVALID_CURRENCY): an accounts gap with an XYZ amount line; "
                  "a CFO can correct its currency to USD (FLOW-5) and Refresh Now closes the gap"))

    # Agreed flow step 1 (completeness, FLOW-1b) is no longer planted: emptying fx_rates.csv left a
    # blank "No rows delivered" row on the Reconciliation tab that read as broken data in the demo.

    # ---- Point 3: duplicate companies ------------------------------------------------------------
    cust_fields, _ = data["customers"]
    corporates = [c for c in customers if c["segment"] == "Corporate" and c["name"].upper().endswith(" SAL")]
    base = corporates[0]
    customers.append({**base, "customer_id": "CNDEMO1", "name": base["name"][:-4] + " S.A.L."})
    cases.append(("3", "Same name, dotted legal word", f"CNDEMO1 '{base['name'][:-4]} S.A.L.' vs {base['customer_id']} '{base['name']}': 100%"))
    base2 = corporates[1]
    typo = base2["name"][:-4].rstrip("s") + "s SAL" if not base2["name"][:-4].endswith("s") else base2["name"][:-5] + " SAL"
    customers.append({**base2, "customer_id": "CNDEMO2", "name": typo})
    cases.append(("3", "Near-identical name", f"CNDEMO2 '{typo}' vs {base2['customer_id']} '{base2['name']}'"))
    customers.append({**base, "customer_id": "CNDEMO3", "name": "Tata Consultancy Services Ltd."})
    customers.append({**base, "customer_id": "CNDEMO4", "name": "TCS"})
    cases.append(("3", "Abbreviation", "CNDEMO3 'Tata Consultancy Services Ltd.' vs CNDEMO4 'TCS' (the abbreviation list)"))
    loan_fields, loans = data["loans"]
    template = loans[0]
    for i, cid in enumerate(("CNDEMO3", "CNDEMO4"), start=1):
        loans.append({**template, "loan_id": f"LNDEMO{i}", "customer_id": cid, "currency": "USD", "principal": "3000000.00",
                      "outstanding": "2500000.00", "days_past_due": "0", "stage": "1", "provision_amount": "25000.00"})
    cases.append(("3", "Exposure roll-up", "confirming CNDEMO3 = CNDEMO4 makes one 5,000,000 USD exposure in the top-20 list after the next run"))

    for name in FILES:
        fields, rows = data[name]
        write(args.output, name, fields, rows)
    lines = ["# Planted demo cases", "", f"Built by `scripts/make_demo_cases.py` from `{args.input}`.", "",
             "| Point | Case | Planted rows and what they should trigger |", "|---|---|---|"]
    lines += [f"| {p} | {c} | {d} |" for p, c, d in cases]
    (args.output / "CASES.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
