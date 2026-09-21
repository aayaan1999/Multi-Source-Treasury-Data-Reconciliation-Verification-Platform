from fastapi import APIRouter, HTTPException

from ..db import query_one

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    try:
        query_one("SELECT 1 AS ok")
    except Exception:
        raise HTTPException(503, {"status": "degraded", "database": False})
    return {"status": "ok", "database": True}
