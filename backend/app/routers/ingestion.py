"""Data Ingestion screen (specs/screen-data-ingestion.md): what came in, from where, and whether it worked.

GET /ingestion/overview returns everything the screen shows in one call:

* Real - the latest pipeline run, from pipeline_reconciliation (Notebooks 1-2 via load_to_postgres):
  records received / kept / held back per source, country and data type, and sources that delivered
  nothing. Used for the stat cards and "Recent ingestions" whenever a run exists.
* Sources - the connector catalogue (app/connectors.py) with each source's saved state from
  source_connectors. Connecting one saves its non-secret settings and hands its credentials to the
  Databricks secret scope (never to Postgres); POST /ingestion/run and each source's Sync start the
  pipeline job through the Jobs API (refresh.py). CFO/admin only.
* Upload - POST /ingestion/upload writes one of the eight core banking CSVs into the pipeline's landing
  folder (Databricks Files API), which starts the pipeline by its file-arrival trigger. CFO/admin only.
* Demo - the scheduled pulls and, before the first pipeline run, the stat cards and recent loads. They
  come from DEMO below and carry "demo": true, which the screen labels (backlog ING-2..6).
"""
import csv
import io
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from .. import connectors
from ..db import query, write
from ..security import current_user
from . import refresh

router = APIRouter(prefix="/ingestion", tags=["data ingestion"], dependencies=[Depends(current_user)])

# databricks.yml: the job starts when files land in the landing volume (file-arrival trigger), after the
# folder has been quiet for 2 minutes. There is no clock schedule.
PIPELINE_TRIGGER = "On file arrival"

SYSTEM_LABELS = {"CORE_CSV": "Core Banking"}
# Upload files (specs/screen-data-ingestion.md section 3b): the day's core banking files go straight to the pipeline's landing
# folder. Notebook 1 reads these eight CSVs by name, so only they are accepted; each must carry its columns.
UPLOAD_FORMATS = ["CSV"]
UPLOAD_FILES = {
    "customers": ["customer_id", "name", "segment", "branch_id", "onboard_date", "risk_rating", "country"],
    "accounts": ["account_id", "customer_id", "type", "currency", "balance", "open_date"],
    "loans": ["loan_id", "customer_id", "product", "principal", "outstanding", "currency", "interest_rate",
              "origination_date", "maturity_date", "days_past_due", "stage", "provision_amount", "collateral_value"],
    "transactions": ["transaction_id", "account_id", "date", "amount", "currency", "type", "channel"],
    "branches": ["branch_id", "name", "region", "staff_count", "monthly_opex"],
    "capital_positions": ["month", "tier1_capital", "tier2_capital", "risk_weighted_assets"],
    "liquidity_daily": ["date", "hqla", "net_outflows_30d", "stable_funding", "required_funding"],
    "fx_rates": ["date", "currency_pair", "rate"],
}
UPLOAD_MAX_BYTES = 100 * 1024 * 1024
# A day's file for these tables keeps (nearly) every record the bank already has. One that drops more
# than REPLACE_WARN_SHARE of them is another snapshot, or a partial file: loading it would turn every
# dropped record into a reconciliation task, so it needs the uploader to confirm.
RECORD_KEYS = {"customers": "customer_id", "accounts": "account_id", "loans": "loan_id", "branches": "branch_id"}
REPLACE_WARN_SHARE = 0.2
# databricks.yml's landing_path: where the file-arrival trigger watches and Notebook 1 reads.
DEFAULT_LANDING_PATH = "/Volumes/dbw_bankx_treasury_poc/raw/raw/resources"

# Placeholder content until schedules and connector runs are recorded (ING-2, ING-4).
DEMO = {
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


def _source_runs() -> list:
    """Loads recorded by the source notebooks themselves (ingestion_runs, e.g. Salesforce), newest first."""
    rows = query("""SELECT source_key, data_name, status, rows_received, message, ran_at
                    FROM ingestion_runs ORDER BY ran_at DESC LIMIT 20""")
    out = []
    for r in rows:
        spec = connectors.SOURCE_TYPES.get(r["source_key"], {"name": r["source_key"]})
        failed = r["status"] == "failed"
        out.append({"source": spec["name"], "type": "API", "data": r["data_name"], "received": r["rows_received"],
                    "kept": r["rows_received"], "held": 0, "status": r["status"],
                    "reason": r["message"] if failed else None, "at": r["ran_at"].isoformat()})
    return out


def _demo_recent(now: datetime) -> list:
    return [{**{k: v for k, v in r.items() if k != "minutes_ago"}, "held": r["received"] - r["kept"],
             "reason": r.get("reason"), "at": (now - timedelta(minutes=r["minutes_ago"])).isoformat()}
            for r in DEMO["recent"]]


@router.get("/overview")
def overview():
    now = datetime.now(timezone.utc)
    rows = _latest_run()
    source_runs = _source_runs()
    real = bool(rows)
    recent = _real_recent(rows) if real else _demo_recent(now)       # the stat cards: the latest pipeline run
    failed = [r for r in recent if r["status"] == "failed"]
    listed = sorted(source_runs + ([] if source_runs and not real else recent), key=lambda r: r["at"], reverse=True)
    sources = source_list()
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
        "sources": {"demo": False, "connected": sum(c["status"] == "connected" for c in sources), "total": len(sources),
                    "missing": [c["name"] for c in sources if c["status"] != "connected"]},
        "connectors": {"demo": False, "items": sources, "databricks": connectors.databricks_configured()},
        "schedules": {"demo": True, "items": [{"source": s["source"], "runs": s["runs"],
                                                "next_at": (now + timedelta(hours=s["next_hours"])).isoformat()}
                                               for s in DEMO["schedules"]]},
        "recent": {"demo": not real and not source_runs, "items": listed},
        "upload_formats": UPLOAD_FORMATS,
        "upload_files": [f"{name}.csv" for name in UPLOAD_FILES],
    }


# ---- source connectors (ING-1) ----------------------------------------------------------------------
class SourceForm(BaseModel):
    values: dict = {}


def _can_manage(user: dict) -> None:
    if user["role"] not in refresh.ALLOWED_ROLES:
        raise HTTPException(403, "Only the CFO or an admin can connect sources or start a run")


def _saved() -> dict:
    return {r["source_key"]: r for r in query(
        "SELECT source_key, config, secret_fields, credentials, connected_at, last_sync_at FROM source_connectors")}


def _card(key: str, row) -> dict:
    spec = connectors.SOURCE_TYPES[key]
    return {
        "key": key, "name": spec["name"], "code": spec["code"], "builtin": bool(spec.get("builtin")),
        "detail": connectors.label_config(key, row["config"]) if row else spec["detail"],
        "status": "connected" if spec.get("builtin") or row else "disconnected",
        "fields": connectors.public_fields(key),
        "config": (row or {}).get("config") or {},                 # non-secret settings only
        "secret_fields": (row or {}).get("secret_fields") or [],   # names only, never values
        "credentials": (row or {}).get("credentials"),
        "connected_at": row["connected_at"].isoformat() if row else None,
        "last_sync_at": row["last_sync_at"].isoformat() if row and row["last_sync_at"] else None,
    }


def source_list() -> list:
    saved = _saved()
    return [_card(key, saved.get(key)) for key in connectors.SOURCE_TYPES]


def _audit(user: dict, action: str, key: str, details: dict) -> None:
    write("""INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
             VALUES (%s, %s, 'source_connector', %s, NULL, %s)""",
          (user["user_id"], action, key, json.dumps(details)), returning=False)


def upload_table(filename: str):
    """Which of the eight files a name is: "transactions.csv", "Transactions_2026-09-30.csv" -> transactions;
    None for anything else."""
    stem, dot, ext = filename.strip().rpartition(".")
    if not dot or ext.lower() != "csv":
        return None
    stem = stem.lower()
    for table in sorted(UPLOAD_FILES, key=len, reverse=True):
        if stem == table or (stem.startswith(table) and stem[len(table)] in "_- ."):
            return table
    return None


def check_upload(filename: str, content: bytes) -> tuple:
    """(table, data rows) for a file the pipeline can read, else a 400 saying what's wrong."""
    names = ", ".join(f"{t}.csv" for t in UPLOAD_FILES)
    if not filename.lower().endswith(".csv"):
        raise HTTPException(400, f"Only CSV files go to the pipeline: {names}")
    table = upload_table(filename)
    if table is None:
        raise HTTPException(400, f"{filename} isn't one of the pipeline's files: {names}")
    if not content.strip():
        raise HTTPException(400, f"{filename} is empty")
    if len(content) > UPLOAD_MAX_BYTES:
        raise HTTPException(400, f"{filename} is larger than {UPLOAD_MAX_BYTES // (1024 * 1024)} MB")
    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise HTTPException(400, f"{filename} isn't UTF-8 text")
    lines = [line for line in text.splitlines() if line.strip()]
    header = [h.strip().strip('"').lower() for h in lines[0].split(",")]
    missing = [c for c in UPLOAD_FILES[table] if c not in header]
    if missing:
        raise HTTPException(400, f"{filename} is missing column(s) {', '.join(missing)} (first row must be the header)")
    return table, len(lines) - 1


def replaced_records(table: str, content: bytes):
    """For a table with record keys: how the file changes the records the platform has now
    ({"current", "dropped", "added"}), or None when there's nothing to compare with."""
    key = RECORD_KEYS.get(table)
    if not key:
        return None
    current = {r["id"] for r in query(f"SELECT {key} AS id FROM {table}")}
    if not current:
        return None
    rows = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    rows.fieldnames = [h.strip().strip('"').lower() for h in rows.fieldnames or []]
    uploaded = {(r.get(key) or "").strip() for r in rows} - {""}
    return {"current": len(current), "dropped": len(current - uploaded), "added": len(uploaded - current)}


def check_replacement(filename: str, table: str, content: bytes) -> None:
    """409 when the file would drop more than REPLACE_WARN_SHARE of the table's records (see RECORD_KEYS)."""
    change = replaced_records(table, content)
    if change and change["dropped"] > REPLACE_WARN_SHARE * change["current"]:
        noun = table.replace("_", " ")
        raise HTTPException(409, (
            f"{filename} would remove {change['dropped']:,} of the {change['current']:,} {noun} the platform has now "
            f"and add {change['added']:,} new ones. That looks like a different or partial snapshot, not the next "
            f"day's file, and every removed record would become a reconciliation task. Send it only if you mean to "
            f"replace the data."))


def _put_in_landing_folder(table: str, content: bytes) -> str:
    """Writes the file into the landing volume with the Databricks Files API, under the name Notebook 1 reads."""
    host, token = refresh._config()
    folder = (os.environ.get("DATABRICKS_LANDING_PATH") or DEFAULT_LANDING_PATH).rstrip("/")
    path = f"{folder}/{table}.csv"
    request = urllib.request.Request(
        f"{host}/api/2.0/fs/files{urllib.parse.quote(path)}?overwrite=true", data=content, method="PUT",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
    )
    try:
        with urllib.request.urlopen(request, timeout=120):
            pass
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get("message", "")
        except ValueError:
            message = ""
        raise HTTPException(502, f"Databricks refused the file ({e.code}){': ' + message if message else ''}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise HTTPException(502, f"Couldn't reach Databricks: {getattr(e, 'reason', e)}")
    return path


@router.post("/upload")
async def upload(request: Request, user: dict = Depends(current_user)):
    """Upload files: one file per request, its bytes as the body and its name in X-File-Name. Checked (one
    of the eight CSVs, with its columns, and - unless X-Replace-Confirmed: yes - not dropping many of the
    records the platform has now), then written to the pipeline's landing folder, which starts the
    pipeline about 2 minutes after the last file (databricks.yml's file-arrival trigger). Audited."""
    _can_manage(user)
    filename = urllib.parse.unquote(request.headers.get("x-file-name") or "").strip()
    if not filename:
        raise HTTPException(400, "The file's name is missing")
    content = await request.body()
    table, rows = check_upload(filename, content)
    confirmed = (request.headers.get("x-replace-confirmed") or "").lower() == "yes"
    if not confirmed:
        check_replacement(filename, table, content)
    if not connectors.databricks_configured():
        raise HTTPException(503, "The app isn't connected to the Databricks pipeline yet (DATABRICKS_HOST and DATABRICKS_TOKEN in backend/.env)")
    path = _put_in_landing_folder(table, content)
    _audit(user, "FILE_UPLOADED", f"{table}.csv",
           {"file": filename, "rows": rows, "bytes": len(content), "path": path, "replace_confirmed": confirmed})
    auto_start = _starts_on_arrival()
    then = ("The pipeline starts about 2 minutes after the last file." if auto_start
            else "The automatic start is paused: press Run All Sources once all files are in.")
    return {"file": filename, "stored_as": f"{table}.csv", "rows": rows, "bytes": len(content), "auto_start": auto_start,
            "message": f"Sent to the pipeline as {table}.csv ({rows:,} rows). {then}"}


def _starts_on_arrival() -> bool:
    """Whether the job's file-arrival trigger is on (databricks.yml's trigger_pause_status); a deploy can pause
    it. If the job can't be read, assume the default (on)."""
    try:
        job = refresh._api("GET", f"/api/2.1/jobs/get?job_id={refresh._job_id()}")
    except HTTPException:
        return True
    return (job.get("settings", {}).get("trigger") or {}).get("pause_status") != "PAUSED"


@router.post("/sources/{key}/test")
def test_source(key: str, form: SourceForm, user: dict = Depends(current_user)):
    _can_manage(user)
    return connectors.test_connection(key, form.values)


@router.post("/sources/{key}/connect")
def connect_source(key: str, form: SourceForm, user: dict = Depends(current_user)):
    """Connect & Save: validates, hands the credentials to Databricks (or nowhere), saves the rest."""
    _can_manage(user)
    config, secrets = connectors.validate(key, form.values)
    result = connectors.connect_to_databricks_pipeline(key, config, secrets)
    write("""INSERT INTO source_connectors (source_key, config, secret_fields, credentials, connected_by)
             VALUES (%s, %s, %s, %s, %s)
             ON CONFLICT (source_key) DO UPDATE SET config = EXCLUDED.config, secret_fields = EXCLUDED.secret_fields,
               credentials = EXCLUDED.credentials, connected_by = EXCLUDED.connected_by, connected_at = now()""",
          (key, json.dumps(config), sorted(secrets), result["credentials"], user["user_id"]), returning=False)
    _audit(user, "SOURCE_CONNECTED", key, {"config": config, "secret_fields": sorted(secrets), "credentials": result["credentials"]})
    return {"source": _card(key, _saved().get(key)), "message": result["detail"]}


@router.delete("/sources/{key}")
def disconnect_source(key: str, user: dict = Depends(current_user)):
    _can_manage(user)
    if connectors.source(key).get("builtin"):
        raise HTTPException(409, "The core banking files are part of the pipeline itself and can't be disconnected here")
    connectors.forget_in_databricks(key)
    write("DELETE FROM source_connectors WHERE source_key = %s", (key,), returning=False)
    _audit(user, "SOURCE_DISCONNECTED", key, {})
    return {"source": _card(key, None)}


def _start_run(user: dict) -> dict:
    """Starts the Databricks pipeline job (POST /api/2.1/jobs/run-now) through Refresh now."""
    if not connectors.databricks_configured():
        raise HTTPException(503, "The app isn't connected to the Databricks pipeline yet (DATABRICKS_HOST and DATABRICKS_TOKEN in backend/.env)")
    return refresh.refresh_now(user)


@router.post("/run")
def run_all(user: dict = Depends(current_user)):
    """Run All Sources: one pipeline run ingests every connected source."""
    _can_manage(user)
    run = _start_run(user)
    write("UPDATE source_connectors SET last_sync_at = now()", returning=False)
    return {"run_id": run["run_id"], "message": "Databricks ingestion pipeline started"}


@router.post("/sources/{key}/sync")
def sync_source(key: str, user: dict = Depends(current_user)):
    """Sync one source. The pipeline ingests every connected source in one run, so this starts that run."""
    _can_manage(user)
    connectors.source(key)
    card = _card(key, _saved().get(key))
    if card["status"] != "connected":
        raise HTTPException(409, f"Connect {card['name']} first")
    run = _start_run(user)
    write("UPDATE source_connectors SET last_sync_at = now() WHERE source_key = %s", (key,), returning=False)
    return {"run_id": run["run_id"], "message": f"Sync started for {card['name']}; the pipeline ingests all connected sources in one run"}
