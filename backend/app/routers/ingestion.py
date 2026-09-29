"""Data Ingestion screen (specs/screen-data-ingestion.md): what came in, from where, and whether it worked.

GET /ingestion/overview returns everything the screen shows in one call. Two kinds of content:

* Real - the latest pipeline run, from pipeline_reconciliation (Notebooks 1-2 via load_to_postgres):
  records received / kept / held back per source, country and data type, and sources that delivered
  nothing. Used for the stat cards and "Recent ingestions" whenever a run exists.
* Demo - the source connectors, their schedules and failed-connector examples. There is no connector
  registry yet (the demo pipeline only reads CSV files from the landing volume), so these come from
  DEMO below and every such block carries "demo": true, which the screen labels. Turning them into
  real data is backlog ING-1..6 (project-docs/CLIENT-FEEDBACK-BACKLOG.md, section 9).
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends

from ..db import query
from ..security import current_user

router = APIRouter(prefix="/ingestion", tags=["data ingestion"], dependencies=[Depends(current_user)])

# databricks.yml: the job starts when files land in the landing volume (file-arrival trigger), after the
# folder has been quiet for 2 minutes. There is no clock schedule.
PIPELINE_TRIGGER = "On file arrival"

SYSTEM_LABELS = {"CORE_CSV": "Core Banking"}
UPLOAD_FORMATS = ["CSV", "XLSX", "JSON", "XML", "PDF"]

# Placeholder content until the connector registry exists (ING-1). Shaped like the client demo deck.
DEMO = {
    "connectors": [
        {"code": "SFTP", "name": "SFTP", "detail": "Lebanon core banking files", "status": "connected"},
        {"code": "API", "name": "REST API", "detail": "Saudi Arabia ERP", "status": "connected"},
        {"code": "SQL", "name": "Database", "detail": "SQL Server / Oracle", "status": "connected"},
        {"code": "SP", "name": "SharePoint", "detail": "Branch finance workbooks", "status": "connected"},
        {"code": "BLOB", "name": "Azure Blob Storage", "detail": "Group treasury", "status": "connected"},
        {"code": "ERP", "name": "Core Banking / ERP", "detail": "Add another system", "status": "not_connected"},
    ],
    "schedules": [
        {"source": "Lebanon Core Banking", "runs": "Daily 02:00 + on file arrival", "next_hours": 18},
        {"source": "Saudi Arabia ERP", "runs": "Every 6 hours", "next_hours": 4},
        {"source": "Group Treasury", "runs": "Daily 06:00", "next_hours": 22},
    ],
    # Used for "Recent ingestions" and the stat cards only when no pipeline run is in the database yet.
    "recent": [
        {"source": "Lebanon Core Banking", "type": "SFTP", "data": "transactions.csv", "received": 755, "kept": 752, "status": "success", "minutes_ago": 30},
        {"source": "Lebanon Core Banking", "type": "SFTP", "data": "accounts.csv", "received": 229, "kept": 228, "status": "success", "minutes_ago": 30},
        {"source": "Saudi Arabia ERP", "type": "REST API", "data": "transactions", "received": 165, "kept": 165, "status": "success", "minutes_ago": 33},
        {"source": "Qatar Core Banking", "type": "Database", "data": "transactions", "received": 92, "kept": 92, "status": "processing", "minutes_ago": 24},
        {"source": "Group Treasury", "type": "Azure Blob", "data": "fx_rates.csv", "received": 42, "kept": 42, "status": "success", "minutes_ago": 49},
        {"source": "Qatar CRM", "type": "REST API", "data": "customers", "received": 0, "kept": 0, "status": "failed",
         "reason": "authentication expired", "minutes_ago": 52},
    ],
}


def _latest_run() -> list:
    return query(
        """SELECT source_system, source_country, source_table, received_rows, clean_rows, rejected_rows, note, detected_at
           FROM pipeline_reconciliation
           WHERE detected_at = (SELECT max(detected_at) FROM pipeline_reconciliation)
           ORDER BY source_country, source_table"""
    )


def _real_recent(rows: list) -> list:
    recent = []
    for r in rows:
        failed = bool(r["note"]) and r["received_rows"] == 0
        recent.append({
            "source": f"{r['source_country']} {SYSTEM_LABELS.get(r['source_system'], r['source_system'])}",
            "type": "File (CSV)",
            "data": f"{r['source_table']}.csv",
            "received": r["received_rows"],
            "kept": r["clean_rows"],
            "held": r["rejected_rows"],
            "status": "failed" if failed else "success",
            "reason": r["note"] if failed else None,
            "at": r["detected_at"].isoformat(),
        })
    return recent


def _demo_recent(now: datetime) -> list:
    return [{**{k: v for k, v in r.items() if k != "minutes_ago"}, "held": r["received"] - r["kept"],
             "reason": r.get("reason"), "at": (now - timedelta(minutes=r["minutes_ago"])).isoformat()}
            for r in DEMO["recent"]]


@router.get("/overview")
def overview():
    now = datetime.now(timezone.utc)
    rows = _latest_run()
    real = bool(rows)
    recent = _real_recent(rows) if real else _demo_recent(now)
    failed = [r for r in recent if r["status"] == "failed"]
    connectors = DEMO["connectors"]
    return {
        "trigger": PIPELINE_TRIGGER,
        "stats": {
            "demo": not real,
            "run_at": recent and max(r["at"] for r in recent),
            "files": len({r["data"] for r in recent}),
            "received": sum(r["received"] for r in recent),
            "kept": sum(r["kept"] for r in recent),
            "held": sum(r["held"] for r in recent),
            "failed": len(failed),
            "failed_example": f"{failed[0]['source']} · {failed[0]['data']}: {failed[0]['reason']}" if failed else None,
        },
        "sources": {"demo": True, "connected": sum(c["status"] == "connected" for c in connectors), "total": len(connectors),
                    "missing": [c["name"] for c in connectors if c["status"] != "connected"]},
        "connectors": {"demo": True, "items": connectors},
        "schedules": {"demo": True, "items": [{"source": s["source"], "runs": s["runs"],
                                                "next_at": (now + timedelta(hours=s["next_hours"])).isoformat()}
                                               for s in DEMO["schedules"]]},
        "recent": {"demo": not real, "items": recent},
        "upload_formats": UPLOAD_FORMATS,
    }
