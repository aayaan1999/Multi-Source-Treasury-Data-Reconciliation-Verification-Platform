from fastapi import APIRouter, Depends, HTTPException

from ..db import query_one
from ..security import current_user

router = APIRouter(prefix="/scenario", tags=["screen 4 - scenario modelling"], dependencies=[Depends(current_user)])


@router.get("/snapshot")
def snapshot():
    """The single-row position the React app fetches once on load. Slider recomputes happen in the browser,
    so there is deliberately no recompute endpoint."""
    row = query_one("SELECT * FROM scenario_snapshot ORDER BY calculation_date DESC LIMIT 1")
    if row is None:
        raise HTTPException(404, "No scenario snapshot loaded yet - run the pipeline first")
    return row
