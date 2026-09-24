"""Postgres side of the CFO reconciliation workflow (specs/cfo-reconciliation-workflow.md, FLOW-5).

Plain psycopg2, no Zeebe imports, so poll_worker.py and outcome_worker.py share it and the backend
tests can exercise it against a real Postgres without a Camunda stack.
"""
import psycopg2.extras

PROCESS_ID = "reconciliation-review"
RECORD_TYPE = "reconciliation"
SOURCE_TABLE = "pipeline_reconciliation"
FLAG_LABEL = "RECONCILIATION"


def cfo_user_id(conn, email: str) -> int:
    """The user who acts as CFO (the demo's approver by default - spec section 2)."""
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
        row = cur.fetchone()
    if row is None:
        raise RuntimeError(f"No user {email!r} to act as CFO - seed the demo users or set CFO_EMAIL")
    return row[0]


def fetch_unstarted(conn) -> list[dict]:
    """OPEN items with a gap that have no reconciliation-review process yet."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT p.recon_id, p.source_system, p.source_country, p.source_table,
                      p.received_rows, p.rejected_rows, p.note
               FROM pipeline_reconciliation p
               WHERE p.status = 'OPEN' AND p.has_gap
                 AND NOT EXISTS (
                     SELECT 1 FROM camunda_process_tracking t
                     WHERE t.record_type = %s AND t.source_table = %s
                       AND t.record_key = p.recon_id::text AND t.flag_label = %s)
               ORDER BY p.recon_id""",
            (RECORD_TYPE, SOURCE_TABLE, FLAG_LABEL),
        )
        return cur.fetchall()


def title(item: dict) -> str:
    """One line for the task list, e.g. "CORE_CSV · Lebanon · transactions: 1 of 6 rows rejected",
    or the completeness check's note ("... : No rows delivered")."""
    what = item.get("note") or f"{item['rejected_rows']} of {item['received_rows']} rows rejected"
    return f"{item['source_system']} · {item['source_country']} · {item['source_table']}: {what}"


def process_variables(item: dict, cfo_id: int) -> dict:
    """Same variable names as transaction-review where they mean the same thing, so the Tasks
    screen's list, comments and audit keys work unchanged."""
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(item["recon_id"]),
        "flagLabel": FLAG_LABEL,
        "title": title(item),
        "cfoUserId": cfo_id,
    }


def record_started(conn, recon_id: int, process_instance_key: int) -> None:
    """Remember the process (so it's never started twice) and hand the item to the CFO."""
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (RECORD_TYPE, SOURCE_TABLE, str(recon_id), FLAG_LABEL, process_instance_key),
        )
        cur.execute("UPDATE pipeline_reconciliation SET status = 'WITH_CFO' WHERE recon_id = %s AND status = 'OPEN'", (recon_id,))
    conn.commit()


def approve(conn, recon_id: int, approved_by: int) -> None:
    """The write-reconciliation-outcome service task: item and its proposed corrections APPROVED,
    with one audit row for the item and one per correction, all in one transaction. Idempotent: a
    retried job finds the item already approved and changes nothing."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE pipeline_reconciliation SET status = 'APPROVED', approved_by = %s, approved_at = now()
               WHERE recon_id = %s AND status <> 'APPROVED' RETURNING recon_id""",
            (approved_by, recon_id),
        )
        if cur.fetchone() is None:
            conn.rollback()
            return
        cur.execute(
            """UPDATE reconciliation_corrections SET status = 'APPROVED', approved_by = %s, approved_at = now()
               WHERE recon_id = %s AND status = 'PROPOSED'
               RETURNING source_table, record_key, field_name, old_value, new_value""",
            (approved_by, recon_id),
        )
        corrections = cur.fetchall()
        audit = [(approved_by, "APPROVED", "reconciliation_item", str(recon_id), None, f"{len(corrections)} correction(s)")]
        audit += [
            (approved_by, "CORRECTION_APPROVED", "reconciliation_correction", f"{t}:{k}:{f}", old, new)
            for t, k, f, old, new in corrections
        ]
        cur.executemany(
            """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
               VALUES (%s, %s, %s, %s, %s, %s)""",
            audit,
        )
    conn.commit()
