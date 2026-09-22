"""Screen 6 - Report Workflow (specs/screen-06-report-workflow.md).

Camunda's Tasklist API is the source of truth for "what's open" and completing a task
(specs/camunda-bpmn-process-design.md, CLAUDE.md's Workflow Engine Decision) - the frontend calls
Tasklist directly for both, not this backend. What lives here is everything Camunda doesn't do:
joining a flagged record back to its full source row, comments, the insert-only audit_log mirror
of what Camunda already tracked internally, breach alerts, and the small management view.
"""
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..db import query, query_one, write
from ..security import current_user

router = APIRouter(prefix="/workflow", tags=["screen 6 - report workflow"], dependencies=[Depends(current_user)])

# source_table -> single-column primary key, for joining a flagged record back to its full row.
# fx_rates has no single-column PK (see below) so it isn't in this map.
ENTITY_PK = {
    "customers": "customer_id",
    "accounts": "account_id",
    "loans": "loan_id",
    "transactions": "transaction_id",
    "branches": "branch_id",
    "capital_positions": "month",
    "liquidity_daily": "date",
}
SOURCE_TABLES = set(ENTITY_PK) | {"fx_rates"}


def _source_row(source_table: str, record_key: str) -> Optional[dict]:
    """The full underlying row a flagged record points at (specs/notebook-02-bank-data-quality.md
    section 2: record_key is the source table's PK, or for fx_rates a synthesised
    "date_currencypair" key, since no single column identifies a rate row)."""
    if source_table not in SOURCE_TABLES:
        raise HTTPException(400, f"Unknown source_table: {source_table}")
    if source_table == "fx_rates":
        date, _, pair = record_key.partition("_")
        return query_one("SELECT * FROM fx_rates WHERE date = %s AND currency_pair = %s", (date, pair))
    return query_one(f"SELECT * FROM {source_table} WHERE {ENTITY_PK[source_table]} = %s", (record_key,))


@router.get("/exceptions/detail")
def exception_detail(
    record_type: Literal["data_quality", "fraud"] = Query(...),
    source_table: str = Query(...),
    record_key: str = Query(...),
    flag_label: str = Query(...),
):
    """Full record detail for the review screen: the flag itself plus the underlying source row.
    Tasklist already carries the flag's own fields as process variables, but not the source row -
    that only lives in this app's Postgres, so the frontend still needs this endpoint even though
    task state and task actions come from Tasklist directly."""
    if record_type == "data_quality":
        flag = query_one(
            "SELECT source_table, record_key, flag_label, description FROM data_quality_exceptions "
            "WHERE source_table = %s AND record_key = %s AND flag_label = %s",
            (source_table, record_key, flag_label),
        )
    else:
        flag = query_one(
            "SELECT transaction_id AS record_key, flag_label, flag_type, description, status, detected_at "
            "FROM flagged_transactions WHERE transaction_id = %s AND flag_label = %s",
            (record_key, flag_label),
        )
    if flag is None:
        raise HTTPException(404, "No such flagged record")
    tracking = query_one(
        "SELECT process_instance_key, started_at FROM camunda_process_tracking "
        "WHERE record_type = %s AND source_table = %s AND record_key = %s AND flag_label = %s",
        (record_type, source_table, record_key, flag_label),
    )
    return {"flag": flag, "source_row": _source_row(source_table, record_key), "process": tracking}


@router.get("/exceptions/comments")
def list_comments(source_table: str, record_key: str, flag_label: str):
    return query(
        """SELECT c.comment_id, c.comment_text, c.created_at, c.parent_comment_id, u.name AS author, u.user_id
           FROM comments c JOIN users u ON u.user_id = c.user_id
           WHERE c.source_table = %s AND c.record_key = %s AND c.flag_label = %s
           ORDER BY c.created_at""",
        (source_table, record_key, flag_label),
    )


class CommentRequest(BaseModel):
    source_table: str
    record_key: str
    flag_label: str
    comment_text: str
    parent_comment_id: Optional[int] = None


@router.post("/exceptions/comments")
def add_comment(body: CommentRequest, user: dict = Depends(current_user)):
    if body.source_table not in SOURCE_TABLES:
        raise HTTPException(400, f"Unknown source_table: {body.source_table}")
    row = write(
        """INSERT INTO comments (source_table, record_key, flag_label, user_id, comment_text, parent_comment_id)
           VALUES (%s, %s, %s, %s, %s, %s) RETURNING comment_id, created_at""",
        (body.source_table, body.record_key, body.flag_label, user["user_id"], body.comment_text, body.parent_comment_id),
    )
    _log_audit(user["user_id"], "COMMENT", f"{body.source_table}:{body.record_key}:{body.flag_label}", None, body.comment_text)
    return {"comment_id": row["comment_id"], "created_at": row["created_at"]}


def _log_audit(user_id: int, action: str, object_id: str, old_value, new_value) -> None:
    write(
        """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           VALUES (%s, %s, 'exception', %s, %s, %s) RETURNING log_id""",
        (user_id, action, object_id, old_value, new_value),
    )


class TaskCompletionRequest(BaseModel):
    source_table: str
    record_key: str
    flag_label: str
    outcome: Literal["APPROVED", "REJECTED", "CORRECTED"]
    camunda_task_id: Optional[str] = None


@router.post("/exceptions/task-completions")
def log_task_completion(body: TaskCompletionRequest, user: dict = Depends(current_user)):
    """Mirrors a Tasklist task completion into audit_log (specs/screen-06-report-workflow.md
    section 2.5: "every task completion writes a row here"). The frontend calls this right after
    completing the task via Tasklist's own API - Camunda already recorded the decision as the
    authoritative copy (and the outcome worker writes review_outcomes), this is only the
    human-readable mirror. Not a workflow action in its own right: completing this endpoint
    without also completing the Tasklist task would leave the task open, and vice versa - the
    frontend is responsible for doing both."""
    _log_audit(user["user_id"], body.outcome, f"{body.source_table}:{body.record_key}:{body.flag_label}",
              None, body.camunda_task_id)
    return {"status": "logged"}


@router.get("/audit-log")
def audit_log(
    object_type: Optional[str] = None,
    object_id: Optional[str] = None,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    limit: int = Query(200, le=1000),
):
    clauses, params = [], []
    for col, val in (("object_type", object_type), ("object_id", object_id), ("user_id", user_id), ("action", action)):
        if val is not None:
            clauses.append(f"a.{col} = %s")
            params.append(val)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    return query(
        f"""SELECT a.log_id, a.timestamp, a.user_id, u.name AS user_name, a.action, a.object_type,
                   a.object_id, a.old_value, a.new_value
            FROM audit_log a LEFT JOIN users u ON u.user_id = a.user_id
            {where} ORDER BY a.timestamp DESC LIMIT %s""",
        tuple(params),
    )


@router.get("/breaches")
def breaches(status: Optional[str] = None):
    where = "WHERE b.status = %s" if status else ""
    params = (status,) if status else ()
    return query(
        f"""SELECT b.breach_id, l.metric_name, l.threshold_value, l.direction, b.detected_at,
                   b.actual_value, b.assigned_to, u.name AS assigned_to_name, b.status, b.action_plan,
                   b.resolved_at, l.resolution_days
            FROM breaches b JOIN limits l ON l.limit_id = b.limit_id
            LEFT JOIN users u ON u.user_id = b.assigned_to
            {where} ORDER BY b.detected_at DESC""",
        params,
    )


@router.get("/stats")
def stats():
    """Small management view (specs/screen-06-report-workflow.md section 2.6): on-time vs late
    report submissions, open breaches by age bucket, and a best-effort average turnaround from
    audit_log (time from a record's first logged event to its outcome). Built last since the spec
    calls it the least load-bearing part of the screen for the demo narrative - this is
    intentionally simpler than sections 1-5, not because the data doesn't support more, but
    because audit_log has no explicit "task assigned" event to measure queue time from, only what
    this screen itself has logged (comments and outcomes)."""
    submissions = query_one(
        """SELECT count(*) FILTER (WHERE submitted_at IS NOT NULL AND submitted_at::date <= due_date) AS on_time,
                  count(*) FILTER (WHERE submitted_at IS NOT NULL AND submitted_at::date > due_date) AS late,
                  count(*) FILTER (WHERE submitted_at IS NULL AND due_date < current_date) AS overdue_open
           FROM report_instances"""
    )
    breach_ages = query(
        """SELECT breach_id,
                  CASE WHEN resolved_at IS NOT NULL THEN 'resolved'
                       WHEN now() - detected_at < interval '1 day' THEN '<1 day'
                       WHEN now() - detected_at < interval '7 days' THEN '1-7 days'
                       ELSE '7+ days' END AS age_bucket
           FROM breaches WHERE status = 'OPEN' OR resolved_at IS NOT NULL"""
    )
    open_by_age = {}
    for row in breach_ages:
        if row["age_bucket"] != "resolved":
            open_by_age[row["age_bucket"]] = open_by_age.get(row["age_bucket"], 0) + 1
    turnaround = query_one(
        """SELECT avg(outcome.timestamp - first_event.timestamp) AS avg_turnaround
           FROM (SELECT object_id, min(timestamp) AS timestamp FROM audit_log GROUP BY object_id) first_event
           JOIN (SELECT object_id, max(timestamp) AS timestamp FROM audit_log
                 WHERE action IN ('APPROVED', 'REJECTED', 'CORRECTED') GROUP BY object_id) outcome
           ON outcome.object_id = first_event.object_id"""
    )
    return {
        "submissions": submissions,
        "open_breaches_by_age": open_by_age,
        "avg_turnaround_seconds": (turnaround["avg_turnaround"].total_seconds()
                                   if turnaround and turnaround["avg_turnaround"] else None),
    }
