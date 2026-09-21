from fastapi import APIRouter, Depends

from ..db import latest_rows
from ..security import current_user

router = APIRouter(prefix="/performance", tags=["screen 5 - branch & segment performance"],
                   dependencies=[Depends(current_user)])


@router.get("/branches")
def branches():
    return latest_rows("branch_performance_summary", "profit_usd DESC NULLS LAST")


@router.get("/segments")
def segments():
    return latest_rows("segment_performance_summary", "profit_usd DESC NULLS LAST")


@router.get("/products")
def products():
    return latest_rows("product_performance_summary", "net_contribution_usd DESC NULLS LAST")
