"""Roll the loaded demo dataset forward to a new business day, so "today" has its own data.

    backend/.venv/Scripts/python.exe scripts/generate_next_day.py --date 2026-09-25
        [--input resources/demo-cases] [--output resources/<date>]

Takes the 8 CSVs currently loaded (default: resources/demo-cases) and writes a full snapshot as of
--date: every day after the input's last transaction date, up to and including --date, gets
  * transactions: about as many per day as the last week averaged, resampled from that week's
    rows (same account, type, channel and currency mix) with the amount varied by up to +/-20%;
  * liquidity_daily: one row, a small random walk from the previous day;
  * fx_rates: one rate per currency pair, a small random walk from the previous day.
Plus two planted rows on --date itself, so the new day has explainable items (ids contain "DEMO"):
  * a 65,000 USD deposit to a Corporate customer: LARGE_AMOUNT (Threshold, goes to Compliance);
  * a transaction whose currency is "US$": INVALID_CURRENCY, rejected in cleaning, so "Received vs
    kept" shows a gap for that source and country, and the CFO gets a task.

Deliberately NOT changed: customers, accounts (balances included), loans, branches and
capital_positions. Account balances are what the core-banking comparison checks, and the stand-in
core-banking database is only re-synced by scripts/plant_core_system_breaks.py - changing balances
here would make every changed account look like a break. Deterministic: same input and date, same output.
"""
import argparse
import csv
import random
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = ["accounts", "branches", "capital_positions", "customers", "fx_rates", "liquidity_daily", "loans", "transactions"]
LOOKBACK_DAYS = 7


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
    parser.add_argument("--date", required=True, type=date.fromisoformat)
    parser.add_argument("--input", default=ROOT / "resources" / "demo-cases", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    today = args.date
    out = args.output or ROOT / "resources" / today.isoformat()
    rng = random.Random(today.toordinal())
    data = {name: read(args.input, name) for name in FILES}

    # ---- Transactions: resample last week's rows onto each new day ------------------------------
    tx_fields, txns = data["transactions"]
    dated = [t for t in txns if t["date"]]
    last_day = max(date.fromisoformat(t["date"]) for t in dated)
    days = [last_day + timedelta(days=n) for n in range(1, (today - last_day).days + 1)]
    if not days:
        raise SystemExit(f"The input already has transactions up to {last_day}; pick a later --date")
    recent = [t for t in dated if "DEMO" not in t["transaction_id"]
              and date.fromisoformat(t["date"]) > last_day - timedelta(days=LOOKBACK_DAYS)]
    per_day = round(len(recent) / LOOKBACK_DAYS)
    next_id = max(int(t["transaction_id"][2:]) for t in txns if t["transaction_id"][2:].isdigit()) + 1

    new_txns = []
    for day in days:
        for _ in range(per_day + rng.randint(-10, 10)):
            base = rng.choice(recent)
            amount = round(float(base["amount"]) * rng.uniform(0.8, 1.2), 2)
            new_txns.append({**base, "transaction_id": f"TN{next_id:05d}", "date": day.isoformat(), "amount": f"{amount:.2f}"})
            next_id += 1

    # Planted rows on the new day itself.
    _, customers = data["customers"]
    _, accounts = data["accounts"]
    segment = {c["customer_id"]: c["segment"] for c in customers}
    used = Counter(t["account_id"] for t in txns + new_txns)
    corporate_usd = sorted((a for a in accounts if a["currency"] == "USD" and segment.get(a["customer_id"]) == "Corporate"
                            and a["account_id"].startswith("ACN0")), key=lambda a: (used[a["account_id"]], a["account_id"]))
    large, bad_currency = corporate_usd[0], corporate_usd[1]
    new_txns.append({"transaction_id": f"TNDEMO{today:%m%d}A", "account_id": large["account_id"], "date": today.isoformat(),
                     "amount": "65000.00", "currency": "USD", "type": "Deposit", "channel": "Branch"})
    new_txns.append({"transaction_id": f"TNDEMO{today:%m%d}B", "account_id": bad_currency["account_id"], "date": today.isoformat(),
                     "amount": "2500.00", "currency": "US$", "type": "Transfer", "channel": "Online"})

    # ---- Liquidity: one row per new day, a small walk from the last one --------------------------
    liq_fields, liquidity = data["liquidity_daily"]
    prev = max(liquidity, key=lambda r: r["date"])
    new_liq = []
    for day in days:
        prev = {"date": day.isoformat(), **{k: str(round(float(prev[k]) * rng.uniform(0.992, 1.008)))
                                            for k in liq_fields if k != "date"}}
        new_liq.append(prev)

    # ---- FX: one rate per pair per new day -------------------------------------------------------
    fx_fields, fx = data["fx_rates"]
    latest = max(r["date"] for r in fx)
    rates = {r["currency_pair"]: float(r["rate"]) for r in fx if r["date"] == latest}
    new_fx = []
    for day in days:
        for pair in rates:
            rates[pair] *= rng.uniform(0.998, 1.002)
            new_fx.append({"date": day.isoformat(), "currency_pair": pair, "rate": f"{rates[pair]:.4f}"})

    out.mkdir(parents=True, exist_ok=True)
    for name in FILES:
        fields, rows = data[name]
        extra = {"transactions": new_txns, "liquidity_daily": new_liq, "fx_rates": new_fx}.get(name, [])
        write(out, name, fields, rows + extra)

    print(f"Snapshot as of {today} in {out}")
    print(f"  {len(new_txns) - 2} new transactions over {', '.join(d.isoformat() for d in days)} (~{per_day}/day)")
    print(f"  {len(new_liq)} liquidity row(s), {len(new_fx)} FX rate(s)")
    print(f"  planted: TNDEMO{today:%m%d}A 65,000 USD deposit on {large['account_id']} (LARGE_AMOUNT, Threshold)")
    print(f"  planted: TNDEMO{today:%m%d}B currency 'US$' on {bad_currency['account_id']} (INVALID_CURRENCY, received-vs-kept gap)")


if __name__ == "__main__":
    main()
