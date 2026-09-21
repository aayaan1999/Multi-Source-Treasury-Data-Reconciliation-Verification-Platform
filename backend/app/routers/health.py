from fastapi import APIRouter, HTTPException

from ..db import query_one

router = APIRouter(tags=["health"])


@router.get("/live")
def live():
    """Liveness only: the process is up. Deliberately no database call, so a hosting platform's health check
    doesn't restart a healthy API just because Neon is asleep. Use /health to see the database."""
    return {"status": "alive"}


@router.get("/health")
def health():
    try:
        query_one("SELECT 1 AS ok")
    except Exception:
        raise HTTPException(503, {"status": "degraded", "database": False})
    return {"status": "ok", "database": True}
