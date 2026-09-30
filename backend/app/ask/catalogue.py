"""The approved questions (specs/ask-a-question.md section 5, CHT-1).

Every entry reads a precomputed summary table the screens already use, with fixed SQL. Filter
values are always bound parameters; column names and sort direction come from the tables below,
never from the request or the model.
"""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Callable, Optional

from ..db import query
from ..routers.portfolio import AGEING_ORDER, _in_bucket_order
from . import vocab
from .extract import Period

MAX_ROWS = 500
ALL_ROLES = frozenset({"approver", "risk", "analyst", "preparer", "compliance", "auditor", "admin"})   # specs/user-roles.md


class NoData(Exception):
    """The asked-for period has no snapshot; carries the range that does exist (section 6.5)."""

    def __init__(self, first: Optional[date], last: Optional[date]):
        super().__init__("no data")
        self.first, self.last = first, last


@dataclass
class Entry:
    id: str
    label: str                                  # what the answer card calls it
    description: str                            # what the model is told it answers
    source: str                                 # table shown as "Source:"
    run: Callable                               # run(filters) -> (columns, rows, as_of, notes)
    metrics: dict = field(default_factory=dict)             # metric key -> column
    metric_required: bool = False
    filters: frozenset = frozenset()            # which optional filters this entry takes
    roles: frozenset = ALL_ROLES
    examples: tuple = ()


def _plain(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def _rows(rows: list) -> list:
    return [{k: _plain(v) for k, v in r.items()} for r in rows[:MAX_ROWS]]


def col(key: str, label: str, unit: str = "text") -> dict:
    return {"key": key, "label": label, "unit": unit}


def metric_col(key: str, column: str) -> dict:
    m = vocab.METRICS[key]
    return col(column, m.label, m.unit)


def snapshot(table: str, period: Optional[Period]) -> date:
    """The calculation_date to read: the latest overall, or the latest inside the asked-for period."""
    if period is None:
        row = query(f"SELECT max(calculation_date) AS d FROM {table}")[0]
    else:
        row = query(f"SELECT max(calculation_date) AS d FROM {table} WHERE calculation_date BETWEEN %s AND %s",
                    (period.date_from, period.date_to))[0]
    if row["d"] is None:
        bounds = query(f"SELECT min(calculation_date) AS a, max(calculation_date) AS b FROM {table}")[0]
        raise NoData(bounds["a"], bounds["b"])
    return row["d"]


def _direction(f: dict) -> str:
    return "ASC" if f.get("order") == "asc" else "DESC"


def _limit(f: dict, default: int = MAX_ROWS, cap: int = MAX_ROWS) -> int:
    return min(f.get("top_n") or default, cap)


# ---- kpi_value -------------------------------------------------------------------------------------
KPI_COLUMNS = {"car": "car_pct", "lcr": "lcr_pct", "npl_ratio": "npl_ratio_pct", "nim": "nim_pct",
               "cost_to_income": "cost_to_income_pct", "roe": "roe_pct", "total_assets": "total_assets_usd",
               "dollarization": "dollarization_ratio_pct"}
PLACEHOLDER_KPIS = {"nim", "cost_to_income", "roe"}
PLACEHOLDER_NOTE = ("NIM, cost-to-income and ROE use documented placeholder assumptions "
                    "(specs/notebook-03-kpi-summary.md) until the bank confirms them.")


def run_kpi(f: dict):
    metric, period = f.get("metric"), f.get("period")
    shown = [metric] if metric else list(KPI_COLUMNS)
    notes = [PLACEHOLDER_NOTE] if PLACEHOLDER_KPIS & set(shown) else []
    if period is not None and period.is_range:
        rows = query(f"SELECT calculation_date, {', '.join(KPI_COLUMNS[k] for k in shown)} FROM kpi_daily_summary "
                     "WHERE calculation_date BETWEEN %s AND %s ORDER BY calculation_date", (period.date_from, period.date_to))
        if not rows:
            snapshot("kpi_daily_summary", period)          # raises NoData with the available range
        columns = [col("calculation_date", "Date", "date")] + [metric_col(k, KPI_COLUMNS[k]) for k in shown]
        return columns, _rows(rows), rows[-1]["calculation_date"].isoformat(), notes
    day = snapshot("kpi_daily_summary", period)
    row = query("SELECT * FROM kpi_daily_summary WHERE calculation_date = %s", (day,))[0]
    rows = [{"kpi": vocab.METRICS[k].label, "value": _plain(row[KPI_COLUMNS[k]]), "unit": vocab.METRICS[k].unit}
            for k in shown]
    return [col("kpi", "KPI"), col("value", "Value", "row")], rows, day.isoformat(), notes


# ---- country_breakdown -----------------------------------------------------------------------------
COUNTRY_COLUMNS = {"deposits": "deposits_usd", "loans": "loans_usd", "npl_ratio": "npl_ratio_pct",
                   "bad_loans": "npl_loans_usd", "customers": "customer_count", "transactions": "transaction_count",
                   "transaction_volume": "transaction_volume_usd"}


def _country_filter(countries: list) -> list:
    return [a for c in countries for a in vocab.country_aliases(c)]


def run_country(f: dict):
    day = snapshot("country_performance_summary", f.get("period"))
    metric = f.get("metric")
    shown = [metric] if metric else list(COUNTRY_COLUMNS)
    where, params = "calculation_date = %s", [day]
    if f.get("countries"):
        where += " AND lower(country) = ANY(%s)"
        params.append(_country_filter(f["countries"]))
    order = f"{COUNTRY_COLUMNS[metric]} {_direction(f)} NULLS LAST, country" if metric else "country"
    rows = query(f"SELECT country, {', '.join(COUNTRY_COLUMNS[k] for k in shown)} FROM country_performance_summary "
                 f"WHERE {where} ORDER BY {order} LIMIT %s", (*params, _limit(f)))
    columns = [col("country", "Country")] + [metric_col(k, COUNTRY_COLUMNS[k]) for k in shown]
    return columns, _rows(rows), day.isoformat(), []


# ---- branch_ranking --------------------------------------------------------------------------------
BRANCH_COLUMNS = {"deposits": "deposits_usd", "loans": "loans_usd", "revenue": "revenue_usd", "cost": "cost_usd",
                  "profit": "profit_usd", "cost_to_income": "cost_to_income_pct", "staff": "staff_count",
                  "profit_per_staff": "profit_per_staff_usd"}


def run_branches(f: dict):
    day = snapshot("branch_performance_summary", f.get("period"))
    column = BRANCH_COLUMNS[f["metric"]]
    where, params = ["p.calculation_date = %s"], [day]
    if f.get("countries"):
        aliases = _country_filter(f["countries"])
        where.append("(lower(coalesce(b.source_country, '')) = ANY(%s) OR lower(p.region) = ANY(%s))")
        params += [aliases, aliases]
    if f.get("regions"):
        where.append("p.region = ANY(%s)")
        params.append(f["regions"])
    if f.get("branches"):
        where.append("p.branch_id = ANY(%s)")
        params.append(f["branches"])
    rows = query(
        f"""SELECT p.branch_id, coalesce(b.name, p.branch_id) AS branch_name, p.region, p.{column}
            FROM branch_performance_summary p LEFT JOIN branches b ON b.branch_id = p.branch_id
            WHERE {' AND '.join(where)} ORDER BY p.{column} {_direction(f)} NULLS LAST, p.branch_id LIMIT %s""",
        (*params, _limit(f)),
    )
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank
    columns = [col("rank", "Rank", "number"), col("branch_name", "Branch"), col("region", "Region"),
               metric_col(f["metric"], column)]
    return columns, _rows(rows), day.isoformat(), []


# ---- segment_performance / product_performance -------------------------------------------------------
SEGMENT_COLUMNS = {"customers": "customer_count", "deposits": "deposits_usd", "loans": "loans_usd",
                   "revenue": "revenue_usd", "bad_loans": "bad_loans_usd", "profit": "profit_usd",
                   "revenue_per_customer": "revenue_per_customer_usd"}
PRODUCT_COLUMNS = {"loans": "outstanding_usd", "avg_rate": "avg_interest_rate", "interest_income": "interest_income_usd",
                   "npl_ratio": "npl_pct", "net_contribution": "net_contribution_usd"}
SEGMENT_NOTE = "Segment profit allocates branch cost in proportion to revenue (SEGMENT_COST_ALLOCATION assumption)."


def _grouped(table: str, key: str, label: str, columns_by_metric: dict, values_filter: str, notes: list):
    def run(f: dict):
        day = snapshot(table, f.get("period"))
        metric = f.get("metric")
        shown = [metric] if metric else list(columns_by_metric)
        where, params = "calculation_date = %s", [day]
        if f.get(values_filter):
            where += f" AND {key} = ANY(%s)"
            params.append(f[values_filter])
        order = f"{columns_by_metric[metric]} {_direction(f)} NULLS LAST, {key}" if metric else key
        rows = query(f"SELECT {key}, {', '.join(columns_by_metric[k] for k in shown)} FROM {table} "
                     f"WHERE {where} ORDER BY {order} LIMIT %s", (*params, _limit(f)))
        columns = [col(key, label)] + [metric_col(k, columns_by_metric[k]) for k in shown]
        return columns, _rows(rows), day.isoformat(), notes
    return run


# ---- loan_breakdown --------------------------------------------------------------------------------
def run_breakdown(f: dict):
    day = snapshot("loan_breakdown_by_dimension", f.get("period"))
    sort = "bad_loan_outstanding_usd" if f.get("metric") == "bad_loans" else "total_outstanding_usd"
    rows = query(
        f"""SELECT d.dimension_value, coalesce(b.name, d.dimension_value) AS label,
                   d.total_outstanding_usd, d.bad_loan_outstanding_usd,
                   CASE WHEN d.total_outstanding_usd > 0
                        THEN 100.0 * d.bad_loan_outstanding_usd / d.total_outstanding_usd END AS bad_share_pct
            FROM loan_breakdown_by_dimension d
            LEFT JOIN branches b ON d.dimension_type = 'branch' AND b.branch_id = d.dimension_value
            WHERE d.calculation_date = %s AND d.dimension_type = %s
            ORDER BY d.{sort} {_direction(f)} NULLS LAST, d.dimension_value LIMIT %s""",
        (day, f["dimension"], _limit(f)),
    )
    columns = [col("label", vocab.DIMENSIONS[f["dimension"]]), col("total_outstanding_usd", "Loans", "usd"),
               col("bad_loan_outstanding_usd", "Bad loans", "usd"), col("bad_share_pct", "Bad loans share", "pct")]
    return columns, _rows(rows), day.isoformat(), []


# ---- ifrs9_stages / top_exposures / loan_ageing ----------------------------------------------------------
def run_stages(f: dict):
    day = snapshot("loan_stage_summary", f.get("period"))
    where, params = "calculation_date = %s", [day]
    if f.get("stages"):
        where += " AND stage = ANY(%s)"
        params.append(f["stages"])
    rows = query(f"SELECT stage, loan_count, outstanding_usd, provisions_usd, coverage_pct FROM loan_stage_summary "
                 f"WHERE {where} ORDER BY stage", tuple(params))
    columns = [col("stage", "Stage", "number"), col("loan_count", "Loans", "count"), col("outstanding_usd", "Outstanding", "usd"),
               col("provisions_usd", "Provisions", "usd"), col("coverage_pct", "Coverage", "pct")]
    return columns, _rows(rows), day.isoformat(), []


def run_exposures(f: dict):
    day = snapshot("top_exposures", f.get("period"))
    where, params = "calculation_date = %s", [day]
    if f.get("products"):
        where += " AND product = ANY(%s)"
        params.append(f["products"])
    rows = query(f"SELECT customer_name, customer_id, product, outstanding_usd, days_past_due, pct_of_capital "
                 f"FROM top_exposures WHERE {where} ORDER BY outstanding_usd DESC NULLS LAST LIMIT %s",
                 (*params, _limit(f, default=20, cap=20)))
    columns = [col("customer_name", "Borrower"), col("customer_id", "Customer ID"), col("product", "Product"),
               col("outstanding_usd", "Outstanding", "usd"), col("days_past_due", "Days past due", "count"),
               col("pct_of_capital", "% of capital", "pct")]
    return columns, _rows(rows), day.isoformat(), []


def run_ageing(f: dict):
    day = snapshot("loan_ageing_summary", f.get("period"))
    rows = _in_bucket_order(query("SELECT bucket, outstanding_usd, pct_of_book FROM loan_ageing_summary "
                                  "WHERE calculation_date = %s", (day,)), AGEING_ORDER)
    columns = [col("bucket", "Days past due"), col("outstanding_usd", "Outstanding", "usd"), col("pct_of_book", "% of book", "pct")]
    return columns, _rows(rows), day.isoformat(), []


# ---- data_quality ----------------------------------------------------------------------------------
def run_quality(f: dict):
    if f.get("view") == "flag":
        day = snapshot("exception_summary_by_flag", f.get("period"))
        where, params = "calculation_date = %s", [day]
        if f.get("tables"):
            where += " AND source_table = ANY(%s)"
            params.append(f["tables"])
        rows = query(f"SELECT source_table, flag_label, exception_count FROM exception_summary_by_flag "
                     f"WHERE {where} ORDER BY exception_count DESC, source_table, flag_label LIMIT %s", (*params, MAX_ROWS))
        columns = [col("source_table", "Table"), col("flag_label", "Check"), col("exception_count", "Records flagged", "count")]
        return columns, _rows(rows), day.isoformat(), []
    day = snapshot("exception_summary_by_table", f.get("period"))
    where, params = "calculation_date = %s", [day]
    if f.get("tables"):
        where += " AND source_table = ANY(%s)"
        params.append(f["tables"])
    rows = query(f"SELECT source_table, raw_row_count, flagged_record_count, exception_rate_pct FROM exception_summary_by_table "
                 f"WHERE {where} ORDER BY exception_rate_pct DESC NULLS LAST, source_table LIMIT %s", (*params, MAX_ROWS))
    columns = [col("source_table", "Table"), col("raw_row_count", "Records received", "count"),
               col("flagged_record_count", "Records flagged", "count"), col("exception_rate_pct", "Exception rate", "pct")]
    return columns, _rows(rows), day.isoformat(), []


# ---- limit_breaches --------------------------------------------------------------------------------
LIMIT_METRICS = {"car": "capital_adequacy_ratio", "lcr": "liquidity_coverage_ratio", "npl_ratio": "npl_ratio",
                 "nim": "net_interest_margin", "cost_to_income": "cost_to_income_ratio", "roe": "return_on_equity",
                 "dollarization": "dollarization_ratio"}
LEVEL_LABEL = {"EARLY_WARNING": "Early warning", "APPETITE": "Internal limit", "REGULATORY": "Regulatory limit"}


def run_breaches(f: dict):
    where, params = [], []
    status = f.get("status") or "open"
    if status == "open":
        where.append("b.resolved_at IS NULL AND b.status = 'OPEN'")
    elif status == "closed":
        where.append("(b.resolved_at IS NOT NULL OR b.status <> 'OPEN')")
    if f.get("metric"):
        where.append("l.metric_name = %s")
        params.append(LIMIT_METRICS[f["metric"]])
    period = f.get("period")
    if period is not None:
        where.append("b.detected_at::date BETWEEN %s AND %s")
        params += [period.date_from, period.date_to]
    rows = query(
        f"""SELECT l.metric_name, b.level, b.status, b.actual_value, l.threshold_value, l.regulatory_value,
                   b.detected_at::date AS detected_on, b.due_date
            FROM breaches b JOIN limits l ON l.limit_id = b.limit_id
            {'WHERE ' + ' AND '.join(where) if where else ''}
            ORDER BY b.detected_at DESC LIMIT %s""",
        (*params, MAX_ROWS),
    )
    labels = {v: vocab.METRICS[k].label for k, v in LIMIT_METRICS.items()}
    for r in rows:
        r["metric_name"] = labels.get(r["metric_name"], r["metric_name"])
        r["level"] = LEVEL_LABEL.get(r["level"], r["level"])
    columns = [col("metric_name", "Limit"), col("level", "Level"), col("status", "Status"),
               col("actual_value", "Actual", "number"), col("threshold_value", "Internal limit", "number"),
               col("regulatory_value", "Regulatory limit", "number"), col("detected_on", "Detected", "date"),
               col("due_date", "Due", "date")]
    return columns, _rows(rows), date.today().isoformat(), []


ENTRIES = {e.id: e for e in [
    Entry("kpi_value", "Headline KPIs", "A bank-wide headline KPI (CAR, LCR, NPL ratio, NIM, cost-to-income, ROE, "
          "total assets, dollarization) on a date, or its trend over a period", "kpi_daily_summary", run_kpi,
          metrics=KPI_COLUMNS, filters=frozenset({"period"}),
          examples=("What is our capital adequacy ratio?", "NPL ratio over the last 7 days")),
    Entry("country_breakdown", "By country", "Deposits, loans, NPL ratio, bad loans, customers or transactions "
          "for each country (Lebanon, Saudi Arabia, Qatar), or one country", "country_performance_summary", run_country,
          metrics=COUNTRY_COLUMNS, filters=frozenset({"period", "countries", "order", "top_n"}),
          examples=("NPL ratio by country", "Deposits in Saudi Arabia")),
    Entry("branch_ranking", "Branches ranked", "Branches ranked by a measure (profit, revenue, cost, deposits, "
          "loans, cost-to-income, staff, profit per staff), e.g. top or worst branches", "branch_performance_summary",
          run_branches, metrics=BRANCH_COLUMNS, metric_required=True,
          filters=frozenset({"period", "countries", "regions", "branches", "order", "top_n"}),
          examples=("Top 5 branches by profit", "Worst 3 branches on cost to income")),
    Entry("segment_performance", "By customer segment", "Retail, SME and Corporate segment figures: customers, "
          "deposits, loans, revenue, bad loans, profit", "segment_performance_summary",
          _grouped("segment_performance_summary", "segment", "Segment", SEGMENT_COLUMNS, "segments", [SEGMENT_NOTE]),
          metrics=SEGMENT_COLUMNS, filters=frozenset({"period", "segments", "order", "top_n"}),
          examples=("Profit by segment",)),
    Entry("product_performance", "By loan product", "Loan products (mortgage, auto, personal, SME, corporate): "
          "outstanding, average rate, interest income, NPL ratio, net contribution", "product_performance_summary",
          _grouped("product_performance_summary", "product", "Product", PRODUCT_COLUMNS, "products", []),
          metrics=PRODUCT_COLUMNS, filters=frozenset({"period", "products", "order", "top_n"}),
          examples=("NPL ratio by loan product",)),
    Entry("loan_breakdown", "Loan book breakdown", "The loan book and bad loans split by branch, product, segment "
          "or currency", "loan_breakdown_by_dimension", run_breakdown,
          metrics={"loans": "total_outstanding_usd", "bad_loans": "bad_loan_outstanding_usd"},
          filters=frozenset({"period", "dimension", "order", "top_n"}),
          examples=("Loan book by currency",)),
    Entry("ifrs9_stages", "IFRS 9 stages", "IFRS 9 staging: loans, outstanding, provisions and coverage in stage 1, 2 and 3",
          "loan_stage_summary", run_stages, filters=frozenset({"period", "stages"}),
          examples=("IFRS 9 staging",)),
    Entry("top_exposures", "Largest exposures", "The largest borrowers / biggest exposures / concentration",
          "top_exposures", run_exposures, filters=frozenset({"period", "products", "top_n"}),
          examples=("Top 10 exposures",)),
    Entry("loan_ageing", "Loan ageing", "Loans by days past due (ageing buckets, arrears)", "loan_ageing_summary",
          run_ageing, filters=frozenset({"period"}), examples=("Loan ageing",)),
    Entry("data_quality", "Data quality", "Records rejected or flagged by the data-quality checks, per source table "
          "or per check", "exception_summary_by_table", run_quality, filters=frozenset({"period", "tables", "view"}),
          examples=("Data quality by table",)),
    Entry("limit_breaches", "Limit breaches", "Breaches of risk limits (CAR, LCR, NPL, ...): open, closed or all",
          "breaches", run_breaches, metrics={k: v for k, v in LIMIT_METRICS.items()},
          filters=frozenset({"period", "status"}), examples=("Open limit breaches",)),
]}

# "npl" where only a bad-loans amount exists, "profit" for a product's net contribution, etc.
METRIC_FALLBACKS = {
    "segment_performance": {"npl_ratio": "bad_loans"},
    "product_performance": {"bad_loans": "npl_ratio", "profit": "net_contribution", "revenue": "interest_income",
                            "outstanding": "loans"},
    "loan_breakdown": {"npl_ratio": "bad_loans"},
    "country_breakdown": {"volume": "transaction_volume"},
}

EXAMPLES = ["NPL ratio by country", "Top 5 branches by profit", "What is our capital adequacy ratio?",
            "IFRS 9 staging", "Top 10 exposures", "Open limit breaches"]
