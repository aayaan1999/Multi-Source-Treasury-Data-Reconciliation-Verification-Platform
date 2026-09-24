"""Generate three consecutive days of demo data (resources/<date>/, 8 CSVs each) for the CFO/COO
walkthrough, built on the dataset currently loaded (bank-data/synthetic_2026-09-22/upload-ready/).

    backend/.venv/Scripts/python.exe scripts/generate_demo_days.py

Each folder is a full snapshot "as of" that date (the pipeline full-refreshes the entity tables on
every load), so the folders are loaded oldest first, each with the pipeline's `calculation_date`
parameter set to the folder's date - that is what gives the dashboard a 3-point trend.

The story the numbers tell (printed at the end as a KPI preview using Notebook 3's formulas):
  * Capital ratio slides 13.4% -> 13.0% -> 12.4% (risk-weighted assets growing): "Action needed",
    only 0.4 points above the 12% regulatory minimum on the last day.
  * Bad loans (NPL) climb 4.1% -> 4.6% -> 5.2% as three loans roll past 90 days: breaches the 5%
    internal limit on the last day.
  * Liquidity eases 138% -> 131% -> 126% (still comfortably above 100%).
  * Dollarization improves ~73% -> ~71% -> ~68% as LBP deposits grow (drops below the 70% limit).
  * New fraud flags every day (large amount, structuring, velocity, duplicate) plus one new
    data-quality problem per day, so the Tasks queue has fresh, explainable items.

Deliberately NOT changed, so reconciliation against the second Neon project ("core banking
system") keeps finding only its planted differences: customers.csv is copied as-is, and accounts
ACN0001-ACN0032 (the sample that project was seeded from) keep their exact values.
"""
import csv
import random
from datetime import date, timedelta
from pathlib import Path

random.seed(2026_09_23)

ROOT = Path(__file__).resolve().parent.parent
BASE = ROOT / "bank-data" / "synthetic_2026-09-22" / "upload-ready"
OUT = ROOT / "resources"
DAYS = [date(2026, 9, 21), date(2026, 9, 22), date(2026, 9, 23)]
TXN_START = date(2026, 9, 1)

# Accounts the core-banking stand-in was seeded from - never modified.
CORE_SAMPLE = {f"ACN{i:04d}" for i in range(1, 33)}

# Scale factors that make the base data's ratios bank-like: the base loan book (~$39M) is tiny next
# to its capital (~$218M tier 1), which put ROE near 0% and cost-to-income at 24%. Capital is
# scaled as a whole (tier 1, tier 2 and RWA together), so the capital ratio history is unchanged.
LOAN_SCALE = 3.0
CAPITAL_SCALE = 0.15
OPEX_SCALE = 6.0
LBP_PER_USD = 89_500  # LBP balances in the base data are USD-sized numbers; make them real LBP amounts

# Per-day targets.
CAR_TARGET = {DAYS[0]: 13.4, DAYS[1]: 13.0, DAYS[2]: 12.4}
LCR_TARGET = {DAYS[0]: 138.0, DAYS[1]: 131.0, DAYS[2]: 126.0}
LBP_GROWTH = {DAYS[0]: 1.67, DAYS[1]: 1.85, DAYS[2]: 2.13}  # multiplier on LBP deposit base

FX = {"USD": 1.0, "EUR": 1 / 1.09, "LBP": 89_300.0, "SAR": 3.75, "QAR": 3.64}  # preview only


def read(name):
    with open(BASE / f"{name}.csv", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def write(folder, name, rows, fields):
    folder.mkdir(parents=True, exist_ok=True)
    with open(folder / f"{name}.csv", "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)


customers = read("customers")
accounts_base = read("accounts")
loans_base = read("loans")
branches_base = read("branches")
capital_base = read("capital_positions")
acct_by_id = {a["account_id"]: a for a in accounts_base}

# --- Loans: scale up, then decide which loans are 90+ days past due on each day. -------------------
def money(v):
    return f"{v:.2f}"

loans_scaled = []
for l in loans_base:
    l = dict(l)
    for col in ("principal", "outstanding", "provision_amount", "collateral_value"):
        l[col] = money(float(l[col]) * LOAN_SCALE)
    loans_scaled.append(l)

# Loan IDs picked by size from the base book (share of outstanding in brackets) so NPL lands on
# ~4.1% -> ~4.6% -> ~5.2%. Base NPL is 5.9%; these three are moved to stage 2 (74 dpd) on every day:
NOT_NPL = {"LN0002", "LN0011", "LN0023"}  # 1.01% + 0.33% + 0.19%
# ...and these cross 90 days past due on their roll day (stage 2 and ageing before it):
ROLLS_ON = {"LN0016": DAYS[1], "LN0060": DAYS[2], "LN0005": DAYS[2]}  # 0.50%, 0.30%, 0.33%
DQ_LOAN = "LN0059"  # planted NPL_STAGE_MISMATCH (97 dpd, still stage 2); tiny, so it barely moves NPL


def loans_for(day):
    out = []
    for l in loans_scaled:
        l = dict(l)
        if l["loan_id"] in NOT_NPL:
            l.update(days_past_due="74", stage="2")
        elif l["loan_id"] in ROLLS_ON:
            # Already stage 2 and ageing; crosses 90 days past due on its roll day (becomes an NPL).
            dpd = 90 + (day - ROLLS_ON[l["loan_id"]]).days
            if dpd >= 90:
                l.update(days_past_due=str(dpd), stage="3", provision_amount=money(float(l["outstanding"]) * 0.35))
            else:
                l.update(days_past_due=str(dpd), stage="2")
        if l["loan_id"] == DQ_LOAN:
            l.update(days_past_due="97", stage="2")
        out.append(l)
    return out


# --- Accounts: LBP deposits become real LBP amounts and grow day by day (core sample untouched). ---
def accounts_for(day):
    out = []
    for a in accounts_base:
        a = dict(a)
        if a["currency"] == "LBP" and a["account_id"] not in CORE_SAMPLE:
            a["balance"] = money(float(a["balance"]) * LBP_PER_USD * LBP_GROWTH[day])
        out.append(a)
    return out


# --- Branches: opex scaled so cost-to-income lands in a realistic 40-55% band. ---------------------
branches = [dict(b, monthly_opex=str(round(int(b["monthly_opex"]) * OPEX_SCALE))) for b in branches_base]

# --- Capital: scaled history; September's RWA restated each day to hit the CAR target. ------------
def capital_for(day):
    out = []
    for c in capital_base:
        t1, t2, rwa = (round(float(c[k]) * CAPITAL_SCALE) for k in ("tier1_capital", "tier2_capital", "risk_weighted_assets"))
        if c["month"] == "2026-09":
            rwa = round((t1 + t2) / (CAR_TARGET[day] / 100))
        out.append({"month": c["month"], "tier1_capital": t1, "tier2_capital": t2, "risk_weighted_assets": rwa})
    return out


# --- Liquidity: one consistent daily series; each file carries the rows up to its own date. -------
LIQ_START = date(2026, 8, 25)
liquidity_series = []
d = LIQ_START
while d <= DAYS[-1]:
    outflows = 35_000_000 * (1 + random.uniform(-0.02, 0.02))
    lcr = LCR_TARGET.get(d, 141 + random.uniform(-2.5, 2.5))
    stable = 60_000_000 * (1 + random.uniform(-0.01, 0.01))
    liquidity_series.append({
        "date": d.isoformat(), "hqla": round(outflows * lcr / 100), "net_outflows_30d": round(outflows),
        "stable_funding": round(stable), "required_funding": round(stable / 1.11),
    })
    d += timedelta(days=1)

# --- FX rates: same six pairs as the base file, one row per pair per day. -------------------------
FX_BASE = {"USD/LBP": 89_300.0, "USD/SAR": 3.7500, "USD/QAR": 3.6410, "EUR/USD": 1.0930, "GBP/USD": 1.2670, "USD/AED": 3.6725}
fx_series = []
d = LIQ_START
while d <= DAYS[-1]:
    for pair, base in FX_BASE.items():
        fx_series.append({"date": d.isoformat(), "currency_pair": pair, "rate": f"{base * (1 + random.uniform(-0.002, 0.002)):.4f}"})
    d += timedelta(days=1)

# --- Transactions: clean background activity (no rule fires by accident) plus planted cases. ------
TYPES = ["Deposit"] * 34 + ["Withdrawal"] * 30 + ["Transfer"] * 25 + ["Fee"] * 11
CHANNELS = ["Mobile"] * 43 + ["Online"] * 23 + ["ATM"] * 20 + ["Branch"] * 14
eligible = [a for a in accounts_base if a["account_id"] not in CORE_SAMPLE]

background = []
per_acct_day = {}
d = TXN_START
while d <= DAYS[-1]:
    for _ in range(random.randint(125, 150)):
        a = random.choice(eligible)
        key = (a["account_id"], d)
        if per_acct_day.get(key, 0) >= 2:  # >2 same-day would fire VELOCITY_BREACH
            continue
        per_acct_day[key] = per_acct_day.get(key, 0) + 1
        typ = random.choice(TYPES)
        usd = random.uniform(8, 60) if typ == "Fee" else min(random.lognormvariate(8.5, 0.8), 19_500)
        amount = usd * (LBP_PER_USD if a["currency"] == "LBP" else FX[a["currency"]])
        if 8_400 <= amount < 10_100:  # the structuring rule checks the native amount: keep that band for planted cases
            amount = random.choice([7_800.0, 11_200.0])
        background.append({"account_id": a["account_id"], "date": d.isoformat(), "amount": money(amount),
                           "currency": a["currency"], "type": typ, "channel": random.choice(CHANNELS)})
    d += timedelta(days=1)

usd_free = [a["account_id"] for a in eligible if a["currency"] == "USD" and not any(k[0] == a["account_id"] for k in per_acct_day)]
eur_free = [a["account_id"] for a in eligible if a["currency"] == "EUR" and not any(k[0] == a["account_id"] for k in per_acct_day)]
if len(usd_free) < 6 or not eur_free:  # fall back to accounts with no activity on the planted days
    busy = {k[0] for k in per_acct_day if k[1] in DAYS}
    usd_free = [a["account_id"] for a in eligible if a["currency"] == "USD" and a["account_id"] not in busy]
    eur_free = [a["account_id"] for a in eligible if a["currency"] == "EUR" and a["account_id"] not in busy]


def t(acct, day, amount, typ, channel, currency="USD"):
    return {"account_id": acct, "date": day.isoformat(), "amount": money(amount), "currency": currency, "type": typ, "channel": channel}


planted = [
    # 21 Sep: a large wire, and two deposits just under 10,000 on one account (structuring).
    t(usd_free[0], DAYS[0], 185_000, "Transfer", "Branch"),
    t(usd_free[1], DAYS[0], 9_400, "Deposit", "Branch"),
    t(usd_free[1], DAYS[0], 9_750, "Deposit", "ATM"),
    # 22 Sep: four mobile transfers in one day (velocity), and the same ATM withdrawal posted twice.
    *[t(usd_free[2], DAYS[1], amt, "Transfer", "Mobile") for amt in (1_250, 2_900, 4_100, 3_350)],
    t(usd_free[3], DAYS[1], 2_450, "Withdrawal", "ATM"),
    t(usd_free[3], DAYS[1], 2_450, "Withdrawal", "ATM"),
    # 23 Sep: a large EUR transfer, another structuring pair, and three rapid online payments.
    t(eur_free[0], DAYS[2], 96_000, "Transfer", "Online", "EUR"),
    t(usd_free[4], DAYS[2], 9_200, "Deposit", "Branch"),
    t(usd_free[4], DAYS[2], 9_880, "Deposit", "Branch"),
    *[t(usd_free[5], DAYS[2], amt, "Transfer", "Online") for amt in (3_800, 6_250, 5_400)],
]
dq_txns = [
    t(eligible[40]["account_id"], DAYS[1], 640, "Withdrawal", "Telephone", eligible[40]["currency"]),  # INVALID_CHANNEL
    t("ACN0999", DAYS[2], 5_300, "Deposit", "Online"),  # ORPHAN_ACCOUNT - no such account
]
if eligible[40]["currency"] == "LBP":
    dq_txns[0]["amount"] = money(640 * LBP_PER_USD)

all_txns = sorted(background + planted + dq_txns, key=lambda r: r["date"])
for i, r in enumerate(all_txns, start=1):
    r["transaction_id"] = f"TN{30000 + i:05d}"

# --- Write the three folders. ----------------------------------------------------------------------
TXN_FIELDS = ["transaction_id", "account_id", "date", "amount", "currency", "type", "channel"]
preview = []
for day in DAYS:
    folder = OUT / day.isoformat()
    day_loans, day_accounts, day_capital = loans_for(day), accounts_for(day), capital_for(day)
    day_liq = [r for r in liquidity_series if r["date"] <= day.isoformat()]
    day_txns = [r for r in all_txns if r["date"] <= day.isoformat()]
    write(folder, "customers", customers, list(customers[0].keys()))
    write(folder, "accounts", day_accounts, list(accounts_base[0].keys()))
    write(folder, "loans", day_loans, list(loans_base[0].keys()))
    write(folder, "branches", branches, list(branches_base[0].keys()))
    write(folder, "capital_positions", day_capital, ["month", "tier1_capital", "tier2_capital", "risk_weighted_assets"])
    write(folder, "liquidity_daily", day_liq, ["date", "hqla", "net_outflows_30d", "stable_funding", "required_funding"])
    write(folder, "fx_rates", [r for r in fx_series if r["date"] <= day.isoformat()], ["date", "currency_pair", "rate"])
    write(folder, "transactions", day_txns, TXN_FIELDS)

    # KPI preview with Notebook 3's formulas (approximate FX; data-quality-flagged rows excluded).
    clean_loans = [l for l in day_loans if l["loan_id"] != DQ_LOAN]
    out_usd = sum(float(l["outstanding"]) / FX[l["currency"]] for l in clean_loans)
    npl_usd = sum(float(l["outstanding"]) / FX[l["currency"]] for l in clean_loans if int(l["days_past_due"]) >= 90)
    bal = [(float(a["balance"]) / FX[a["currency"]], a) for a in day_accounts]
    bal_usd = sum(v for v, _ in bal)
    non_lbp = sum(v for v, a in bal if a["currency"] != "LBP")
    ii = sum(float(l["outstanding"]) / FX[l["currency"]] * float(l["interest_rate"]) / 100 for l in clean_loans)
    dep = {"Current": 0.0, "Savings": 1.5, "Term deposit": 3.0}
    ie = sum(v * dep[a["type"]] / 100 for v, a in bal)
    region_ccy = {"Beirut": "USD", "North": "USD", "South": "USD", "KSA": "SAR", "Qatar": "QAR"}
    opex = sum(int(b["monthly_opex"]) / FX[region_ccy[b["region"]]] for b in branches if b["region"] in region_ccy)
    fees = sum(abs(float(r["amount"])) / FX[r["currency"]] for r in day_txns if r["type"] == "Fee" and r["account_id"] in acct_by_id and r["channel"] != "Telephone")
    rev = ii + fees
    cap = day_capital[-1]
    liq = day_liq[-1]
    preview.append((day, {
        "CAR": (cap["tier1_capital"] + cap["tier2_capital"]) / cap["risk_weighted_assets"] * 100,
        "LCR": liq["hqla"] / liq["net_outflows_30d"] * 100,
        "NPL": npl_usd / out_usd * 100,
        "NIM": (ii - ie) / out_usd * 100,
        "CTI": opex / rev * 100,
        "ROE": (rev - opex) / cap["tier1_capital"] * 100,
        "Assets $M": (out_usd + bal_usd) / 1e6,
        "Dollarization": non_lbp / bal_usd * 100,
        "txns": len(day_txns),
    }))

print(f"Wrote {', '.join(str(OUT / d.isoformat()) for d in DAYS)}")
for day, k in preview:
    print(day, "  ".join(f"{n} {v:,.1f}" if isinstance(v, float) else f"{n} {v}" for n, v in k.items()))
