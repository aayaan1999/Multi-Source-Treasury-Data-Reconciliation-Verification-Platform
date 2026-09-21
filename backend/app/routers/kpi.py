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
