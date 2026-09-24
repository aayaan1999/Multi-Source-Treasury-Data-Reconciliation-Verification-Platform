"""Refresh Now (specs/refresh-now.md, FLOW-6): starts the Databricks pipeline job on request instead
of waiting for its next trigger, and reports the latest run's progress so the dashboard can show it.

Talks to the Databricks Jobs API 2.1 with a token from backend/.env (DATABRICKS_HOST,
DATABRICKS_TOKEN; DATABRICKS_JOB_ID optional - otherwise the job is found by name). The token is
never logged or returned. Not configured -> a clear 503, the rest of the app unaffected.
"""
import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from ..db import write
from ..security import current_user

router = APIRouter(prefix="/refresh", tags=["refresh now"], dependencies=[Depends(current_user)])

JOB_NAME = "bank-data-pipeline"            # databricks.yml
ALLOWED_ROLES = {"approver", "admin"}     # the CFO (the demo approver) and admins
ACTIVE_STATES = {"QUEUED", "PENDING", "RUNNING", "TERMINATING", "BLOCKED", "WAITING_FOR_RETRY"}

_job_id_cache: dict = {}


def _config() -> tuple:
    host = (os.environ.get("DATABRICKS_HOST") or "").rstrip("/")
    token = os.environ.get("DATABRICKS_TOKEN") or ""
    if not host or not token:
        raise HTTPException(503, "Refresh Now isn't set up: add DATABRICKS_HOST and DATABRICKS_TOKEN to backend/.env")
    if not host.startswith("http"):
        host = f"https://{host}"
    return host, token


def _api(method: str, path: str, body: Optional[dict] = None) -> dict:
    """One Jobs API call. Errors become a 502 carrying Databricks' own message (never the token)."""
    host, token = _config()
    request = urllib.request.Request(
        f"{host}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            return json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            message = json.loads(e.read()).get("message", "")
        except ValueError:
            message = ""
        raise HTTPException(502, f"Databricks refused the request ({e.code}){': ' + message if message else ''}")
    except (urllib.error.URLError, TimeoutError) as e:
        raise HTTPException(502, f"Couldn't reach Databricks: {getattr(e, 'reason', e)}")


def _job_id() -> int:
    configured = os.environ.get("DATABRICKS_JOB_ID")
    if configured:
        return int(configured)
    if "id" not in _job_id_cache:
        jobs = _api("GET", f"/api/2.1/jobs/list?name={JOB_NAME}").get("jobs", [])
        if not jobs:
            raise HTTPException(503, f"No Databricks job named {JOB_NAME} - deploy it with `databricks bundle deploy`")
        _job_id_cache["id"] = jobs[0]["job_id"]
    return _job_id_cache["id"]


def _when(ms) -> Optional[str]:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat() if ms else None


def _run_summary(run: dict) -> dict:
    state = run.get("state", {})
    return {
        "run_id": run.get("run_id"),
        "state": state.get("life_cycle_state"),
        "result": state.get("result_state"),          # SUCCESS / FAILED / CANCELED once finished
        "message": state.get("state_message") or None,
        "started_at": _when(run.get("start_time")),
        "ended_at": _when(run.get("end_time")),
        "trigger": run.get("trigger"),                # ONE_TIME (Refresh Now), FILE_ARRIVAL, ...
        "url": run.get("run_page_url"),
    }


def _latest_run() -> Optional[dict]:
    runs = _api("GET", f"/api/2.1/jobs/runs/list?job_id={_job_id()}&limit=1").get("runs", [])
    return _run_summary(runs[0]) if runs else None


@router.get("/status")
def status():
    """The pipeline's latest run, and whether one is in progress. Anyone logged in can see it."""
    run = _latest_run()
    return {"running": bool(run and run["state"] in ACTIVE_STATES), "last_run": run}


@router.post("")
def refresh_now(user: dict = Depends(current_user)):
    """Starts the pipeline now (CFO/admin only). Refused while a run is already going: the job runs
    one at a time anyway (databricks.yml max_concurrent_runs), and a second click shouldn't queue a
    duplicate refresh."""
    if user["role"] not in ALLOWED_ROLES:
        raise HTTPException(403, "Only the CFO or an admin can refresh the data")
    run = _latest_run()
    if run and run["state"] in ACTIVE_STATES:
        raise HTTPException(409, f"A refresh is already running (started {run['started_at'] or 'just now'})")
    run_id = _api("POST", "/api/2.1/jobs/run-now", {"job_id": _job_id()})["run_id"]
    write(
        """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           VALUES (%s, 'REFRESH_REQUESTED', 'pipeline_job', %s, NULL, %s) RETURNING log_id""",
        (user["user_id"], str(run_id), JOB_NAME),
    )
    return {"run_id": run_id}
