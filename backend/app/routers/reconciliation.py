"""Reconciliation tab: reads/resolves specs/multi-source-reconciliation.md's
`reconciliation_exceptions` (Neon-slice bronze_neon_* vs this app's own canonical *_clean data), and
reads specs/pipeline-reconciliation.md's `pipeline_reconciliation` items (received vs kept per
source, country and table - FLOW-3), with the rejected records behind each one.

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
                   r.resolved_by, u.name AS resolved_by_name, r.resolved_at, r.resolution_note
            FROM reconciliation_exceptions r LEFT JOIN users u ON u.user_id = r.resolved_by
            {where} ORDER BY r.detected_at DESC LIMIT %s""",
        tuple(params),
    )


PIPELINE_COLUMNS = """p.recon_id, p.ingest_batch_id, p.source_system, p.source_country, p.source_table,
       p.received_rows, p.clean_rows, p.rejected_rows, p.amount_column, p.unreadable_amount_rows,
       p.amounts_by_currency, p.has_gap, p.status, p.detected_at"""

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
        f"""SELECT {PIPELINE_COLUMNS} FROM pipeline_reconciliation p {where}
            ORDER BY p.has_gap DESC, p.rejected_rows DESC, p.source_table, p.source_country LIMIT %s""",
        tuple(params),
    )


@router.get("/pipeline/{recon_id}/records")
def pipeline_item_records(recon_id: int):
    """The rejected records behind one item, from data_quality_exceptions (same table, source,
    country and run). The exceptions log only holds the latest run's rejects, so an older run's
    item says the detail is gone rather than showing a different run's records."""
    item = query_one(f"SELECT {PIPELINE_COLUMNS} FROM pipeline_reconciliation p WHERE p.recon_id = %s", (recon_id,))
    if item is None:
        raise HTTPException(404, "No such reconciliation item")
    records = query(
        """SELECT record_key, flag_label, description FROM data_quality_exceptions
           WHERE source_table = %s AND source_system = %s AND source_country = %s AND ingest_batch_id = %s
           ORDER BY record_key, flag_label""",
        (item["source_table"], item["source_system"], item["source_country"], item["ingest_batch_id"]),
    )
    # Every rejected row of the run the log holds has at least one exception, so rejected rows with
    # no records means the item is from an older run whose detail has been replaced.
    return {"item": item, "records": records, "records_available": bool(records) or item["rejected_rows"] == 0}


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
