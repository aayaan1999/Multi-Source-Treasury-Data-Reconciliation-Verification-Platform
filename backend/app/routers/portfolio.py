from concurrent.futures import ThreadPoolExecutor
from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response

from ..db import latest_rows, query, query_one
from ..exports import portfolio_workbook
from ..security import current_user
from .performance import _branches

router = APIRouter(prefix="/portfolio", tags=["screen 2 - portfolio & credit risk"], dependencies=[Depends(current_user)])

# Same bucket rules as notebooks/06 (outstanding / collateral_value x 100; zero or missing collateral counts as >100%).
LTV_SQL = {
    "<50%": "(l.collateral_value > 0 AND l.outstanding * 100.0 / l.collateral_value < 50)",
    "50-80%": "(l.collateral_value > 0 AND l.outstanding * 100.0 / l.collateral_value >= 50 "
              "AND l.outstanding * 100.0 / l.collateral_value < 80)",
    "80-100%": "(l.collateral_value > 0 AND l.outstanding * 100.0 / l.collateral_value >= 80 "
               "AND l.outstanding * 100.0 / l.collateral_value <= 100)",
    ">100%": "(l.collateral_value IS NULL OR l.collateral_value = 0 OR l.outstanding * 100.0 / l.collateral_value > 100)",
}

AGEING_ORDER = ["Current", "1-30", "31-60", "61-90", "90-180", "180+"]
LTV_ORDER = ["<50%", "50-80%", "80-100%", ">100%"]


def _in_bucket_order(rows: list, order: list) -> list:
    """Buckets have a business order, not an alphabetical one; unknown labels go last."""
    return sorted(rows, key=lambda r: order.index(r["bucket"]) if r["bucket"] in order else len(order))


@router.get("/breakdown")
def breakdown(dimension: Literal["product", "segment", "branch", "currency"]):
    return latest_rows("loan_breakdown_by_dimension", "total_outstanding_usd DESC NULLS LAST",
                       "dimension_type = %s", (dimension,))


@router.get("/stage-summary")
def stage_summary():
    return latest_rows("loan_stage_summary", "stage")


@router.get("/top-exposures")
def top_exposures():
    return latest_rows("top_exposures", "outstanding_usd DESC NULLS LAST")


@router.get("/ageing")
def ageing():
    return _in_bucket_order(latest_rows("loan_ageing_summary", "bucket"), AGEING_ORDER)


@router.get("/ltv-distribution")
def ltv_distribution():
    return _in_bucket_order(latest_rows("ltv_distribution", "bucket"), LTV_ORDER)


@router.get("/overview")
def overview():
    """Everything Screen 2 needs on first paint, in one round trip instead of nine: the loan-book summary, all
    four breakdown dimensions, and the branch names used to label the branch breakdown. One HTTP round trip avoids
    the browser's per-origin connection queueing, but the 9 underlying queries still run concurrently (not one
    after another) - Neon's per-connection setup cost is real, and paying it 9 times in series would undo the win.
    """
    jobs = {
        "stages": lambda: latest_rows("loan_stage_summary", "stage"),
        "top_exposures": lambda: latest_rows("top_exposures", "outstanding_usd DESC NULLS LAST"),
        "ageing": lambda: _in_bucket_order(latest_rows("loan_ageing_summary", "bucket"), AGEING_ORDER),
        "ltv": lambda: _in_bucket_order(latest_rows("ltv_distribution", "bucket"), LTV_ORDER),
        "branches": _branches,
        **{
            f"breakdown_{d}": (lambda d=d: latest_rows(
                "loan_breakdown_by_dimension", "total_outstanding_usd DESC NULLS LAST", "dimension_type = %s", (d,)))
            for d in ("product", "segment", "branch", "currency")
        },
    }
    # Capped rather than one worker per job: Neon's compute has a real ceiling on concurrent query execution,
    # and firing all 9 at once let them queue server-side and land *slower* than a smaller, steady batch does.
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = {key: future.result() for key, future in
                  {key: pool.submit(job) for key, job in jobs.items()}.items()}

    return {
        "stages": results["stages"],
        "top_exposures": results["top_exposures"],
        "ageing": results["ageing"],
        "ltv": results["ltv"],
        "branches": results["branches"],
        "breakdown": {d: results[f"breakdown_{d}"] for d in ("product", "segment", "branch", "currency")},
    }


@router.get("/loans")
def loans(
    product: Optional[str] = None,
    currency: Optional[str] = None,
    stage: Optional[int] = Query(None, ge=1, le=3),
    branch_id: Optional[str] = None,
    segment: Optional[str] = None,
    customer_id: Optional[str] = None,
    min_days_past_due: Optional[int] = Query(None, ge=0),
    max_days_past_due: Optional[int] = Query(None, ge=0),
    ltv_bucket: Optional[Literal["<50%", "50-80%", "80-100%", ">100%"]] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Drill-down list behind a clicked bar or row on Screens 2 and 5, read straight from `loans`."""
    where, params = [], []
    for column, value in (("l.product", product), ("l.currency", currency), ("l.stage", stage),
                          ("c.branch_id", branch_id), ("c.segment", segment), ("l.customer_id", customer_id)):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    if min_days_past_due is not None:
        where.append("l.days_past_due >= %s")
        params.append(min_days_past_due)
    if max_days_past_due is not None:
        where.append("l.days_past_due <= %s")
        params.append(max_days_past_due)
    if ltv_bucket is not None:
        where.append(LTV_SQL[ltv_bucket])   # fixed strings from the table above, never user text
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    source = f"FROM loans l JOIN customers c ON c.customer_id = l.customer_id {clause}"

    total = query_one(f"SELECT count(*) AS n {source}", tuple(params))["n"]
    items = query(
        f"""SELECT l.loan_id, l.customer_id, c.name AS customer_name, c.segment, c.branch_id, l.product,
                   l.currency, l.principal, l.outstanding, l.interest_rate, l.days_past_due, l.stage,
                   l.provision_amount, l.collateral_value, l.maturity_date
            {source} ORDER BY l.outstanding DESC NULLS LAST, l.loan_id LIMIT %s OFFSET %s""",
        tuple(params) + (limit, offset),
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/customers")
def customers(
    branch_id: Optional[str] = None,
    segment: Optional[str] = None,
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Who is behind a branch or a segment (drill-down from Screen 5), with how many loans they hold."""
    where, params = [], []
    for column, value in (("c.branch_id", branch_id), ("c.segment", segment)):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    total = query_one(f"SELECT count(*) AS n FROM customers c {clause}", tuple(params))["n"]
    items = query(
        f"""SELECT c.customer_id, c.name, c.segment, c.branch_id, c.risk_rating, c.country, c.onboard_date,
                   count(l.loan_id)::int AS loan_count,
                   count(l.loan_id) FILTER (WHERE l.days_past_due >= 90)::int AS bad_loan_count
            FROM customers c LEFT JOIN loans l ON l.customer_id = c.customer_id
            {clause} GROUP BY c.customer_id ORDER BY c.name, c.customer_id LIMIT %s OFFSET %s""",
        tuple(params) + (limit, offset),
    )
    return {"total": total, "limit": limit, "offset": offset, "items": items}


@router.get("/export.xlsx")
def export():
    """Everything Screen 2 shows, as one Excel workbook."""
    data = {
        "stages": latest_rows("loan_stage_summary", "stage"),
        "breakdown": {
            d: latest_rows("loan_breakdown_by_dimension", "total_outstanding_usd DESC NULLS LAST",
                           "dimension_type = %s", (d,))
            for d in ("product", "segment", "branch", "currency")
        },
        "top_exposures": latest_rows("top_exposures", "outstanding_usd DESC NULLS LAST"),
        "ageing": _in_bucket_order(latest_rows("loan_ageing_summary", "bucket"), AGEING_ORDER),
        "ltv": _in_bucket_order(latest_rows("ltv_distribution", "bucket"), LTV_ORDER),
    }
    return Response(portfolio_workbook(data),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="portfolio_credit_risk.xlsx"'})
