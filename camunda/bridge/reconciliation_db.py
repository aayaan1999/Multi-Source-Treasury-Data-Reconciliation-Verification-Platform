"""Postgres side of pipeline-gap tasks (rows a delivery sent that we couldn't load): starting a
reconciliation-task for each gap in a source's newest run, and superseding older runs' untouched items
(specs/reconciliation-approvals.md, specs/cfo-reconciliation-workflow.md for the corrections).
Deciding, approving and sending back live in recon_tasks_db, shared with core-system break groups.

Plain psycopg2, no Zeebe imports, so the workers and the backend tests can exercise it against a real
Postgres without a Camunda stack.
"""
from datetime import date, timedelta

import psycopg2.extras

from sent_back import sent_back_variables

PROCESS_ID = "reconciliation-task"
RECORD_TYPE = "reconciliation"
SOURCE_TABLE = "pipeline_reconciliation"
FLAG_LABEL = "RECONCILIATION"

# Why a row was rejected, in the words the task list uses (Notebook 2's flag labels).
FLAG_WORDS = {
    "INVALID_AMOUNT": "missing amount", "INVALID_CHANNEL": "unknown channel", "INVALID_CURRENCY": "unknown currency",
    "INVALID_RATE": "invalid rate", "INVALID_RWA": "invalid risk-weighted assets", "INVALID_SEGMENT": "unknown segment",
    "INVALID_STAGE": "invalid stage", "MISSING_ACCOUNT_ID": "missing account ID", "MISSING_BRANCH_ID": "missing branch",
    "MISSING_CUSTOMER_ID": "missing customer ID", "MISSING_DATE": "missing date", "MISSING_LOAN_ID": "missing loan ID",
    "MISSING_MONTH": "missing month", "MISSING_RISK_RATING": "missing risk rating",
    "MISSING_TRANSACTION_ID": "missing transaction ID", "NEGATIVE_BALANCE": "negative balance",
    "NEGATIVE_DPD": "negative days past due", "NEGATIVE_HQLA": "negative liquid assets",
    "NEGATIVE_OPEX": "negative running costs", "NPL_STAGE_MISMATCH": "stage doesn't match days past due",
    "ORPHAN_ACCOUNT": "unknown account", "ORPHAN_BRANCH": "unknown branch", "ORPHAN_CUSTOMER": "unknown customer",
    "OUTSTANDING_EXCEEDS_PRINCIPAL": "outstanding above principal", "DUPLICATE_RATE": "duplicate rate",
}

# The newest run of each source (same rule as the backend's LATEST_RUN_PER_SOURCE). Each pipeline run
# re-checks the whole delivery, so an older run's item describes a problem the newest run has already
# re-reported (or no longer has), and data_quality_exceptions only keeps the newest run's records.
LATEST_RUN = """(p.source_system, p.ingest_batch_id) IN (
    SELECT DISTINCT ON (source_system) source_system, ingest_batch_id
    FROM pipeline_reconciliation ORDER BY source_system, detected_at DESC)"""

# Items nobody has decided yet (WITH_CFO: the retired CFO-first process). Once decided, the item is
# part of its run's record and is never closed underneath anyone.
UNTOUCHED_STATUSES = ("OPEN", "WITH_TEAM", "WITH_CFO")


def rules(conn) -> tuple:
    """recon.rules and the due days for this task type (app_settings)."""
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM app_settings WHERE key IN ('recon.rules', 'task.due_days')")
        cfg = dict(cur.fetchall())
    return cfg["recon.rules"], cfg["task.due_days"].get("RECONCILIATION", 3)


def cfo_rule(item: dict, rules: dict):
    """Whether the CFO must approve this item whatever the team decides, and why: a delivery that
    sent nothing, or a gap of important_amount or more in one currency."""
    if item.get("note"):
        return True, "a delivery with no rows"
    gaps = [(abs(v.get("gap") or 0), cur) for cur, v in (item.get("amounts_by_currency") or {}).items()]
    size, currency = max(gaps, default=(0, None))
    if size >= rules["important_amount"]:
        return True, f"a gap of {size:,.2f} {currency}"
    return False, None


def fetch_unstarted(conn) -> list[dict]:
    """OPEN items with a gap, from each source's newest run, that have no task yet, with the reasons
    their rows were rejected. Older runs' items are superseded instead (fetch_superseded)."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT p.recon_id, p.source_system, p.source_country, p.source_table, p.received_rows,
                      p.rejected_rows, p.note, p.amounts_by_currency, p.sent_back_note, p.sent_back_at, p.sent_back_from,
                      (SELECT name FROM users WHERE user_id = p.sent_back_by) AS sent_back_by_name,
                      ARRAY(SELECT DISTINCT d.flag_label FROM data_quality_exceptions d
                            WHERE d.source_table = p.source_table AND d.source_system = p.source_system
                              AND d.source_country = p.source_country AND d.ingest_batch_id = p.ingest_batch_id
                            ORDER BY 1) AS flags
               FROM pipeline_reconciliation p
               WHERE p.status = 'OPEN' AND p.has_gap AND """ + LATEST_RUN + """
                 AND NOT EXISTS (
                     SELECT 1 FROM camunda_process_tracking t
                     WHERE t.record_type = %s AND t.source_table = %s
                       AND t.record_key = p.recon_id::text AND t.flag_label = %s)
               ORDER BY p.recon_id""",
            (RECORD_TYPE, SOURCE_TABLE, FLAG_LABEL),
        )
        return cur.fetchall()


def fetch_superseded(conn) -> list[dict]:
    """Undecided items from a run that is no longer its source's newest, with the task process
    started for each (if any) so the caller can cancel it."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT p.recon_id, p.status, p.ingest_batch_id, t.process_instance_key
               FROM pipeline_reconciliation p
               LEFT JOIN camunda_process_tracking t
                 ON t.record_type = %s AND t.source_table = %s AND t.record_key = p.recon_id::text AND t.flag_label = %s
               WHERE p.status IN %s AND NOT """ + LATEST_RUN + """
                 AND NOT EXISTS (SELECT 1 FROM reconciliation_corrections c
                                 WHERE c.recon_id = p.recon_id AND c.status <> 'WITHDRAWN')
               ORDER BY p.recon_id""",
            (RECORD_TYPE, SOURCE_TABLE, FLAG_LABEL, UNTOUCHED_STATUSES),
        )
        return cur.fetchall()


def mark_superseded(conn, recon_id: int) -> bool:
    """SUPERSEDED with one audit row, only if still undecided (a person acting at the same moment wins).
    Not an approval: nobody decided anything, a newer run replaced it."""
    with conn.cursor() as cur:
        cur.execute(
            """WITH up AS (
                   UPDATE pipeline_reconciliation p SET status = 'SUPERSEDED'
                   FROM (SELECT recon_id, status FROM pipeline_reconciliation WHERE recon_id = %s FOR UPDATE) old
                   WHERE p.recon_id = old.recon_id AND old.status IN %s
                   RETURNING p.recon_id, old.status AS old_status)
               INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
               SELECT NULL, 'SUPERSEDED', 'reconciliation_item', recon_id::text, old_status, 'newer run' FROM up
               RETURNING log_id""",
            (recon_id, UNTOUCHED_STATUSES),
        )
        done = cur.fetchone() is not None
    conn.commit()
    return done


def title(item: dict) -> str:
    """One line for the task list, e.g. "Lebanon transactions: 3 rows not loaded (unknown currency,
    unknown channel)", or "Qatar transactions: no rows delivered"."""
    where = f"{item['source_country']} {item['source_table']}"
    if item.get("note"):
        return f"{where}: {item['note'][0].lower()}{item['note'][1:]}"
    n = item["rejected_rows"]
    reasons = [FLAG_WORDS.get(f, f.replace("_", " ").lower()) for f in (item.get("flags") or [])]
    return f"{where}: {n} row{'' if n == 1 else 's'} not loaded" + (f" ({', '.join(reasons)})" if reasons else "")


def process_variables(item: dict, rules: dict, due_days: int, today: date = None) -> dict:
    """Same variable names as the other reconciliation-task kind (recon_groups_db), so the Tasks
    screen, comments and audit keys work the same way."""
    today = today or date.today()
    cfo, _ = cfo_rule(item, rules)
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(item["recon_id"]),
        "flagLabel": FLAG_LABEL,
        "teamGroup": rules["owner_team"].lower(),
        "title": title(item),
        "severity": "HIGH" if cfo else "MEDIUM",
        "dueDate": (today + timedelta(days=1 if cfo else due_days)).isoformat(),
        "cfoRequired": cfo,
        **sent_back_variables(item),                       # a task reopened at run sign-off says so
    }


def record_started(conn, item: dict, process_instance_key: int, rules: dict) -> None:
    """Remember the process (so it's never started twice) and hand the item to the team, with
    whether the CFO must approve it whatever is decided."""
    cfo, reason = cfo_rule(item, rules)
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (RECORD_TYPE, SOURCE_TABLE, str(item["recon_id"]), FLAG_LABEL, process_instance_key),
        )
        cur.execute(
            """UPDATE pipeline_reconciliation SET status = 'WITH_TEAM', cfo_required = %s, cfo_reason = %s, title = %s
               WHERE recon_id = %s AND status = 'OPEN'""",
            (cfo, reason, title(item), item["recon_id"]),
        )
    conn.commit()
