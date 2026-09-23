from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import query, query_one
from ..security import current_user

router = APIRouter(prefix="/kpi-summary", tags=["screen 1 - executive summary"], dependencies=[Depends(current_user)])


@router.get("/latest")
def latest():
    """Most recent KPI row; `assumptions_applied` lists the placeholder assumptions behind NIM/cost-to-income/ROE."""
    row = query_one("SELECT * FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT 1")
    if row is None:
        raise HTTPException(404, "No KPI data loaded yet - run the pipeline first")
    return row


@router.get("/history")
def history(days: int = Query(30, ge=1, le=730)):
    """Trend data. Returns however many days exist (a fresh demo has one)."""
    return query(
        """SELECT * FROM kpi_daily_summary
           WHERE calculation_date > (SELECT max(calculation_date) FROM kpi_daily_summary) - %s
           ORDER BY calculation_date""",
        (days,),
    )


# --- KPI detail / breakdown (Screen 1 tile click-through) -----------------------------------
#
# Every number here is read straight from Postgres and computed with the exact same formula
# notebooks/03_kpi_summary.py uses (specs/notebook-03-kpi-summary.md section 5-6) - no AI, no
# narrative generation, just the KPI's own arithmetic made visible. FX conversion reuses the rate
# notebooks/03_kpi_summary.py actually logged to fx_rate_usage_log for that calculation_date
# (rather than fetching a fresh live rate here) so the breakdown matches what really produced that
# day's kpi_daily_summary row, not today's rate.
#
# Caveat surfaced in the response itself: loans/accounts/branches/transactions are current-state
# tables in Postgres, not a per-day historized snapshot, so a component breakdown can only be shown
# for the latest calculation_date - there is no stored "what these looked like yesterday" to diff
# against. capital_positions/liquidity_daily ARE naturally historized (one row per month/date), so
# those two KPIs' components can genuinely be compared across the two most recent calculation dates.

DEPOSIT_RATE_BY_TYPE = {"Current": 0.0, "Savings": 1.5, "Term deposit": 3.0}
REGION_CURRENCY = {"Beirut": "USD", "North": "USD", "South": "USD", "KSA": "SAR", "Qatar": "QAR"}
NPL_DAYS_PAST_DUE_THRESHOLD = 90


def _fx_rates(calculation_date, used_in_calculation: str) -> dict:
    """The exact rates notebooks/03_kpi_summary.py fetched and logged for this calculation_date and
    this part of the calculation - not a fresh live fetch, so this matches what actually produced
    that day's numbers."""
    rows = query(
        """SELECT DISTINCT ON (currency_pair) currency_pair, rate FROM fx_rate_usage_log
           WHERE used_in_calculation = %s AND logged_at::date = %s
           ORDER BY currency_pair, logged_at DESC""",
        (used_in_calculation, calculation_date),
    )
    rates = {"USD": 1.0}
    for r in rows:
        _, ccy = r["currency_pair"].split("/")
        rates[ccy] = r["rate"]
    return rates


def _usd(amount, currency: str, rates: dict) -> float:
    return float(amount) / rates.get(currency, 1.0)


def _fmt_usd(v) -> str:
    return f"${v:,.0f}"


def _capital_components(calculation_date):
    """capital_positions is historized (one row per month) - unlike the other source tables, this
    genuinely lets us compare the row behind today's calculation against the row behind the
    previous one."""
    latest = query_one("SELECT * FROM capital_positions ORDER BY month DESC LIMIT 1")
    if latest is None:
        return None, None, "No capital_positions data loaded yet."
    car = (float(latest["tier1_capital"]) + float(latest["tier2_capital"])) / float(latest["risk_weighted_assets"]) * 100
    components = [
        {"label": "Tier 1 capital", "value": float(latest["tier1_capital"]), "formatted": _fmt_usd(latest["tier1_capital"])},
        {"label": "Tier 2 capital", "value": float(latest["tier2_capital"]), "formatted": _fmt_usd(latest["tier2_capital"])},
        {"label": "Risk-weighted assets", "value": float(latest["risk_weighted_assets"]), "formatted": _fmt_usd(latest["risk_weighted_assets"])},
    ]
    formula = f"CAR = (Tier 1 + Tier 2 capital) ÷ Risk-weighted assets × 100, latest capital position (month {latest['month']})"
    return car, components, formula


def _liquidity_components(calculation_date):
    latest = query_one("SELECT * FROM liquidity_daily ORDER BY date DESC LIMIT 1")
    if latest is None:
        return None, None, "No liquidity_daily data loaded yet."
    lcr = float(latest["hqla"]) / float(latest["net_outflows_30d"]) * 100
    components = [
        {"label": "High-quality liquid assets (HQLA)", "value": float(latest["hqla"]), "formatted": _fmt_usd(latest["hqla"])},
        {"label": "Net cash outflows (30-day)", "value": float(latest["net_outflows_30d"]), "formatted": _fmt_usd(latest["net_outflows_30d"])},
    ]
    formula = f"LCR = HQLA ÷ 30-day net outflows × 100, latest liquidity position ({latest['date']})"
    return lcr, components, formula


def _loans_usd(calculation_date):
    rates = _fx_rates(calculation_date, "loans_conversion")
    rows = query("SELECT outstanding, currency, days_past_due, interest_rate FROM loans")
    total = sum(_usd(r["outstanding"], r["currency"], rates) for r in rows)
    npl = sum(_usd(r["outstanding"], r["currency"], rates) for r in rows if r["days_past_due"] >= NPL_DAYS_PAST_DUE_THRESHOLD)
    interest_income = sum(_usd(r["outstanding"], r["currency"], rates) * float(r["interest_rate"]) / 100 for r in rows)
    return total, npl, interest_income, rates


def _accounts_usd(calculation_date):
    rates = _fx_rates(calculation_date, "accounts_conversion")
    rows = query("SELECT balance, currency, type FROM accounts")
    total = sum(_usd(r["balance"], r["currency"], rates) for r in rows)
    non_lbp = sum(_usd(r["balance"], r["currency"], rates) for r in rows if r["currency"] != "LBP")
    interest_expense = sum(_usd(r["balance"], r["currency"], rates) * DEPOSIT_RATE_BY_TYPE.get(r["type"], 0.0) / 100 for r in rows)
    return total, non_lbp, interest_expense, rates


def _branches_opex_usd(calculation_date):
    rates = _fx_rates(calculation_date, "branch_opex_conversion")
    rows = query("SELECT region, monthly_opex FROM branches")
    return sum(_usd(r["monthly_opex"], REGION_CURRENCY.get(r["region"], "USD"), rates) for r in rows), rates


def _fee_income_usd(calculation_date):
    rates = _fx_rates(calculation_date, "transactions_conversion")
    rows = query("SELECT amount, currency FROM transactions WHERE type = 'Fee'")
    return sum(_usd(r["amount"], r["currency"], rates) for r in rows), rates


KPI_BREAKDOWN = {}


def _kpi_breakdown(key):
    return KPI_BREAKDOWN[key]


def _register(key):
    def wrap(fn):
        KPI_BREAKDOWN[key] = fn
        return fn
    return wrap


@_register("car_pct")
def _car(calculation_date):
    value, components, formula = _capital_components(calculation_date)
    return value, components, formula, []


@_register("lcr_pct")
def _lcr(calculation_date):
    value, components, formula = _liquidity_components(calculation_date)
    return value, components, formula, []


@_register("npl_ratio_pct")
def _npl(calculation_date):
    total, npl, _, rates = _loans_usd(calculation_date)
    value = npl / total * 100 if total else None
    components = [
        {"label": "Loans 90+ days past due (USD)", "value": npl, "formatted": _fmt_usd(npl)},
        {"label": "Total loans outstanding (USD)", "value": total, "formatted": _fmt_usd(total)},
    ]
    formula = "NPL ratio = Loans 90+ days past due ÷ Total loans outstanding × 100, all converted to USD"
    return value, components, formula, [("Loan amounts (USD)", rates)]


@_register("total_assets_usd")
def _total_assets(calculation_date):
    loans_total, _, _, loan_rates = _loans_usd(calculation_date)
    accounts_total, _, _, account_rates = _accounts_usd(calculation_date)
    value = loans_total + accounts_total
    components = [
        {"label": "Total loans outstanding (USD)", "value": loans_total, "formatted": _fmt_usd(loans_total)},
        {"label": "Total account balances (USD)", "value": accounts_total, "formatted": _fmt_usd(accounts_total)},
    ]
    formula = "Total assets = Total loans outstanding + Total account balances, all converted to USD (a simplified proxy - no cash/investment/fixed-asset tables exist in the schema)"
    return value, components, formula, [("Loan amounts (USD)", loan_rates), ("Account balances (USD)", account_rates)]


@_register("dollarization_ratio_pct")
def _dollarization(calculation_date):
    total, non_lbp, _, rates = _accounts_usd(calculation_date)
    value = non_lbp / total * 100 if total else None
    components = [
        {"label": "Non-LBP account balances (USD)", "value": non_lbp, "formatted": _fmt_usd(non_lbp)},
        {"label": "Total account balances (USD)", "value": total, "formatted": _fmt_usd(total)},
    ]
    formula = "Dollarization ratio = Non-LBP account balances ÷ Total account balances × 100, all converted to USD"
    return value, components, formula, [("Account balances (USD)", rates)]


@_register("nim_pct")
def _nim(calculation_date):
    loans_total, _, interest_income, loan_rates = _loans_usd(calculation_date)
    _, _, interest_expense, account_rates = _accounts_usd(calculation_date)
    value = (interest_income - interest_expense) / loans_total * 100 if loans_total else None
    components = [
        {"label": "Interest income on loans (USD)", "value": interest_income, "formatted": _fmt_usd(interest_income)},
        {"label": "Interest paid on deposits (USD, assumption-based rate by account type)", "value": interest_expense, "formatted": _fmt_usd(interest_expense)},
        {"label": "Total loans outstanding (USD)", "value": loans_total, "formatted": _fmt_usd(loans_total)},
    ]
    formula = "NIM = (Interest income − Interest paid on deposits) ÷ Total loans outstanding × 100"
    return value, components, formula, [("Loan amounts (USD)", loan_rates), ("Account balances (USD)", account_rates)]


@_register("cost_to_income_pct")
def _cost_to_income(calculation_date):
    _, _, interest_income, loan_rates = _loans_usd(calculation_date)
    opex, opex_rates = _branches_opex_usd(calculation_date)
    fee_income, txn_rates = _fee_income_usd(calculation_date)
    revenue = interest_income + fee_income
    value = opex / revenue * 100 if revenue else None
    components = [
        {"label": "Branch operating expense (USD, assumption-based region currency)", "value": opex, "formatted": _fmt_usd(opex)},
        {"label": "Interest income (USD)", "value": interest_income, "formatted": _fmt_usd(interest_income)},
        {"label": "Fee income (USD)", "value": fee_income, "formatted": _fmt_usd(fee_income)},
    ]
    formula = "Cost-to-income = Branch operating expense ÷ (Interest income + Fee income) × 100"
    return value, components, formula, [("Loan amounts (USD)", loan_rates), ("Branch opex (USD)", opex_rates), ("Fee income (USD)", txn_rates)]


@_register("roe_pct")
def _roe(calculation_date):
    latest_capital = query_one("SELECT tier1_capital FROM capital_positions ORDER BY month DESC LIMIT 1")
    _, _, interest_income, loan_rates = _loans_usd(calculation_date)
    opex, opex_rates = _branches_opex_usd(calculation_date)
    fee_income, txn_rates = _fee_income_usd(calculation_date)
    revenue = interest_income + fee_income
    profit = revenue - opex
    tier1 = float(latest_capital["tier1_capital"]) if latest_capital else None
    value = profit / tier1 * 100 if tier1 else None
    components = [
        {"label": "Profit (revenue − opex, USD)", "value": profit, "formatted": _fmt_usd(profit)},
        {"label": "Tier 1 capital, used as an equity proxy (USD)", "value": tier1, "formatted": _fmt_usd(tier1) if tier1 else "—"},
    ]
    formula = "ROE = (Interest income + Fee income − Branch opex) ÷ Tier 1 capital × 100 (Tier 1 capital stands in for equity - the shakiest of the assumption-based KPIs)"
    return value, components, formula, [("Loan amounts (USD)", loan_rates), ("Branch opex (USD)", opex_rates), ("Fee income (USD)", txn_rates)]


def _capital_history():
    """Every capital_positions row, each with its own CAR computed - capital_positions is
    genuinely historized (one row per month), so unlike the other source tables this can show a
    real month-over-month trend, not just the latest snapshot."""
    rows = query("SELECT * FROM capital_positions ORDER BY month")
    return [
        {
            "label": str(r["month"]),
            "value": (float(r["tier1_capital"]) + float(r["tier2_capital"])) / float(r["risk_weighted_assets"]) * 100,
        }
        for r in rows
    ]


def _liquidity_history():
    rows = query("SELECT * FROM liquidity_daily ORDER BY date")
    return [{"label": str(r["date"]), "value": float(r["hqla"]) / float(r["net_outflows_30d"]) * 100} for r in rows]


HISTORY_SERIES = {"car_pct": _capital_history, "lcr_pct": _liquidity_history}


def _rate_note(label: str, rates: dict) -> str:
    non_usd = {k: v for k, v in rates.items() if k != "USD"}
    if not non_usd:
        return f"{label}: no non-USD currencies present."
    parts = ", ".join(f"1 USD = {v:g} {k}" for k, v in sorted(non_usd.items()))
    return f"{label}: {parts}"


@router.get("/{key}/breakdown")
def breakdown(key: str):
    """What a KPI tile's number is actually made of, computed live against the same source tables
    and formula notebooks/03_kpi_summary.py uses - a plain arithmetic drill-down, not an AI-written
    explanation. See this module's header comment for what can and can't be compared historically."""
    if key not in KPI_BREAKDOWN:
        raise HTTPException(404, f"Unknown KPI: {key}")
    latest_row = query_one("SELECT * FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT 1")
    if latest_row is None:
        raise HTTPException(404, "No KPI data loaded yet - run the pipeline first")
    # key is safe to interpolate as an identifier here - it was checked against KPI_BREAKDOWN's
    # fixed set of 8 column names above, so this can't become arbitrary SQL.
    history_rows = query(
        f"SELECT calculation_date, {key} AS value FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT 2"
    )
    previous_row = history_rows[1] if len(history_rows) > 1 else None

    computed_value, components, formula, rate_groups = _kpi_breakdown(key)(latest_row["calculation_date"])
    fx_notes = [_rate_note(label, rates) for label, rates in rate_groups]

    stored_value = latest_row[key]
    mismatch_note = None
    if computed_value is not None and stored_value is not None and abs(computed_value - float(stored_value)) > 0.01:
        mismatch_note = (
            f"Recomputing this just now gives {computed_value:.2f}, vs {float(stored_value):.2f} stored from the "
            f"last pipeline run - the source data has moved since that run."
        )

    return {
        "key": key,
        "calculation_date": latest_row["calculation_date"],
        "value": stored_value,
        "previous_value": previous_row["value"] if previous_row else None,
        "previous_calculation_date": previous_row["calculation_date"] if previous_row else None,
        "formula": formula,
        "components": components,
        "fx_notes": fx_notes,
        "mismatch_note": mismatch_note,
        "assumptions_applied": [a for a in (latest_row.get("assumptions_applied") or []) if key in a],
        "history_series": HISTORY_SERIES[key]() if key in HISTORY_SERIES else [],
    }
