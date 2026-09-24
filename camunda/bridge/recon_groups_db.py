"""Grouping core-system reconciliation breaks by cause (specs/reconciliation-groups.md, client point 1):
open breaks become groups - one task each, one decision for the whole group - except important
breaks (missing records, key fields, large amounts), which are always their own group. Plain
psycopg2, no Zeebe, so it's testable without Camunda.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

import psycopg2.extras

PROCESS_ID = "reconciliation-group-review"
RECORD_TYPE = "recon_group"
SOURCE_TABLE = "reconciliation_groups"
FLAG_LABEL = "RECON_GROUP"
DECISION_STATUS = {"ACCEPT": "ACCEPTED", "DISMISS": "DISMISSED", "CORRECT": "CORRECTED"}
ENTITY_LABEL = {"account": "Account", "customer": "Customer"}
MISMATCH_TEXT = {"MISSING_IN_CANONICAL": "missing in our data", "MISSING_IN_SOURCE": "missing in the source system"}


def settings(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM app_settings WHERE key IN ('recon.rules', 'task.due_days')")
        return dict(cur.fetchall())


def difference(b: dict):
    """Source minus ours, for numeric values; None for text."""
    try:
        return round(float(b["source_value"]) - float(b["canonical_value"]), 2)
    except (TypeError, ValueError):
        return None


def is_important(b: dict, rules: dict) -> bool:
    """Never grouped for a bulk decision (spec section 4): a missing record, a key field, or a big amount."""
    if b["mismatch_type"] != "VALUE_MISMATCH" or b["field_name"] in rules["important_fields"]:
        return True
    d = difference(b)
    return d is not None and abs(d) >= rules["important_amount"]


def _band(d: float, bands: list) -> str:
    size = abs(d)
    lower = 0
    for upper in bands:
        if size < upper:
            return f"{lower:,}-{upper:,}"
        lower = upper
    return f"{bands[-1]:,}+"


def pattern(b: dict, same_diff_counts: Counter, rules: dict) -> str:
    """What the breaks in a group have in common, in words: "+15.00" when many breaks differ by the
    same amount, else a size band; "missing in our data" for a missing record; the field for text."""
    if b["mismatch_type"] != "VALUE_MISMATCH":
        return MISMATCH_TEXT.get(b["mismatch_type"], b["mismatch_type"])
    d = difference(b)
    if d is None:
        return "different value"
    if same_diff_counts[(b["source_system"], b["entity_type"], b["field_name"], d)] >= rules["same_difference_min"]:
        return f"{d:+,.2f}"
    return f"difference {_band(d, rules['size_bands'])}"


def create_groups(conn, today: date = None) -> int:
    """Groups every OPEN break not yet in a group. Important and carved-out breaks get a group each;
    the rest share a group per source + record type + field + mismatch + pattern, split at
    max_group_size. Returns how many groups were created."""
    today = today or date.today()
    cfg = settings(conn)
    rules, due_days = cfg["recon.rules"], cfg["task.due_days"].get("RECON_GROUP", 3)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT exception_id, source_system, entity_type, entity_id, field_name, source_value, canonical_value,
                      mismatch_type, carved_out
               FROM reconciliation_exceptions WHERE status = 'OPEN' AND group_id IS NULL ORDER BY exception_id"""
        )
        breaks = cur.fetchall()
        same_diff = Counter(
            (b["source_system"], b["entity_type"], b["field_name"], difference(b))
            for b in breaks if difference(b) is not None and not is_important(b, rules)
        )
        groups = defaultdict(list)
        for b in breaks:
            important = is_important(b, rules)
            key = (b["source_system"], b["entity_type"], b["field_name"], b["mismatch_type"], pattern(b, same_diff, rules))
            if important or b["carved_out"]:
                key = key + (f"single:{b['exception_id']}",)
            groups[(key, important)].append(b)

        created = 0
        for (key, important), members in groups.items():
            for start in range(0, len(members), rules["max_group_size"]):
                chunk = members[start:start + rules["max_group_size"]]
                diffs = [d for d in (difference(b) for b in chunk) if d is not None]
                total_abs = sum(abs(d) for d in diffs)
                cur.execute(
                    """INSERT INTO reconciliation_groups (group_key, source_system, entity_type, field_name, mismatch_type,
                           pattern, important, break_count, total_difference, largest_difference,
                           requires_second_approval, team, due_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING group_id""",
                    ("|".join(str(k) for k in key), key[0], key[1], key[2], key[3], key[4], important, len(chunk),
                     round(sum(diffs), 2) if diffs else None, max((abs(d) for d in diffs), default=None),
                     len(chunk) > 1 and total_abs >= rules["second_approval_total"],
                     rules["owner_team"], today + timedelta(days=1 if important else due_days)),
                )
                group_id = cur.fetchone()["group_id"]
                cur.execute("UPDATE reconciliation_exceptions SET group_id = %s WHERE exception_id = ANY(%s)",
                            (group_id, [b["exception_id"] for b in chunk]))
                created += 1
    conn.commit()
    return created


def title(g: dict) -> str:
    """E.g. "Account balance +15.00 · 412 accounts · neon" or "Customer C0090 missing in our data · neon"."""
    entity = ENTITY_LABEL.get(g["entity_type"], g["entity_type"])
    field = f" {g['field_name']}" if g["field_name"] else ""
    count = f" · {g['break_count']} {g['entity_type']}s" if g["break_count"] > 1 else ""
    return f"{entity}{field} {g['pattern']}{count} · {g['source_system']}"


def fetch_unstarted(conn) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT * FROM reconciliation_groups WHERE status = 'PENDING' AND process_instance_key IS NULL
               ORDER BY important DESC, break_count DESC, group_id"""
        )
        return cur.fetchall()


def process_variables(g: dict) -> dict:
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(g["group_id"]),
        "flagLabel": FLAG_LABEL,
        "teamGroup": g["team"].lower(),                # candidate group of the review step
        "title": title(g),
        "severity": "HIGH" if g["important"] else "MEDIUM",
        "dueDate": g["due_date"].isoformat(),
        "requiresSecondApproval": g["requires_second_approval"],
    }


def record_started(conn, group_id: int, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE reconciliation_groups SET status = 'OPEN', process_instance_key = %s WHERE group_id = %s AND status = 'PENDING'",
                    (process_instance_key, group_id))
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (RECORD_TYPE, SOURCE_TABLE, str(group_id), FLAG_LABEL, process_instance_key),
        )
    conn.commit()


def decide(conn, group_id: int, decision: str, excluded_ids: list, decided_by: int, approved_by=None) -> None:
    """One decision for every open break in the group except the carve-outs, each with its own audit
    row; carve-outs leave the group and are regrouped on their own next poll. One transaction;
    idempotent for a retried job."""
    status = DECISION_STATUS[decision]
    excluded = [int(i) for i in (excluded_ids or [])]
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE reconciliation_groups SET status = 'CLOSED', decision = %s, decided_by = %s, approved_by = %s, closed_at = now()
               WHERE group_id = %s AND status <> 'CLOSED' RETURNING group_id""",
            (decision, decided_by, approved_by, group_id),
        )
        if cur.fetchone() is None:
            conn.rollback()
            return
        cur.execute(
            """UPDATE reconciliation_exceptions SET group_id = NULL, carved_out = true
               WHERE group_id = %s AND exception_id = ANY(%s) AND status = 'OPEN'""",
            (group_id, excluded),
        )
        cur.execute(
            """UPDATE reconciliation_exceptions SET status = %s, resolved_by = %s, resolved_at = now(),
                      resolution_note = %s
               WHERE group_id = %s AND status = 'OPEN'
               RETURNING entity_type, entity_id, mismatch_type, field_name""",
            (status, decided_by, f"Decided for group #{group_id}", group_id),
        )
        audit = [
            (decided_by, status, "reconciliation_exception",
             f"{t}:{e}:{m}" + (f":{f}" if f else ""), "OPEN", f"group #{group_id}")
            for t, e, m, f in cur.fetchall()
        ]
        if audit:
            cur.executemany(
                "INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value) VALUES (%s, %s, %s, %s, %s, %s)",
                audit,
            )
    conn.commit()
