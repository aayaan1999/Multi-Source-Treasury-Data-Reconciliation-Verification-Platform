"""Grouping core-system reconciliation breaks by cause (specs/reconciliation-groups.md, client point 1):
open breaks become groups - one task each, one decision for the whole group - except important
breaks (missing records, key fields, large amounts), which are always their own group - unless one
comparison finds mass_missing_min or more records missing the same way at once: that is a wrong or partial
file, not that many separate problems, so they become one "check the file" group for the CFO. Each group
runs on reconciliation-task (specs/reconciliation-approvals.md): the team decides, and the CFO must
approve an important group, or one whose differences add up to a large amount. Deciding, approving
and sending back live in recon_tasks_db, shared with pipeline gaps. Plain psycopg2, no Zeebe, so
it's testable without Camunda.
"""
from collections import Counter, defaultdict
from datetime import date, timedelta

import psycopg2.extras

from sent_back import sent_back_variables

PROCESS_ID = "reconciliation-task"
RECORD_TYPE = "recon_group"
SOURCE_TABLE = "reconciliation_groups"
FLAG_LABEL = "RECON_GROUP"
DECISION_STATUS = {"ACCEPT": "ACCEPTED", "DISMISS": "DISMISSED", "CORRECT": "CORRECTED"}
ENTITY_LABEL = {"account": "Account", "customer": "Customer"}
MISMATCH_TEXT = {"MISSING_IN_CANONICAL": "missing in our data", "MISSING_IN_SOURCE": "missing in the source system"}
# The systems we compare with, as a sentence names them.
SYSTEM_NAME = {"neon": "core banking", "salesforce": "the CRM"}
# This many records missing the same way in one pass is a file problem (recon.rules can override it).
MASS_MISSING_MIN = 20
MASS = "mass"


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


def cfo_rule(chunk: list, important: bool, rules: dict):
    """Whether the CFO must approve this group whatever the team decides, and why: an important break
    (a missing record, a key field, a big difference), or a bulk group whose differences add up to
    important_amount or more."""
    if important:
        b = chunk[0]
        if b["mismatch_type"] != "VALUE_MISMATCH" and len(chunk) > 1:
            return True, f"{len(chunk)} missing records at once (check the file that was loaded)"
        if b["mismatch_type"] != "VALUE_MISMATCH":
            return True, "a missing record"
        if b["field_name"] in rules["important_fields"]:
            return True, f"a key field ({b['field_name']})"
        return True, f"a difference of {abs(difference(b)):,.2f}"
    total_abs = sum(abs(d) for d in (difference(b) for b in chunk) if d is not None)
    if total_abs >= rules["important_amount"]:
        return True, f"a total difference of {total_abs:,.2f}"
    return False, None


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
    max_group_size. Records missing the same way mass_missing_min times or more share one group, whole.
    Returns how many groups were created."""
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
        missing_way = lambda b: (b["source_system"], b["entity_type"], b["mismatch_type"])  # noqa: E731
        missing = Counter(missing_way(b) for b in breaks if b["mismatch_type"] != "VALUE_MISMATCH" and not b["carved_out"])
        mass_min = rules.get("mass_missing_min", MASS_MISSING_MIN)
        groups = defaultdict(list)
        for b in breaks:
            important = is_important(b, rules)
            key = (b["source_system"], b["entity_type"], b["field_name"], b["mismatch_type"], pattern(b, same_diff, rules))
            if b["mismatch_type"] != "VALUE_MISMATCH" and not b["carved_out"] and missing[missing_way(b)] >= mass_min:
                key = key + (MASS,)
            elif important or b["carved_out"]:
                key = key + (f"single:{b['exception_id']}",)
            groups[(key, important)].append(b)

        created = 0
        for (key, important), members in groups.items():
            size = len(members) if key[-1] == MASS else rules["max_group_size"]
            for start in range(0, len(members), size):
                chunk = members[start:start + size]
                diffs = [d for d in (difference(b) for b in chunk) if d is not None]
                cfo, reason = cfo_rule(chunk, important, rules)
                cur.execute(
                    """INSERT INTO reconciliation_groups (group_key, source_system, entity_type, field_name, mismatch_type,
                           pattern, important, break_count, total_difference, largest_difference,
                           requires_second_approval, cfo_required, cfo_reason, team, due_date)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING group_id""",
                    ("|".join(str(k) for k in key), key[0], key[1], key[2], key[3], key[4], important, len(chunk),
                     round(sum(diffs), 2) if diffs else None, max((abs(d) for d in diffs), default=None),
                     cfo, cfo, reason, rules["owner_team"], today + timedelta(days=1 if cfo else due_days)),
                )
                group_id = cur.fetchone()["group_id"]
                cur.execute("UPDATE reconciliation_exceptions SET group_id = %s WHERE exception_id = ANY(%s)",
                            (group_id, [b["exception_id"] for b in chunk]))
                created += 1
    conn.commit()
    return created


def breaks_of(conn, group_id: int) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT exception_id, source_system, entity_type, entity_id, field_name, source_value, canonical_value,
                      mismatch_type, status
               FROM reconciliation_exceptions WHERE group_id = %s ORDER BY entity_id""",
            (group_id,),
        )
        return cur.fetchall()


def title(g: dict, breaks: list) -> str:
    """One line for the task list that says what's wrong, e.g. "4 accounts: balance 15.00 higher in core
    banking", 'Customer CN0051: segment is "SME" in core banking, "Retail" here', "Customer CNCRM01: in
    the CRM but missing from our data"."""
    system = SYSTEM_NAME.get(g["source_system"], g["source_system"])
    entity = ENTITY_LABEL.get(g["entity_type"], g["entity_type"].title())
    n = len(breaks) or g["break_count"]
    one = breaks[0] if n == 1 and breaks else None
    who = f"{entity} {one['entity_id']}" if one else f"{n} {entity.lower()}s"
    field = g["field_name"]
    check = " - check the file that was loaded" if (g.get("group_key") or "").endswith(f"|{MASS}") else ""
    if g["mismatch_type"] == "MISSING_IN_CANONICAL":
        return f"{who}: in {system} but missing from our data{check}"
    if g["mismatch_type"] == "MISSING_IN_SOURCE":
        return f"{who}: in our data but missing from {system}{check}"
    d = difference(one) if one else None
    if one and d is not None:
        return f"{who}: {field} {abs(d):,.2f} {'higher' if d > 0 else 'lower'} in {system}"
    if one:
        return f'{who}: {field} is "{one["source_value"]}" in {system}, "{one["canonical_value"]}" here'
    if g["pattern"][:1] in "+-":
        amount = float(g["pattern"].replace(",", ""))
        return f"{who}: {field} {abs(amount):,.2f} {'higher' if amount > 0 else 'lower'} in {system}"
    if g["pattern"].startswith("difference "):
        return f"{who}: {field} differs from {system} by {g['pattern'][len('difference '):]}"
    return f"{who}: {field} differs from {system}"


def fetch_unstarted(conn) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT g.*, u.name AS sent_back_by_name FROM reconciliation_groups g LEFT JOIN users u ON u.user_id = g.sent_back_by
               WHERE g.status = 'PENDING' AND g.process_instance_key IS NULL
               ORDER BY g.important DESC, g.break_count DESC, g.group_id"""
        )
        return cur.fetchall()


def process_variables(g: dict, breaks: list) -> dict:
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(g["group_id"]),
        "flagLabel": FLAG_LABEL,
        "teamGroup": g["team"].lower(),                # candidate group of the review step
        "title": title(g, breaks),
        "severity": "HIGH" if g["cfo_required"] else "MEDIUM",
        "dueDate": g["due_date"].isoformat(),
        "cfoRequired": g["cfo_required"],
        **sent_back_variables(g),                          # a task reopened at run sign-off says so
    }


def record_started(conn, group_id: int, process_instance_key: int, task_title: str = None) -> None:
    """The group's task is with the team. A group sent back at run sign-off gets a new process, so the
    tracking row takes the new key."""
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE reconciliation_groups SET status = 'OPEN', process_instance_key = %s, title = COALESCE(%s, title)
               WHERE group_id = %s AND status = 'PENDING'""",
            (process_instance_key, task_title, group_id),
        )
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO UPDATE SET process_instance_key = EXCLUDED.process_instance_key""",
            (RECORD_TYPE, SOURCE_TABLE, str(group_id), FLAG_LABEL, process_instance_key),
        )
    conn.commit()
