"""Reconciliation tab: reads/resolves specs/multi-source-reconciliation.md's
`reconciliation_exceptions` (Neon-slice bronze_neon_* vs this app's own canonical *_clean data), and
reads specs/pipeline-reconciliation.md's `pipeline_reconciliation` items (received vs kept per
source, country and table - FLOW-3), with the rejected records behind each one. Pipeline items also
carry the CFO workflow (specs/cfo-reconciliation-workflow.md, FLOW-5): the Camunda process decides
the steps; these endpoints record what happens at each one (reassign, corrections, submit, return).

Standalone from Screen 6 - not routed through Camunda. Both handle "a flagged discrepancy needs a
human decision," but this one is data-layer verification (does our copy of the data match the
second Neon project standing in for a Core Banking System?), not a regulatory/fraud workflow, and
there's no BPMN process or candidate-group routing for it (deliberately: see the decision to keep
this a plain read/resolve screen instead of a fourth Camunda candidate group).
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..db import query, query_one, write
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
def groups(status: Optional[str] = None, limit: int = Query(500, le=5000)):
    """Groups of breaks with the same cause (one task each), important ones first."""
    where, params = ("WHERE status = %s", (status,)) if status else ("", ())
    return query(
        f"""SELECT group_id, source_system, entity_type, field_name, mismatch_type, pattern, important, break_count,
                   total_difference, largest_difference, requires_second_approval, team, status, decision,
                   due_date, created_at, closed_at
            FROM reconciliation_groups {where}
            ORDER BY (status = 'CLOSED'), important DESC, break_count DESC, group_id LIMIT %s""",
        (*params, limit),
    )


@router.get("/groups/{group_id}")
def group_detail(group_id: int):
    """A group and every break in it, for the review popup (carve-outs are picked from this list).
    Breaks decided in this group keep pointing at it; carved-out ones have left it."""
    g = query_one("SELECT * FROM reconciliation_groups WHERE group_id = %s", (group_id,))
    if g is None:
        raise HTTPException(404, "No such group")
    g["breaks"] = query(
        """SELECT exception_id, entity_type, entity_id, field_name, source_value, canonical_value, mismatch_type,
                  status, first_seen, last_seen, times_seen, recurring
           FROM reconciliation_exceptions WHERE group_id = %s ORDER BY entity_id LIMIT 5000""",
        (group_id,),
    )
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
    signoff = query_one(
        """SELECT s.status, s.prepared_at, s.prepare_note, up.name AS prepared_by_name, s.prepared_by,
                  s.signed_at, s.sign_note, us.name AS signed_by_name
           FROM reconciliation_signoffs s LEFT JOIN users up ON up.user_id = s.prepared_by
           LEFT JOIN users us ON us.user_id = s.signed_by
           WHERE s.run_date = %s AND s.source_system = %s""",
        (run_date, source_system),
    )
    return {"run_date": run_date, "source_system": source_system, **counts, **group_counts, "signoff": signoff}


class SubmitRunRequest(BaseModel):
    source_system: str = "neon"
    note: Optional[str] = None


@router.post("/run/submit")
def submit_run(body: SubmitRunRequest, user: dict = Depends(current_user)):
    """The preparer submits the latest run for sign-off. While important breaks are still open, a
    note saying why is required."""
    summary = run_summary(body.source_system)
    if summary["run_date"] is None:
        raise HTTPException(404, "No reconciliation run yet")
    if summary["important_open"] and not (body.note or "").strip():
        raise HTTPException(400, f"{summary['important_open']} important break(s) are still open - add a note explaining why the run can be signed off")
    if summary["signoff"] and summary["signoff"]["status"] in ("SUBMITTED", "SIGNED_OFF"):
        raise HTTPException(409, f"This run is already {summary['signoff']['status'].lower().replace('_', ' ')}")
    write(
        """WITH up AS (
               INSERT INTO reconciliation_signoffs (run_date, source_system, status, prepared_by, prepared_at, prepare_note)
               VALUES (%s, %s, 'SUBMITTED', %s, now(), %s)
               ON CONFLICT (run_date, source_system) DO UPDATE SET status = 'SUBMITTED', prepared_by = EXCLUDED.prepared_by,
                   prepared_at = now(), prepare_note = EXCLUDED.prepare_note, signed_by = NULL, signed_at = NULL, sign_note = NULL
               RETURNING run_date)
           INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           SELECT %s, 'RUN_SUBMITTED', 'reconciliation_run', %s, NULL, %s FROM up RETURNING log_id""",
        (summary["run_date"], body.source_system, user["user_id"], body.note, user["user_id"],
         f"{body.source_system}:{summary['run_date']}", body.note),
    )
    return {"status": "SUBMITTED"}


class SignOffRequest(BaseModel):
    source_system: str = "neon"
    decision: Literal["SIGN_OFF", "RETURN"]
    note: Optional[str] = None


@router.post("/run/signoff")
def sign_off_run(body: SignOffRequest, user: dict = Depends(current_user)):
    """A second person (CFO/approver or admin, never the preparer) signs the run off or returns it."""
    if user["role"] not in ("approver", "admin"):
        raise HTTPException(403, "Only the CFO (approver) or an admin can sign off a run")
    summary = run_summary(body.source_system)
    signoff = summary.get("signoff")
    if not signoff or signoff["status"] != "SUBMITTED":
        raise HTTPException(409, "The run hasn't been submitted for sign-off")
    if signoff["prepared_by"] == user["user_id"]:
        raise HTTPException(409, "The person who prepared the run can't also sign it off")
    if body.decision == "RETURN" and not (body.note or "").strip():
        raise HTTPException(400, "Say why the run is being returned")
    new_status = "SIGNED_OFF" if body.decision == "SIGN_OFF" else "RETURNED"
    write(
        """WITH up AS (
               UPDATE reconciliation_signoffs SET status = %s, signed_by = %s, signed_at = now(), sign_note = %s
               WHERE run_date = %s AND source_system = %s AND status = 'SUBMITTED' RETURNING run_date)
           INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           SELECT %s, %s, 'reconciliation_run', %s, 'SUBMITTED', %s FROM up RETURNING log_id""",
        (new_status, user["user_id"], body.note, summary["run_date"], body.source_system,
         user["user_id"], "RUN_" + new_status, f"{body.source_system}:{summary['run_date']}", body.note),
    )
    return {"status": new_status}



@router.get("")
def list_exceptions(
    status: Optional[str] = None,
    entity_type: Optional[str] = None,
    mismatch_type: Optional[str] = None,
    # Up to 5000: the Reconciliation page fetches the whole table once (unfiltered) and filters its
    # tabs/status in the browser, so this must return every row. The table is hundreds-to-thousands
    # of rows, not millions; move filtering back server-side if it ever outgrows this cap.
    limit: int = Query(200, le=5000),
):
    clauses, params = [], []
    for col, val in (("status", status), ("entity_type", entity_type), ("mismatch_type", mismatch_type)):
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
       p.amounts_by_currency, p.has_gap, p.status, p.detected_at, p.note,
       p.assigned_to, ua.name AS assigned_to_name, p.approved_by, p.approved_at"""
PIPELINE_FROM = "pipeline_reconciliation p LEFT JOIN users ua ON ua.user_id = p.assigned_to"

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
    # Every rejected row of the run the log holds has at least one exception, so rejected rows with
    # no records means the item is from an older run whose detail has been replaced.
    return {"item": item, "records": records, "records_available": bool(records) or item["rejected_rows"] == 0}


def _item(recon_id: int) -> dict:
    item = query_one(f"SELECT {PIPELINE_COLUMNS} FROM {PIPELINE_FROM} WHERE p.recon_id = %s", (recon_id,))
    if item is None:
        raise HTTPException(404, "No such reconciliation item")
    return item


# ---- CFO workflow (specs/cfo-reconciliation-workflow.md) --------------------------------------

# Corrections can be proposed while the item is with the CFO (handling it directly) or the assignee.
EDITABLE_STATUSES = ("WITH_CFO", "ASSIGNED")

# Key columns identify the record; correcting one would detach the correction from the record.
KEY_COLUMNS = {
    "branches": {"branch_id"}, "customers": {"customer_id"}, "accounts": {"account_id"},
    "loans": {"loan_id"}, "transactions": {"transaction_id"}, "capital_positions": {"month"},
    "liquidity_daily": {"date"}, "fx_rates": {"date", "currency_pair"},
}


@router.get("/assignees")
def assignees():
    """Who the CFO can reassign an item to."""
    return query(
        "SELECT u.user_id, u.name, r.name AS role FROM users u JOIN roles r ON r.role_id = u.role_id ORDER BY u.name"
    )


@router.get("/pipeline/{recon_id}/corrections")
def list_corrections(recon_id: int):
    _item(recon_id)
    return query(
        """SELECT c.correction_id, c.source_table, c.record_key, c.field_name, c.old_value, c.new_value,
                  c.status, c.entered_at, ue.name AS entered_by_name, c.approved_at, c.synced_at
           FROM reconciliation_corrections c JOIN users ue ON ue.user_id = c.entered_by
           WHERE c.recon_id = %s ORDER BY c.entered_at""",
        (recon_id,),
    )


class CorrectionRequest(BaseModel):
    record_key: str
    field_name: str
    new_value: str


@router.post("/pipeline/{recon_id}/corrections")
def propose_correction(recon_id: int, body: CorrectionRequest, user: dict = Depends(current_user)):
    """A proposed value for one field of one rejected record behind this item. A second proposal for
    the same field replaces the first. Kept as PROPOSED until the CFO approves the item."""
    item = _item(recon_id)
    if item["status"] not in EDITABLE_STATUSES:
        raise HTTPException(409, f"Corrections can only be added while the item is with the CFO or the assignee (it is {item['status']})")
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
        (recon_id, item["source_table"], body.record_key, body.field_name, old_value, body.new_value.strip(), user["user_id"],
         user["user_id"], f"{item['source_table']}:{body.record_key}:{body.field_name}"),
    )
    return {"correction_id": row["correction_id"]}


# event -> (status it must be in, status it moves to). Approval is written by the outcome worker when
# the Camunda process reaches its service task, not here (spec section 5).
TRANSITIONS = {
    "REASSIGNED": ("WITH_CFO", "ASSIGNED"),
    "SUBMITTED": ("ASSIGNED", "SUBMITTED"),
    "RETURNED": ("SUBMITTED", "ASSIGNED"),
}


class EventRequest(BaseModel):
    event: Literal["REASSIGNED", "SUBMITTED", "RETURNED"]
    assignee_user_id: Optional[int] = None
    comment: Optional[str] = None


@router.post("/pipeline/{recon_id}/events")
def workflow_event(recon_id: int, body: EventRequest, user: dict = Depends(current_user)):
    """Records a step the Tasks screen just completed in Camunda: status change + one audit row, in
    one statement. Refused when the item isn't at the step the event belongs to."""
    item = _item(recon_id)
    before, after = TRANSITIONS[body.event]
    detail = body.comment
    if body.event == "REASSIGNED":
        assignee = query_one("SELECT user_id, name FROM users WHERE user_id = %s", (body.assignee_user_id,)) if body.assignee_user_id else None
        if assignee is None:
            raise HTTPException(400, "Pick who to assign it to")
        detail = f"assigned to {assignee['name']}" + (f": {body.comment}" if body.comment else "")
    if body.event == "RETURNED" and not (body.comment or "").strip():
        raise HTTPException(400, "Say why it's being returned")
    row = write(
        """WITH upd AS (
               UPDATE pipeline_reconciliation SET status = %s, assigned_to = COALESCE(%s, assigned_to)
               WHERE recon_id = %s AND status = %s RETURNING recon_id),
           aud AS (
               INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
               SELECT %s, %s, 'reconciliation_item', recon_id::text, %s, %s FROM upd)
           SELECT recon_id FROM upd""",
        (after, body.assignee_user_id if body.event == "REASSIGNED" else None, recon_id, before,
         user["user_id"], body.event, before, detail),
    )
    if row is None:
        raise HTTPException(409, f"The item isn't at that step (it is {item['status']})")
    return {"status": after}


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
