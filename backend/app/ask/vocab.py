"""Words the Ask panel understands (specs/ask-a-question.md section 6).

Metric synonyms and country aliases are fixed lists here. Branch, region, segment and product names
come from the database (cached for a few minutes), so a new branch is understood without a code change.
"""
import time
from dataclasses import dataclass
from typing import Optional

from ..db import query


@dataclass(frozen=True)
class Metric:
    key: str
    label: str
    unit: str                               # usd | pct | count | number
    higher_is_better: Optional[bool]        # decides what "best" / "worst" mean (section 6.4)


# One global list; each catalogue entry says which of these it has and in which column.
METRICS = {m.key: m for m in [
    Metric("car", "Capital adequacy ratio (CAR)", "pct", True),
    Metric("lcr", "Liquidity coverage ratio (LCR)", "pct", True),
    Metric("npl_ratio", "NPL ratio", "pct", False),
    Metric("nim", "Net interest margin (NIM)", "pct", True),
    Metric("cost_to_income", "Cost-to-income", "pct", False),
    Metric("roe", "Return on equity (ROE)", "pct", True),
    Metric("total_assets", "Total assets", "usd", None),
    Metric("dollarization", "Dollarization ratio", "pct", False),
    Metric("deposits", "Deposits", "usd", True),
    Metric("loans", "Loans", "usd", None),
    Metric("bad_loans", "Bad loans", "usd", False),
    Metric("profit", "Profit", "usd", True),
    Metric("revenue", "Revenue", "usd", True),
    Metric("cost", "Cost", "usd", False),
    Metric("staff", "Staff", "count", None),
    Metric("profit_per_staff", "Profit per staff", "usd", True),
    Metric("customers", "Customers", "count", True),
    Metric("transactions", "Transactions", "count", None),
    Metric("transaction_volume", "Transaction volume", "usd", None),
    Metric("interest_income", "Interest income", "usd", True),
    Metric("avg_rate", "Average interest rate", "pct", None),
    Metric("net_contribution", "Net contribution", "usd", True),
    Metric("revenue_per_customer", "Revenue per customer", "usd", True),
]}

# Phrase -> metric key. Longest phrases are matched first, and a matched phrase is used up, so
# "cost to income" never also counts as "cost" or "income", and "net income" never as "income".
METRIC_SYNONYMS = {
    "car": ["capital adequacy ratio", "capital adequacy", "capital ratio", "car"],
    "lcr": ["liquidity coverage ratio", "liquidity coverage", "liquidity ratio", "lcr", "liquidity"],
    "npl_ratio": ["non performing loans", "non-performing loans", "nonperforming loans", "non performing",
                  "non-performing", "nonperforming", "npl ratio", "npls", "npl", "bad loans", "bad debt",
                  "bad loan ratio", "problem loans"],
    "nim": ["net interest margin", "interest margin", "nim"],
    "cost_to_income": ["cost to income ratio", "cost-to-income ratio", "cost to income", "cost-to-income",
                       "cost income", "efficiency ratio", "cti"],
    "roe": ["return on equity", "roe"],
    "total_assets": ["total assets", "balance sheet size", "assets"],
    "dollarization": ["dollarization", "dollarisation", "dollar share", "usd share"],
    "deposits": ["deposits", "deposit"],
    "loans": ["loan book", "loan portfolio", "lending", "loans", "loan", "outstanding"],
    "profit": ["net profit", "profitability", "profitable", "profits", "profit", "net income", "earnings"],
    "revenue": ["revenues", "revenue", "income", "sales"],
    "cost": ["operating costs", "expenses", "costs", "cost", "opex"],
    "staff": ["headcount", "employees", "staff"],
    "profit_per_staff": ["profit per employee", "profit per staff", "profit per head"],
    "customers": ["number of customers", "customer count", "customers", "clients"],
    "transactions": ["number of transactions", "transaction count", "transactions"],
    "transaction_volume": ["transaction volume", "volume"],
    "interest_income": ["interest income"],
    "avg_rate": ["average interest rate", "average rate", "interest rate", "avg rate"],
    "net_contribution": ["net contribution", "contribution"],
    "revenue_per_customer": ["revenue per customer", "income per customer"],
}

# Canonical country (as country_performance_summary spells it) -> words that mean it.
COUNTRIES = {
    "Lebanon": ["lebanon", "lebanese"],
    "Saudi Arabia": ["kingdom of saudi arabia", "saudi arabia", "saudi", "ksa"],
    "Qatar": ["qatar", "qatari"],
}

DIMENSIONS = {"product": "Product", "segment": "Segment", "branch": "Branch", "currency": "Currency"}

SOURCE_TABLES = {
    "customers": ["customers", "customer"], "accounts": ["accounts", "account"], "loans": ["loans", "loan"],
    "transactions": ["transactions", "transaction"], "branches": ["branches", "branch"],
    "capital_positions": ["capital positions", "capital"], "liquidity_daily": ["liquidity"],
    "fx_rates": ["fx rates", "exchange rates", "fx"],
}

# Product aliases beyond the name itself ("mortgages" works without an entry: plurals are tried).
PRODUCT_ALIASES = {"mortgage": ["home loans", "home loan", "housing loans"], "auto": ["car loans", "car loan", "vehicle loans"],
                   "personal": ["consumer loans", "personal loans"]}

_cache: dict = {}
_TTL_SECONDS = 600


def names() -> dict:
    """Branches, regions, segments and products as the database has them, cached for 10 minutes."""
    now = time.monotonic()
    if _cache.get("at") and now - _cache["at"] < _TTL_SECONDS:
        return _cache["data"]
    branches = query("SELECT branch_id, name, region, source_country FROM branches ORDER BY branch_id")
    data = {
        "branches": [{"id": b["branch_id"], "name": b["name"], "region": b["region"], "country": b["source_country"]}
                     for b in branches],
        "regions": sorted({b["region"] for b in branches if b["region"]}),
        "segments": [r["segment"] for r in query("SELECT DISTINCT segment FROM segment_performance_summary ORDER BY 1")],
        "products": [r["product"] for r in query("SELECT DISTINCT product FROM product_performance_summary ORDER BY 1")],
    }
    _cache.update(at=now, data=data)
    return data


def clear_cache() -> None:
    _cache.clear()


def country_aliases(country: str) -> list:
    """Every lower-case spelling of a canonical country, for matching columns that spell it differently
    (country_performance_summary says "Saudi Arabia", branches.region says "KSA")."""
    return [country.lower(), *COUNTRIES.get(country, [])]
