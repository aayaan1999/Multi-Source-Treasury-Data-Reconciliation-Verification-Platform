from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query

from ..db import latest_rows, query, query_one
from ..security import current_user

router = APIRouter(prefix="/portfolio", tags=["screen 2 - portfolio & credit risk"], dependencies=[Depends(current_user)])

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


@router.get("/loans")
def loans(
    product: Optional[str] = None,
    currency: Optional[str] = None,
    stage: Optional[int] = Query(None, ge=1, le=3),
    branch_id: Optional[str] = None,
    segment: Optional[str] = None,
    min_days_past_due: Optional[int] = Query(None, ge=0),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Drill-down list behind a clicked bar on Screen 2, read straight from `loans`."""
    where, params = [], []
    for column, value in (("l.product", product), ("l.currency", currency), ("l.stage", stage),
                          ("c.branch_id", branch_id), ("c.segment", segment)):
        if value is not None:
            where.append(f"{column} = %s")
            params.append(value)
    if min_days_past_due is not None:
        where.append("l.days_past_due >= %s")
        params.append(min_days_past_due)
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
