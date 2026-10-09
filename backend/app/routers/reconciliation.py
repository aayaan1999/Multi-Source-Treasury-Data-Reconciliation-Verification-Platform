"""Reconciliation tab and reconciliation tasks (specs/reconciliation-approvals.md).

Two checks: pipeline gaps (specs/pipeline-reconciliation.md: rows a delivery sent that we couldn't
load) and core-system breaks (specs/multi-source-reconciliation.md, specs/reconciliation-groups.md: our
data differs from core banking or the CRM, grouped by cause). Both become tasks on the same Camunda
process (reconciliation-task): the team decides, the CFO approves important ones, and the CFO signs
off each run once every task is decided (reconciliation-run-signoff). Camunda runs the steps and the
bridge workers write the decisions; these endpoints read what the Tasks screen and the Reconciliation
tab show, and take the corrected values the team enters on a pipeline gap.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..db import query, query_one, write
from ..recon_text import FLAG_FIELD, SOURCE_LABEL, group_summary, pipeline_summary, run_day, run_name
from ..security import current_user

router = APIRouter(prefix="/reconciliation", tags=["reconciliation"], dependencies=[Depends(current_user)])

RESOLVED_STATUSES = ("ACCEPTED", "CORRECTED", "DISMISSED")


@router.get("/summary")
def summary():
    by_status = query("SELECT status, count(*) AS count FROM reconciliation_exceptions GROUP BY status")
    by_mismatch = query(
        "SELECT mismatch_type, count(*) AS count FROM reconciliation_exceptions "
        "WHERE status = 'OPEN' GROUP BY mismatch_type"
    )
    by_entity = query(
        "SELECT entity_type, count(*) AS count FROM reconciliation_exceptions "
        "WHERE status = 'OPEN' GROUP BY entity_type"
    )
    return {"by_status": by_status, "by_mismatch_type": by_mismatch, "by_entity_type": by_entity}

# ---- Core-system reconciliation: groups, run sign-off (specs/reconciliation-groups.md) ------------

@router.get("/groups")
def groups(status: Optional[str] = None, source_system: Optional[str] = None, limit: int = Query(500, le=5000)):
    """Groups of breaks with the same cause (one task each), important ones first. source_system picks one
    source (neon = core banking, salesforce = CRM); without it, every source."""
    clauses = [(c, v) for c, v in (("status", status), ("source_system", source_system)) if v]
    where = f"WHERE {' AND '.join(f'{c} = %s' for c, _ in clauses)}" if clauses else ""
    params = tuple(v for _, v in clauses)
    return query(
        f"""SELECT group_id, source_system, entity_type, field_name, mismatch_type, pattern, important, break_count,
                   total_difference, largest_difference, cfo_required, cfo_reason, title, team, status, decision,
                   due_date, created_at, closed_at, run_id
            FROM reconciliation_groups {where}
            ORDER BY (status = 'CLOSED'), important DESC, break_count DESC, group_id LIMIT %s""",
        (*params, limit),
    )


@router.get("/groups/{group_id}")
def group_detail(group_id: int):
    """A group and every break in it, for the review popup (carve-outs are picked from this list).
    Breaks decided in this group keep pointing at it; carved-out ones have left it."""
    g = query_one(
        """SELECT g.*, ud.name AS decided_by_name, ua.name AS approved_by_name, us.name AS sent_back_by_name
           FROM reconciliation_groups g LEFT JOIN users ud ON ud.user_id = g.decided_by
           LEFT JOIN users ua ON ua.user_id = g.approved_by LEFT JOIN users us ON us.user_id = g.sent_back_by
           WHERE g.group_id = %s""",
        (group_id,),
    )
    if g is None:
        raise HTTPException(404, "No such group")
    g["breaks"] = query(
        """SELECT exception_id, entity_type, entity_id, field_name, source_value, canonical_value, mismatch_type,
                  status, first_seen, last_seen, times_seen, recurring
           FROM reconciliation_exceptions WHERE group_id = %s ORDER BY entity_id LIMIT 5000""",
        (group_id,),
    )
    g["summary"] = group_summary(g, [b for b in g["breaks"] if b["status"] == "OPEN"] or g["breaks"])
    g["corrections"] = _corrections("group_id", group_id)
    g["run"] = _run_brief(g["run_id"])
    return g


def _latest_run(source_system: str):
    row = query_one("SELECT max(last_seen)::date AS run_date FROM reconciliation_exceptions WHERE source_system = %s", (source_system,))
    return row["run_date"] if row else None


@router.get("/run")
def run_summary(source_system: str = "neon"):
    """The latest run of a source: what it found, what cleared itself, what's still open, and its
    sign-off. A run's date is the day its breaks were last seen."""
    run_date = _latest_run(source_system)
    if run_date is None:
        return {"run_date": None, "source_system": source_system}
    counts = query_one(
        """SELECT count(*) FILTER (WHERE last_seen::date = %s) AS breaks_seen,
                  count(*) FILTER (WHERE last_seen::date = %s AND status = 'AUTO_ACCEPTED') AS auto_cleared,
                  count(*) FILTER (WHERE status = 'OPEN') AS open_breaks,
                  count(*) FILTER (WHERE status = 'OPEN' AND recurring) AS recurring_open
           FROM reconciliation_exceptions WHERE source_system = %s""",
        (run_date, run_date, source_system),
    )
    group_counts = query_one(
        """SELECT count(*) FILTER (WHERE status <> 'CLOSED') AS groups_open,
                  count(*) FILTER (WHERE status <> 'CLOSED' AND important) AS important_open
           FROM reconciliation_groups WHERE source_system = %s""",
        (source_system,),
    )
    return {"run_date": run_date, "source_system": source_system, **counts, **group_counts}


@router.get("")
def list_exceptions(
    status: Optional[str] = None,
    entity_type: Optional[str] = None,
    mismatch_type: Optional[str] = None,
    source_system: Optional[str] = None,          # neon (core banking) or salesforce (CRM); all when omitted
    # Up to 5000: the Reconciliation page fetches the whole table once (unfiltered) and filters its
    # tabs/status in the browser, so this must return every row. The table is hundreds-to-thousands
    # of rows, not millions; move filtering back server-side if it ever outgrows this cap.
    limit: int = Query(200, le=5000),
):
    clauses, params = [], []
    for col, val in (("status", status), ("entity_type", entity_type), ("mismatch_type", mismatch_type),
                     ("source_system", source_system)):
        if val:
            clauses.append(f"r.{col} = %s")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return query(
        f"""SELECT r.exception_id, r.source_system, r.entity_type, r.entity_id, r.field_name,
                   r.source_value, r.canonical_value, r.mismatch_type, r.status, r.detected_at,
                   r.resolved_by, u.name AS resolved_by_name, r.resolved_at, r.resolution_note,
                   r.resolved_rule, r.group_id, r.first_seen, r.last_seen, r.times_seen, r.recurring
            FROM reconciliation_exceptions r LEFT JOIN users u ON u.user_id = r.resolved_by
            {where} ORDER BY r.detected_at DESC LIMIT %s""",
        tuple(params),
    )


PIPELINE_COLUMNS = """p.recon_id, p.ingest_batch_id, p.source_system, p.source_country, p.source_table,
       p.received_rows, p.clean_rows, p.rejected_rows, p.amount_column, p.unreadable_amount_rows,
       p.amounts_by_currency, p.has_gap, p.status, p.detected_at, p.note, p.title, p.run_id,
       p.decision, p.decided_by, ud.name AS decided_by_name, p.decided_at, p.cfo_required, p.cfo_reason,
       p.approved_by, ua.name AS approved_by_name, p.approved_at,
       p.sent_back_at, p.sent_back_from, p.sent_back_note, us.name AS sent_back_by_name,
       p.carried_count, p.carried_since, p.escalated_at"""
PIPELINE_FROM = """pipeline_reconciliation p LEFT JOIN users ud ON ud.user_id = p.decided_by
       LEFT JOIN users ua ON ua.user_id = p.approved_by LEFT JOIN users us ON us.user_id = p.sent_back_by"""

# The newest run of each source: a run is one delivery, and older runs' items stay as history.
LATEST_RUN_PER_SOURCE = """(p.source_system, p.ingest_batch_id) IN (
    SELECT DISTINCT ON (source_system) source_system, ingest_batch_id
    FROM pipeline_reconciliation ORDER BY source_system, detected_at DESC)"""


@router.get("/pipeline")
def pipeline_items(
    latest_only: bool = Query(True, description="Only each source's newest run"),
    source_system: Optional[str] = None,
    source_country: Optional[str] = None,
    source_table: Optional[str] = None,
    gaps_only: bool = False,
    limit: int = Query(1000, le=5000),
):
    """Received-vs-kept items, gaps first. Read-only: acting on an item is FLOW-5's workflow."""
    clauses, params = [], []
    if latest_only:
        clauses.append(LATEST_RUN_PER_SOURCE)
    for col, val in (("source_system", source_system), ("source_country", source_country), ("source_table", source_table)):
        if val:
            clauses.append(f"p.{col} = %s")
            params.append(val)
    if gaps_only:
        clauses.append("p.has_gap")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return query(
        f"""SELECT {PIPELINE_COLUMNS} FROM {PIPELINE_FROM} {where}
            ORDER BY p.has_gap DESC, p.rejected_rows DESC, p.source_table, p.source_country LIMIT %s""",
        tuple(params),
    )


@router.get("/pipeline/{recon_id}/records")
def pipeline_item_records(recon_id: int):
    """The rejected records behind one item, from data_quality_exceptions (same table, source,
    country and run). The exceptions log only holds the latest run's rejects, so an older run's
    item says the detail is gone rather than showing a different run's records."""
    item = _item(recon_id)
    records = query(
        """SELECT record_key, flag_label, description, record_data FROM data_quality_exceptions
           WHERE source_table = %s AND source_system = %s AND source_country = %s AND ingest_batch_id = %s
           ORDER BY record_key, flag_label""",
        (item["source_table"], item["source_system"], item["source_country"], item["ingest_batch_id"]),
    )
    for r in records:
        r["bad_field"] = FLAG_FIELD.get(r["flag_label"])
    # Every rejected row of the run the log holds has at least one exception, so rejected rows with
    # no records means the item is from an older run whose detail has been replaced.
    return {"item": item, "records": records, "records_available": bool(records) or item["rejected_rows"] == 0,
            "summary": pipeline_summary(item, records), "run": _run_brief(item["run_id"])}


def _item(recon_id: int) -> dict:
    item = query_one(f"SELECT {PIPELINE_COLUMNS} FROM {PIPELINE_FROM} WHERE p.recon_id = %s", (recon_id,))
    if item is None:
        raise HTTPException(404, "No such reconciliation item")
    return item


# ---- Corrected values for a pipeline gap (specs/cfo-reconciliation-workflow.md, reconciliation-approvals.md) --

# Values are entered while the team reviews the item; the CFO approves them with the decision.
EDITABLE_STATUSES = ("WITH_TEAM",)
# The values Notebook 2's checks accept (notebooks/02_data_quality_verification.py VALID_*): a fixed value
# outside these would be rejected again on the next run, so it's refused here. Keep the two in step.
ALLOWED_VALUES = {
    "currency": ("USD", "EUR", "LBP", "SAR", "QAR"),
    "channel": ("ATM", "Branch", "Mobile", "Online"),
    "segment": ("Corporate", "Retail", "SME"),
    "risk_rating": ("A", "B", "C", "D", "E"),
    "stage": ("1", "2", "3"),
}

# Key columns identify the record; correcting one would detach the correction from the record.
KEY_COLUMNS = {
    "branches": {"branch_id"}, "customers": {"customer_id"}, "accounts": {"account_id"},
    "loans": {"loan_id"}, "transactions": {"transaction_id"}, "capital_positions": {"month"},
    "liquidity_daily": {"date"}, "fx_rates": {"date", "currency_pair"},
}


@router.get("/pipeline/{recon_id}/corrections")
def list_corrections(recon_id: int):
    _item(recon_id)
    return _corrections("recon_id", recon_id)


def _corrections(owner_col: str, owner_id: int) -> list:
    """The values proposed (or approved) for an item or a group; withdrawn ones are left out."""
    return query(
        f"""SELECT c.correction_id, c.source_table, c.record_key, c.field_name, c.old_value, c.new_value,
                   c.status, c.entered_at, ue.name AS entered_by_name, ua.name AS approved_by_name, c.approved_at, c.synced_at
            FROM reconciliation_corrections c JOIN users ue ON ue.user_id = c.entered_by
            LEFT JOIN users ua ON ua.user_id = c.approved_by
            WHERE c.{owner_col} = %s AND c.status <> 'WITHDRAWN' ORDER BY c.record_key, c.field_name""",
        (owner_id,),
    )


class CorrectionRequest(BaseModel):
    record_key: str
    field_name: str
    new_value: str


@router.post("/pipeline/{recon_id}/corrections")
def propose_correction(recon_id: int, body: CorrectionRequest, user: dict = Depends(current_user)):
    """A proposed value for one field of one rejected record behind this item. A second proposal for
    the same field replaces the first. Kept as PROPOSED until the CFO approves the decision."""
    item = _item(recon_id)
    if item["status"] not in EDITABLE_STATUSES:
        raise HTTPException(409, f"Corrected values can only be entered while the team is reviewing the item (it is {item['status'].lower().replace('_', ' ')})")
    if not body.new_value.strip():
        raise HTTPException(400, "Enter the corrected value")
    rejected = query_one(
        """SELECT record_data FROM data_quality_exceptions
           WHERE source_table = %s AND record_key = %s AND source_system = %s AND source_country = %s
             AND ingest_batch_id = %s AND record_data IS NOT NULL LIMIT 1""",
        (item["source_table"], body.record_key, item["source_system"], item["source_country"], item["ingest_batch_id"]),
    )
    if rejected is None:
        raise HTTPException(400, f"{body.record_key} is not a rejected record of this item")
    data = rejected["record_data"]
    if body.field_name not in data:
        raise HTTPException(400, f"{item['source_table']} has no field {body.field_name!r}")
    if body.field_name in KEY_COLUMNS.get(item["source_table"], set()):
        raise HTTPException(400, f"{body.field_name} identifies the record and can't be corrected here")
    old = data[body.field_name]
    old_value = None if old is None else str(old)
    new_value = body.new_value.strip()
    if old_value is not None and new_value.casefold() == old_value.strip().casefold():
        raise HTTPException(400, f"{new_value} is the same as the rejected value: it would be rejected again")
    allowed = ALLOWED_VALUES.get(body.field_name)
    if allowed:
        # The pipeline's check is exact, so a different case is stored the way it accepts it ("usd" -> "USD").
        match = next((a for a in allowed if a.casefold() == new_value.casefold()
                      or (body.field_name == "stage" and new_value.replace(".0", "") == a)), None)
        if match is None:
            raise HTTPException(400, f"{body.field_name} must be one of {', '.join(allowed)}: the pipeline rejects anything else")
        new_value = match
    # A numeric field must get a number: Databricks casts the value into the column's type (5b).
    if isinstance(old, (int, float)) and not isinstance(old, bool):
        try:
            float(body.new_value.replace(",", ""))
        except ValueError:
            raise HTTPException(400, f"{body.field_name} is a number - enter a number")
    row = write(
        """WITH ins AS (
               INSERT INTO reconciliation_corrections (recon_id, source_table, record_key, field_name, old_value, new_value, entered_by)
               VALUES (%s, %s, %s, %s, %s, %s, %s)
               ON CONFLICT (recon_id, source_table, record_key, field_name) WHERE status = 'PROPOSED'
               DO UPDATE SET new_value = EXCLUDED.new_value, entered_by = EXCLUDED.entered_by, entered_at = now()
               RETURNING correction_id, old_value, new_value),
           aud AS (
               INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
               SELECT %s, 'CORRECTION_PROPOSED', 'reconciliation_correction', %s, old_value, new_value FROM ins)
           SELECT correction_id FROM ins""",
        (recon_id, item["source_table"], body.record_key, body.field_name, old_value, new_value, user["user_id"],
         user["user_id"], f"{item['source_table']}:{body.record_key}:{body.field_name}"),
    )
    return {"correction_id": row["correction_id"]}


# ---- Runs and their sign-off (specs/reconciliation-approvals.md) ---------------------------------

RUN_COLUMNS = """r.run_id, r.source_system, r.run_key, r.run_date, r.status, r.signed_at, r.sign_note,
       us.name AS signed_by_name, r.created_at, r.signed_tasks, r.carried_tasks, r.carried_to_run_id,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.carried_count > 0 AND p.status IN ('OPEN', 'WITH_TEAM'))
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.carried_count > 0 AND g.status IN ('PENDING', 'OPEN')) AS carried_in,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.escalated_at IS NOT NULL AND p.status IN ('OPEN', 'WITH_TEAM'))
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.escalated_at IS NOT NULL AND g.status IN ('PENDING', 'OPEN')) AS escalated,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.status <> 'SUPERSEDED')
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id) AS tasks,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.status IN ('DECIDED', 'APPROVED'))
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.status = 'CLOSED') AS decided,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.status = 'AWAITING_CFO')
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.status = 'AWAITING_CFO') AS awaiting_cfo,
       (SELECT count(*) FROM pipeline_reconciliation p WHERE p.run_id = r.run_id AND p.sent_back_at IS NOT NULL AND p.status IN ('OPEN', 'WITH_TEAM'))
     + (SELECT count(*) FROM reconciliation_groups g WHERE g.run_id = r.run_id AND g.sent_back_at IS NOT NULL AND g.status IN ('PENDING', 'OPEN')) AS sent_back"""
RUN_FROM = "reconciliation_runs r LEFT JOIN users us ON us.user_id = r.signed_by"


def _with_name(run: dict) -> dict:
    run["name"] = run_name(run["source_system"], run["run_date"], run["run_key"])
    return run


def _run_brief(run_id):
    if run_id is None:
        return None
    run = query_one(f"SELECT {RUN_COLUMNS} FROM {RUN_FROM} WHERE r.run_id = %s", (run_id,))
    return _with_name(run) if run else None


@router.get("/carried")
def carried_tasks():
    """Open reconciliation tasks carried over at a sign-off, by kind and id: how many times, since when,
    and whether they're escalated. The Tasks list marks and sorts them from this."""
    rows = query(
        """SELECT 'reconciliation' AS kind, recon_id::text AS id, carried_count, carried_since, escalated_at
           FROM pipeline_reconciliation WHERE carried_count > 0 AND status IN ('OPEN', 'WITH_TEAM')
           UNION ALL
           SELECT 'recon_group', group_id::text, carried_count, carried_since, escalated_at
           FROM reconciliation_groups WHERE carried_count > 0 AND status IN ('PENDING', 'OPEN')"""
    )
    out = {"reconciliation": {}, "recon_group": {}}
    for r in rows:
        out[r["kind"]][r["id"]] = {"carried_count": r["carried_count"], "carried_since": r["carried_since"],
                                   "escalated": r["escalated_at"] is not None}
    return out


@router.get("/task-runs")
def task_runs():
    """The run each open reconciliation task belongs to, by kind and id, for the Tasks screen's Source
    and Run filters. From the database, not the task's variables: a carried-over task moves to a new run."""
    rows = query(
        """SELECT t.kind, t.id, r.run_id, r.source_system, r.run_date, r.run_key FROM (
               SELECT 'reconciliation' AS kind, recon_id::text AS id, run_id FROM pipeline_reconciliation
               WHERE run_id IS NOT NULL AND status IN ('OPEN', 'WITH_TEAM', 'AWAITING_CFO')
               UNION ALL
               SELECT 'recon_group', group_id::text, run_id FROM reconciliation_groups
               WHERE run_id IS NOT NULL AND status IN ('PENDING', 'OPEN', 'AWAITING_CFO')
               UNION ALL
               SELECT 'recon_run', run_id::text, run_id FROM reconciliation_runs WHERE status IN ('OPEN', 'IN_SIGNOFF')
           ) t JOIN reconciliation_runs r ON r.run_id = t.run_id"""
    )
    out = {"reconciliation": {}, "recon_group": {}, "recon_run": {}}
    for r in rows:
        out[r["kind"]][r["id"]] = {
            "run_id": r["run_id"], "source_system": r["source_system"],
            "source_name": SOURCE_LABEL.get(r["source_system"], r["source_system"]),
            "run_date": r["run_date"], "day": run_day(r["run_date"], r["run_key"]),
        }
    return out


@router.get("/runs")
def current_runs():
    """Each source's current run (the newest that isn't superseded): how many tasks are decided, how
    many wait for the CFO, and its sign-off."""
    return [_with_name(r) for r in query(
        f"""SELECT DISTINCT ON (r.source_system) {RUN_COLUMNS} FROM {RUN_FROM}
            WHERE r.status <> 'SUPERSEDED' ORDER BY r.source_system, r.run_id DESC"""
    )]


@router.get("/runs/{run_id}")
def run_detail(run_id: int):
    """A run and every task in it, for the sign-off popup: what was decided, by whom, who approved it,
    and the fixes that go with it."""
    run = _run_brief(run_id)
    if run is None:
        raise HTTPException(404, "No such run")
    tasks = query(
        """SELECT 'reconciliation' AS kind, p.recon_id AS id, p.title, p.status, p.decision, ud.name AS decided_by_name,
                  p.decided_by, ua.name AS approved_by_name, p.cfo_required, p.cfo_reason,
                  (SELECT count(*) FROM reconciliation_corrections c WHERE c.recon_id = p.recon_id AND c.status <> 'WITHDRAWN') AS fixes,
                  p.carried_count, p.escalated_at IS NOT NULL AS escalated
           FROM pipeline_reconciliation p LEFT JOIN users ud ON ud.user_id = p.decided_by LEFT JOIN users ua ON ua.user_id = p.approved_by
           WHERE p.run_id = %s AND p.status <> 'SUPERSEDED'
           UNION ALL
           SELECT 'recon_group', g.group_id, g.title, g.status, g.decision, ud.name, g.decided_by, ua.name, g.cfo_required, g.cfo_reason,
                  (SELECT count(*) FROM reconciliation_corrections c WHERE c.group_id = g.group_id AND c.status <> 'WITHDRAWN'),
                  g.carried_count, g.escalated_at IS NOT NULL
           FROM reconciliation_groups g LEFT JOIN users ud ON ud.user_id = g.decided_by LEFT JOIN users ua ON ua.user_id = g.approved_by
           WHERE g.run_id = %s
           ORDER BY 9 DESC, 3""",
        (run_id, run_id),
    )
    for t in tasks:
        t["title"] = t["title"] or (f"Item #{t['id']}" if t["kind"] == "reconciliation" else f"Group #{t['id']}")
        t["decided"] = t["status"] in ("DECIDED", "APPROVED", "CLOSED")
        t["awaiting_cfo"] = t["status"] == "AWAITING_CFO"
    counts = {}
    for t in tasks:
        if t["decided"] and t["decision"]:
            counts[t["decision"]] = counts.get(t["decision"], 0) + 1
    words = {"ACCEPT": "accepted", "CORRECT": "corrected", "DISMISS": "dismissed"}
    decided = sum(t["decided"] for t in tasks)
    if not tasks:
        headline = f"The {run['name']} found nothing to review."
    elif decided == len(tasks):
        parts = ", ".join(f"{n} {words[d]}" for d, n in counts.items())
        headline = f"All {len(tasks)} task{'' if len(tasks) == 1 else 's'} from the {run['name']} are decided: {parts}."
    else:
        open_n = len(tasks) - decided
        headline = (f"{decided} of {len(tasks)} tasks from the {run['name']} are decided; the {open_n} still open "
                    f"will be carried over to the next day with a high priority.")
    waiting = sum(t["awaiting_cfo"] for t in tasks)
    run["tasks"] = tasks
    run["summary"] = {
        "headline": headline,
        "job": ((f"First approve or send back the {waiting} task{'' if waiting == 1 else 's'} waiting for you. " if waiting else "")
                + ("Check the decisions, then sign off the decided tasks (say why the open ones are carried over), or send back "
                   "the ones that need another look." if decided < len(tasks) else
                   "Check the decisions, then sign off the run, or send back the tasks that need another look (say why).")),
    }
    return run


class ResolveRequest(BaseModel):
    status: Literal["ACCEPTED", "CORRECTED", "DISMISSED"]
    resolution_note: Optional[str] = None


@router.post("/{exception_id}/resolve")
def resolve(exception_id: int, body: ResolveRequest, user: dict = Depends(current_user)):
    # Decisions are made in the group's task (specs/reconciliation-groups.md): a single break can
    # only be resolved here by an admin, as an override - still audited below.
    if user["role"] != "admin":
        raise HTTPException(403, "Reconciliation breaks are decided in their group's task on the Tasks screen")
    if body.status == "CORRECTED" and not body.resolution_note:
        raise HTTPException(400, "resolution_note is required when correcting a value")
    row = write(
        """UPDATE reconciliation_exceptions
           SET status = %s, resolved_by = %s, resolved_at = now(), resolution_note = %s
           WHERE exception_id = %s AND status = 'OPEN'
           RETURNING exception_id, entity_type, entity_id, mismatch_type, field_name""",
        (body.status, user["user_id"], body.resolution_note, exception_id),
    )
    if row is None:
        raise HTTPException(404, "No open exception with that id (already resolved, or doesn't exist)")
    # Same colon-joined natural-key convention as Screen 6's audit entries
    # (source_table:record_key:flag_label) rather than the bare exception_id, so this shows up
    # consistently in Screen 6's shared audit trail view (GET /workflow/audit-log). field_name is
    # appended only when set (VALUE_MISMATCH rows) - it's what disambiguates two mismatches on the
    # same entity, per reconciliation_exceptions' own UNIQUE (..., mismatch_type, field_name).
    object_id = f"{row['entity_type']}:{row['entity_id']}:{row['mismatch_type']}"
    if row["field_name"]:
        object_id += f":{row['field_name']}"
    write(
        """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           VALUES (%s, %s, 'reconciliation_exception', %s, 'OPEN', %s) RETURNING log_id""",
        (user["user_id"], body.status, object_id, body.resolution_note),
    )
    return {"status": "resolved"}
