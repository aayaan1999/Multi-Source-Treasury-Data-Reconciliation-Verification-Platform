"""Reconciliation tab: reads/resolves specs/multi-source-reconciliation.md's
`reconciliation_exceptions` (Neon-slice bronze_neon_* vs this app's own canonical *_clean data).

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


@router.get("")
def list_exceptions(
    status: Optional[str] = None,
    entity_type: Optional[str] = None,
    mismatch_type: Optional[str] = None,
    # Raised from the original 200/1000 cap: MISSING_IN_SOURCE alone currently has ~1,862 open rows,
    # and DataTable already paginates whatever it's given client-side (10/page) - so the fix is
    # letting a filtered fetch actually return everything that matches, not adding server-side
    # offset pagination on top of that (this table is thousands of rows, not millions).
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
                   r.resolved_by, u.name AS resolved_by_name, r.resolved_at, r.resolution_note
            FROM reconciliation_exceptions r LEFT JOIN users u ON u.user_id = r.resolved_by
            {where} ORDER BY r.detected_at DESC LIMIT %s""",
        tuple(params),
    )


class ResolveRequest(BaseModel):
    status: Literal["ACCEPTED", "CORRECTED", "DISMISSED"]
    resolution_note: Optional[str] = None


@router.post("/{exception_id}/resolve")
def resolve(exception_id: int, body: ResolveRequest, user: dict = Depends(current_user)):
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
