"""Generate a larger, referentially-consistent synthetic bank dataset for the 8-table bank-wide
schema (customers, accounts, loans, transactions, branches, capital_positions, liquidity_daily,
fx_rates - see "Middle East bank data cleaning and reporting.md"). Unlike bank-data/*.csv (small,
deliberately dirty fixtures for Notebook 2's data-quality checks), this output is clean and sized
for scale/performance testing of the application layer.

Usage:
    backend/.venv/Scripts/python.exe scripts/generate_synthetic_bank_data.py

Writes to bank-data/synthetic_<today>/ (dated files) and .../upload-ready/ (plain names, matching
the bank-data/synthetic_2026-09-22/ convention already in the repo).
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(42)

TODAY = date(2026, 9, 23)
ROOT = Path(__file__).resolve().parent.parent / "bank-data" / f"synthetic_{TODAY.isoformat()}"
UPLOAD_READY = ROOT / "upload-ready"

N_BRANCHES = 15
N_CUSTOMERS = 400
N_ACCOUNTS = 600
N_LOANS = 180
N_TRANSACTIONS = 2000
N_CAPITAL_MONTHS = 12
N_LIQUIDITY_DAYS = 90
N_FX_DAYS = 60

REGIONS = ["Beirut", "North", "Bekaa", "South", "Mount Lebanon"]
BRANCH_TOWNS = {
    "Beirut": ["Beirut Central", "Beirut Hamra", "Beirut Ashrafieh", "Beirut Verdun"],
    "North": ["Tripoli North", "Zgharta", "Koura"],
    "Bekaa": ["Zahle", "Baalbek"],
    "South": ["Saida", "Tyre", "Nabatieh"],
    "Mount Lebanon": ["Jounieh", "Baabda", "Aley"],
}
COUNTRIES = ["Lebanon", "Saudi Arabia", "Qatar"]
COUNTRY_WEIGHTS = [0.7, 0.18, 0.12]
CURRENCY_BY_COUNTRY = {"Lebanon": "LBP", "Saudi Arabia": "SAR", "Qatar": "QAR"}
FX_PAIRS = ["USD/LBP", "USD/SAR", "USD/QAR"]
FX_BASE_RATE = {"USD/LBP": 89500.0, "USD/SAR": 3.75, "USD/QAR": 3.64}
FX_DAILY_VOL = {"USD/LBP": 400.0, "USD/SAR": 0.01, "USD/QAR": 0.01}

SEGMENTS = ["Retail", "SME", "Corporate"]
SEGMENT_WEIGHTS = [0.65, 0.25, 0.10]
RISK_RATINGS = ["A", "B", "C", "D"]
RISK_WEIGHTS = [0.35, 0.4, 0.2, 0.05]

ACCOUNT_TYPES = ["Current", "Savings", "Term deposit"]
ACCOUNT_TYPE_WEIGHTS = [0.5, 0.35, 0.15]
ACCOUNT_CURRENCIES = ["USD", "LBP", "SAR", "QAR"]
ACCOUNT_CURRENCY_WEIGHTS = [0.55, 0.25, 0.12, 0.08]

LOAN_PRODUCTS = ["Corporate", "Mortgage", "SME", "Personal", "Auto"]
LOAN_PRODUCT_WEIGHTS = [0.22, 0.28, 0.2, 0.2, 0.1]

TXN_TYPES = ["Deposit", "Withdrawal", "Transfer", "Payment"]
TXN_CHANNELS = ["Branch", "ATM", "Mobile", "Online"]

FIRST_NAMES = ["Rana", "Karim", "Yasmine", "Elie", "Layla", "Fadi", "Maya", "Omar", "Nour", "Sami",
               "Dana", "Ziad", "Rania", "Marwan", "Lina", "Tarek", "Salma", "Hadi", "Reem", "Jad"]
LAST_NAMES = ["Haddad", "Khoury", "Daher", "Aoun", "Saad", "Chami", "Nassar", "Fares", "Abdallah", "Ghosn"]
CORP_NAMES = ["Trading SAL", "Holdings LLC", "Industries SAL", "Capital LLC", "Logistics SAL",
              "Foods SAL", "Textiles LLC", "Construction SAL", "Pharma LLC", "Retail Group SAL"]
CORP_STEMS = ["Khalil", "Aoun", "Cedar", "Beirut", "Levant", "Atlas", "Phoenix", "Orient", "Zahle", "Byblos"]


def rand_date(start: date, end: date) -> date:
    span = (end - start).days
    return start + timedelta(days=random.randint(0, span))


def weighted(options, weights):
    return random.choices(options, weights=weights, k=1)[0]


def gen_branches():
    rows = []
    i = 0
    for region in REGIONS:
        for town in BRANCH_TOWNS[region]:
            i += 1
            if i > N_BRANCHES:
                break
            rows.append({
                "branch_id": f"BN{i:02d}",
                "name": town,
                "region": region,
                "staff_count": random.randint(8, 55),
                "monthly_opex": round(random.uniform(60000, 260000), 2),
            })
    return rows[:N_BRANCHES]


def gen_customers(branches):
    rows = []
    for i in range(1, N_CUSTOMERS + 1):
        segment = weighted(SEGMENTS, SEGMENT_WEIGHTS)
        is_corp = segment in ("SME", "Corporate")
        name = f"{random.choice(CORP_STEMS)} {random.choice(CORP_NAMES)}" if is_corp else f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        rows.append({
            "customer_id": f"CN{i:04d}",
            "name": name,
            "segment": segment,
            "branch_id": random.choice(branches)["branch_id"],
            "onboard_date": rand_date(date(2014, 1, 1), TODAY).isoformat(),
            "risk_rating": weighted(RISK_RATINGS, RISK_WEIGHTS),
            "country": weighted(COUNTRIES, COUNTRY_WEIGHTS),
        })
    return rows


def gen_accounts(customers):
    rows = []
    for i in range(1, N_ACCOUNTS + 1):
        cust = random.choice(customers)
        acc_type = weighted(ACCOUNT_TYPES, ACCOUNT_TYPE_WEIGHTS)
        currency = weighted(ACCOUNT_CURRENCIES, ACCOUNT_CURRENCY_WEIGHTS)
        balance_scale = {"USD": 1, "SAR": 3.75, "QAR": 3.64, "LBP": 89500}[currency]
        base = random.uniform(500, 500000) if acc_type != "Corporate" else random.uniform(5000, 2000000)
        onboard = date.fromisoformat(cust["onboard_date"])
        rows.append({
            "account_id": f"ACN{i:04d}",
            "customer_id": cust["customer_id"],
            "type": acc_type,
            "currency": currency,
            "balance": round(base * balance_scale, 2),
            "open_date": rand_date(onboard, TODAY).isoformat(),
        })
    return rows


def gen_loans(customers):
    rows = []
    for i in range(1, N_LOANS + 1):
        cust = random.choice(customers)
        product = weighted(LOAN_PRODUCTS, LOAN_PRODUCT_WEIGHTS)
        principal = round(random.uniform(20000, 2000000) if product in ("Corporate", "Mortgage") else random.uniform(5000, 150000), 2)
        origination = rand_date(date(2015, 1, 1), date(2026, 6, 1))
        term_years = random.choice([5, 7, 10, 15, 20, 25]) if product in ("Mortgage", "Corporate") else random.choice([2, 3, 5])
        maturity = date(origination.year + term_years, origination.month, min(origination.day, 28))
        dpd = weighted([0, 0, 0, 15, 45, 95, 200], [0.6, 0.1, 0.1, 0.08, 0.06, 0.04, 0.02])
        stage = 1 if dpd == 0 else (2 if dpd < 90 else 3)
        outstanding = round(principal * random.uniform(0.4, 0.98), 2)
        provision_rate = {1: 0.01, 2: 0.1, 3: 0.4}[stage]
        rows.append({
            "loan_id": f"LN{i:04d}",
            "customer_id": cust["customer_id"],
            "product": product,
            "principal": principal,
            "outstanding": outstanding,
            "currency": "USD",
            "interest_rate": round(random.uniform(3.5, 14.0), 2),
            "origination_date": origination.isoformat(),
            "maturity_date": maturity.isoformat(),
            "days_past_due": dpd,
            "stage": stage,
            "provision_amount": round(outstanding * provision_rate, 2),
            "collateral_value": round(principal * random.uniform(0.9, 1.6), 2) if product in ("Mortgage", "Corporate", "Auto") else 0,
        })
    return rows


def gen_transactions(accounts):
    rows = []
    window_start = TODAY - timedelta(days=30)
    for i in range(1, N_TRANSACTIONS + 1):
        acc = random.choice(accounts)
        txn_type = weighted(TXN_TYPES, [0.3, 0.25, 0.3, 0.15])
        amount = round(random.uniform(20, 25000), 2)
        if txn_type in ("Withdrawal", "Payment"):
            amount = -amount
        rows.append({
            "transaction_id": f"TN{i:05d}",
            "account_id": acc["account_id"],
            "date": rand_date(window_start, TODAY).isoformat(),
            "amount": amount,
            "currency": acc["currency"] if random.random() > 0.15 else random.choice(ACCOUNT_CURRENCIES),
            "type": txn_type,
            "channel": weighted(TXN_CHANNELS, [0.2, 0.25, 0.4, 0.15]),
        })
    rows.sort(key=lambda r: r["date"])
    return rows


def gen_capital_positions():
    rows = []
    tier1 = 200_000_000.0
    tier2 = 35_000_000.0
    rwa = 1_900_000_000.0
    month = date(TODAY.year, TODAY.month, 1)
    months = []
    for _ in range(N_CAPITAL_MONTHS):
        months.append(month)
        month = date(month.year - 1, 12, 1) if month.month == 1 else date(month.year, month.month - 1, 1)
    for m in sorted(months):
        tier1 *= random.uniform(0.995, 1.015)
        tier2 *= random.uniform(0.99, 1.02)
        rwa *= random.uniform(0.995, 1.02)
        rows.append({
            "month": f"{m.year:04d}-{m.month:02d}",
            "tier1_capital": round(tier1, 2),
            "tier2_capital": round(tier2, 2),
            "risk_weighted_assets": round(rwa, 2),
        })
    return rows


def gen_liquidity_daily():
    rows = []
    hqla = 500_000_000.0
    outflows = 350_000_000.0
    stable_funding = 600_000_000.0
    required_funding = 550_000_000.0
    d = TODAY - timedelta(days=N_LIQUIDITY_DAYS - 1)
    for _ in range(N_LIQUIDITY_DAYS):
        hqla *= random.uniform(0.99, 1.012)
        outflows *= random.uniform(0.985, 1.015)
        stable_funding *= random.uniform(0.995, 1.008)
        required_funding *= random.uniform(0.995, 1.008)
        rows.append({
            "date": d.isoformat(),
            "hqla": round(hqla, 2),
            "net_outflows_30d": round(outflows, 2),
            "stable_funding": round(stable_funding, 2),
            "required_funding": round(required_funding, 2),
        })
        d += timedelta(days=1)
    return rows


def gen_fx_rates():
    rows = []
    d = TODAY - timedelta(days=N_FX_DAYS - 1)
    rate = dict(FX_BASE_RATE)
    for _ in range(N_FX_DAYS):
        for pair in FX_PAIRS:
            rate[pair] *= random.uniform(1 - FX_DAILY_VOL[pair] / rate[pair] * 0.1, 1 + FX_DAILY_VOL[pair] / rate[pair] * 0.1)
            rows.append({"date": d.isoformat(), "currency_pair": pair, "rate": round(rate[pair], 4)})
        d += timedelta(days=1)
    return rows


def write_csv(path: Path, rows, fieldnames):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def main():
    branches = gen_branches()
    customers = gen_customers(branches)
    accounts = gen_accounts(customers)
    loans = gen_loans(customers)
    transactions = gen_transactions(accounts)
    capital_positions = gen_capital_positions()
    liquidity_daily = gen_liquidity_daily()
    fx_rates = gen_fx_rates()

    tables = {
        "branches": (branches, ["branch_id", "name", "region", "staff_count", "monthly_opex"]),
        "customers": (customers, ["customer_id", "name", "segment", "branch_id", "onboard_date", "risk_rating", "country"]),
        "accounts": (accounts, ["account_id", "customer_id", "type", "currency", "balance", "open_date"]),
        "loans": (loans, ["loan_id", "customer_id", "product", "principal", "outstanding", "currency", "interest_rate",
                           "origination_date", "maturity_date", "days_past_due", "stage", "provision_amount", "collateral_value"]),
        "transactions": (transactions, ["transaction_id", "account_id", "date", "amount", "currency", "type", "channel"]),
        "capital_positions": (capital_positions, ["month", "tier1_capital", "tier2_capital", "risk_weighted_assets"]),
        "liquidity_daily": (liquidity_daily, ["date", "hqla", "net_outflows_30d", "stable_funding", "required_funding"]),
        "fx_rates": (fx_rates, ["date", "currency_pair", "rate"]),
    }

    for name, (rows, fields) in tables.items():
        write_csv(ROOT / f"{name}_{TODAY.isoformat()}.csv", rows, fields)
        write_csv(UPLOAD_READY / f"{name}.csv", rows, fields)
        print(f"{name}: {len(rows)} rows")


if __name__ == "__main__":
    main()
