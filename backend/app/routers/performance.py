from fastapi import APIRouter, Depends, Response

from ..db import latest_rows, query, query_one
from ..exports import performance_workbook
from ..security import current_user

router = APIRouter(prefix="/performance", tags=["screen 5 - branch & segment performance"],
                   dependencies=[Depends(current_user)])

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _branches() -> list:
    """The league table: worst profit first (the ones to worry about), with each branch's name joined in."""
    return query(
        """SELECT p.*, b.name AS branch_name
           FROM branch_performance_summary p LEFT JOIN branches b ON b.branch_id = p.branch_id
           WHERE p.calculation_date = (SELECT max(calculation_date) FROM branch_performance_summary)
           ORDER BY p.profit_usd ASC NULLS LAST, p.branch_id"""
    )


def _channels() -> dict:
    """How customers transact, current period only (no historical comparison exists). Transaction *counts*, because
    amounts are in mixed currencies."""
    rows = query(
        """SELECT coalesce(channel, 'Unknown') AS channel, count(*)::bigint AS transaction_count,
                  round(100.0 * count(*) / sum(count(*)) OVER (), 1)::float AS share_pct
           FROM transactions GROUP BY 1 ORDER BY 2 DESC, 1"""
    )
    span = query_one("SELECT min(date) AS first_date, max(date) AS last_date FROM transactions") or {}
    return {"first_date": span.get("first_date"), "last_date": span.get("last_date"), "channels": rows}


def _regions(branches: list) -> list:
    """Regional rollup: the branch figures grouped by region (done here, not as a separate pipeline table)."""
    out = {}
    for b in branches:
        r = out.setdefault(b["region"], {"region": b["region"], "branches": 0, "revenue_usd": 0.0, "cost_usd": 0.0,
                                         "profit_usd": 0.0})
        r["branches"] += 1
        for key in ("revenue_usd", "cost_usd", "profit_usd"):
            r[key] += b[key] or 0.0
    return sorted(out.values(), key=lambda r: r["profit_usd"])


@router.get("/branches")
def branches():
    return _branches()


@router.get("/segments")
def segments():
    return latest_rows("segment_performance_summary", "profit_usd DESC NULLS LAST")


@router.get("/products")
def products():
    return latest_rows("product_performance_summary", "net_contribution_usd DESC NULLS LAST")


@router.get("/channels")
def channels():
    return _channels()


@router.get("/export.xlsx")
def export():
    branch_rows = _branches()
    data = {
        "branches": branch_rows,
        "regions": _regions(branch_rows),
        "segments": latest_rows("segment_performance_summary", "profit_usd DESC NULLS LAST"),
        "products": latest_rows("product_performance_summary", "net_contribution_usd DESC NULLS LAST"),
        "channels": _channels()["channels"],
    }
    return Response(performance_workbook(data), media_type=XLSX,
                    headers={"Content-Disposition": 'attachment; filename="branch_segment_performance.xlsx"'})
