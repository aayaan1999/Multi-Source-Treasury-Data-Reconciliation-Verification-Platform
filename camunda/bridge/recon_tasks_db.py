"""What the reconciliation-task process's service tasks do (specs/reconciliation-approvals.md), for both
task types: a pipeline gap (pipeline_reconciliation) and a group of core-system breaks
(reconciliation_groups).

    record_decision  the team's decision: checked, saved, and whether the CFO must approve it
    approve          the CFO's approval: never by the person who decided, only by the CFO or an admin
    send_back        the CFO sends the decision back to the team

Each returns the process variables its gateway reads, so a refused step goes back to the person with
the reason instead of failing the job. One transaction each, with audit rows; idempotent for a retried
job. Plain psycopg2, no Zeebe, so the backend tests exercise it against a real Postgres.
"""
from decimal import Decimal, InvalidOperation

import psycopg2.extras

import recon_groups_db
import reconciliation_db

DECISIONS = ("ACCEPT", "CORRECT", "DISMISS")
CFO_ROLES = ("approver", "admin")
PIPELINE, GROUP = reconciliation_db.RECORD_TYPE, recon_groups_db.RECORD_TYPE
# A break's entity -> the table a correction patches (Notebook 1 applies approved corrections by table,
# record key and field).
ENTITY_TABLE = {"account": "accounts", "customer": "customers"}


def _refused(**variables) -> dict:
    return variables


def user(cur, user_id):
    if user_id is None:
        return None
    cur.execute("SELECT u.user_id, u.name, r.name AS role FROM users u JOIN roles r ON r.role_id = u.role_id WHERE u.user_id = %s",
                (int(user_id),))
    return cur.fetchone()


def needs_cfo(cfo_required: bool, cfo_reason, decision: str):
    """The CFO approves an important task whatever the decision, and any data fix."""
    reasons = [cfo_reason] if cfo_required and cfo_reason else (["an important task"] if cfo_required else [])
    if decision == "CORRECT":
        reasons.append("a proposed data fix")
    return bool(reasons), "; ".join(reasons)


def plain_value(value):
    """'122098.1500' -> '122098.15', so a correction reads (and is applied) the way the value is stored here."""
    try:
        return format(Decimal(value).normalize(), "f")
    except (InvalidOperation, TypeError, ValueError):
        return value


def _audit(cur, user_id, action, object_type, object_id, old, new):
    cur.execute("INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value) VALUES (%s, %s, %s, %s, %s, %s)",
                (user_id, action, object_type, str(object_id), old, new))


def _finalize_group(cur, group_id: int, decision: str, decided_by: int, approved_by=None) -> None:
    """The decision takes effect: the group closes, every open break in it gets the decision (one audit
    row each), and its proposed fixes are approved."""
    cur.execute(
        """UPDATE reconciliation_groups SET status = 'CLOSED', closed_at = now(), approved_by = %s,
                  approved_at = CASE WHEN %s::int IS NULL THEN NULL ELSE now() END
           WHERE group_id = %s""",
        (approved_by, approved_by, group_id),
    )
    status = recon_groups_db.DECISION_STATUS[decision]
    cur.execute(
        """UPDATE reconciliation_exceptions SET status = %s, resolved_by = %s, resolved_at = now(), resolution_note = %s
           WHERE group_id = %s AND status = 'OPEN'
           RETURNING entity_type, entity_id, mismatch_type, field_name""",
        (status, decided_by, f"Decided for group #{group_id}", group_id),
    )
    for t, e, m, f in cur.fetchall():
        _audit(cur, decided_by, status, "reconciliation_exception", f"{t}:{e}:{m}" + (f":{f}" if f else ""), "OPEN", f"group #{group_id}")
    if approved_by is not None:
        cur.execute(
            """UPDATE reconciliation_corrections SET status = 'APPROVED', approved_by = %s, approved_at = now()
               WHERE group_id = %s AND status = 'PROPOSED' RETURNING source_table, record_key, field_name, old_value, new_value""",
            (approved_by, group_id),
        )
        for t, k, f, old, new in cur.fetchall():
            _audit(cur, approved_by, "CORRECTION_APPROVED", "reconciliation_correction", f"{t}:{k}:{f}", old, new)


# ---- the team's decision -------------------------------------------------------------------------

def record_decision(conn, record_type: str, key, decision: str, decided_by, excluded_ids=(), corrected_values=None) -> dict:
    """Checks and saves the team's decision. Returns decisionOk / decisionError, and needsCfo / cfoReason
    for the Important? gateway. corrected_values: for a group, the value the reviewer entered per break
    ({exception_id: value}); a break without one takes the source system's value."""
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            who = user(cur, decided_by)
            if who is None:
                return _refused(decisionOk=False, decisionError="The decision didn't say who made it. Reopen the task and decide again.")
            if who["role"] == "auditor":
                return _refused(decisionOk=False, decisionError="The Internal Auditor can look but not decide (specs/user-roles.md).")
            if decision not in DECISIONS:
                return _refused(decisionOk=False, decisionError="Pick Accept, Correct our data or Dismiss.")
            if record_type == PIPELINE:
                result = _decide_pipeline(cur, int(key), decision, who["user_id"])
            else:
                result = _decide_group(cur, int(key), decision, who["user_id"], excluded_ids or [], corrected_values or {})
        if result["decisionOk"]:
            conn.commit()
        else:
            conn.rollback()
        return result
    except Exception:
        conn.rollback()
        raise


def _decide_pipeline(cur, recon_id, decision, decided_by):
    cur.execute("SELECT * FROM pipeline_reconciliation WHERE recon_id = %s FOR UPDATE", (recon_id,))
    item = cur.fetchone()
    if item is None:
        return _refused(decisionOk=False, decisionError="This item no longer exists.")
    needs, reason = needs_cfo(item["cfo_required"], item["cfo_reason"], decision)
    ok = dict(decisionOk=True, decisionError="", needsCfo=needs, cfoReason=reason)
    if item["status"] in ("AWAITING_CFO", "DECIDED") and item["decision"] == decision and item["decided_by"] == decided_by:
        return ok                                               # a retried job: already saved
    if item["status"] != "WITH_TEAM":
        return _refused(decisionOk=False, decisionError=f"This item can't be decided now (it is {item['status'].lower().replace('_', ' ')}).")
    cur.execute("SELECT count(*) AS n FROM reconciliation_corrections WHERE recon_id = %s AND status = 'PROPOSED'", (recon_id,))
    proposed = cur.fetchone()["n"]
    if decision == "CORRECT" and not proposed:
        return _refused(decisionOk=False, decisionError="Enter at least one corrected value before choosing Correct our data.")
    if decision != "CORRECT" and proposed:
        cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE recon_id = %s AND status = 'PROPOSED'", (recon_id,))
    cur.execute(
        """UPDATE pipeline_reconciliation SET decision = %s, decided_by = %s, decided_at = now(), status = %s
           WHERE recon_id = %s""",
        (decision, decided_by, "AWAITING_CFO" if needs else "DECIDED", recon_id),
    )
    _audit(cur, decided_by, "DECIDED", "reconciliation_item", recon_id, "WITH_TEAM", decision + (" (CFO approval needed)" if needs else ""))
    return ok


def _is_number(value) -> bool:
    try:
        Decimal(str(value).replace(",", ""))
        return True
    except (InvalidOperation, TypeError, ValueError):
        return False


def fixed_values(kept: list, corrected_values: dict):
    """The value each kept break is fixed to: what the reviewer entered, else the source system's value.
    Returns ({exception_id: value}, None), or (None, why) when a value can't be used."""
    entered = {str(k): v for k, v in (corrected_values or {}).items()}
    out = {}
    for b in kept:
        raw = entered.get(str(b["exception_id"]), b["source_value"])
        value = "" if raw is None else str(raw).strip()
        if not value:
            return None, f"Enter the fixed value for {b['entity_type']} {b['entity_id']}."
        if _is_number(b["canonical_value"]):
            if not _is_number(value):
                return None, f"{b['field_name']} is a number: enter a number for {b['entity_type']} {b['entity_id']}."
            value = plain_value(value.replace(",", ""))
            if Decimal(value) == Decimal(str(b["canonical_value"]).replace(",", "")):
                return None, f"The fixed value for {b['entity_type']} {b['entity_id']} is the same as ours: change it, or leave the record out."
        elif value == b["canonical_value"]:
            return None, f"The fixed value for {b['entity_type']} {b['entity_id']} is the same as ours: change it, or leave the record out."
        out[b["exception_id"]] = value
    return out, None


def _decide_group(cur, group_id, decision, decided_by, excluded_ids, corrected_values):
    cur.execute("SELECT * FROM reconciliation_groups WHERE group_id = %s FOR UPDATE", (group_id,))
    g = cur.fetchone()
    if g is None:
        return _refused(decisionOk=False, decisionError="This group no longer exists.")
    needs, reason = needs_cfo(g["cfo_required"], g["cfo_reason"], decision)
    ok = dict(decisionOk=True, decisionError="", needsCfo=needs, cfoReason=reason)
    if g["status"] in ("AWAITING_CFO", "CLOSED") and g["decision"] == decision and g["decided_by"] == decided_by:
        return ok                                               # a retried job: already saved
    if g["status"] != "OPEN":
        return _refused(decisionOk=False, decisionError=f"This group can't be decided now (it is {g['status'].lower().replace('_', ' ')}).")
    cur.execute(
        """SELECT exception_id, entity_type, entity_id, field_name, source_value, canonical_value, mismatch_type
           FROM reconciliation_exceptions WHERE group_id = %s AND status = 'OPEN' ORDER BY exception_id""",
        (group_id,),
    )
    open_breaks = cur.fetchall()
    excluded = {int(i) for i in excluded_ids} & {b["exception_id"] for b in open_breaks}
    if open_breaks and len(excluded) >= len(open_breaks):
        return _refused(decisionOk=False, decisionError="Leave at least one break in the group, or it has nothing to decide.")
    kept = [b for b in open_breaks if b["exception_id"] not in excluded]
    if decision == "CORRECT":
        if any(b["mismatch_type"] != "VALUE_MISMATCH" for b in kept):
            return _refused(decisionOk=False, decisionError=(
                "A missing record can't be corrected here. Accept or dismiss it, and raise it with the team that owns the record."))
        if any(b["entity_type"] not in ENTITY_TABLE for b in kept):
            return _refused(decisionOk=False, decisionError="These records can't be corrected from here.")
        fixes, why = fixed_values(kept, corrected_values)
        if why:
            return _refused(decisionOk=False, decisionError=why)
    if excluded:
        # Left out: out of this group, grouped on their own at the next poll (same run).
        cur.execute("UPDATE reconciliation_exceptions SET group_id = NULL, carved_out = true WHERE exception_id = ANY(%s)", (list(excluded),))
    cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE group_id = %s AND status = 'PROPOSED'", (group_id,))
    if decision == "CORRECT":
        # "Our copy is wrong": the fix is the value the reviewer entered (the source system's by default),
        # applied by Notebook 1 once the CFO approves.
        for b in kept:
            cur.execute(
                """INSERT INTO reconciliation_corrections (group_id, source_table, record_key, field_name, old_value, new_value, entered_by)
                   VALUES (%s, %s, %s, %s, %s, %s, %s)""",
                (group_id, ENTITY_TABLE[b["entity_type"]], b["entity_id"], b["field_name"], b["canonical_value"],
                 fixes[b["exception_id"]], decided_by),
            )
    cur.execute(
        "UPDATE reconciliation_groups SET decision = %s, decided_by = %s, decided_at = now(), status = %s WHERE group_id = %s",
        (decision, decided_by, "AWAITING_CFO" if needs else "OPEN", group_id),
    )
    _audit(cur, decided_by, "DECIDED", "reconciliation_group", group_id, "OPEN",
           decision + (f", {len(excluded)} left out" if excluded else "") + (" (CFO approval needed)" if needs else ""))
    if not needs:
        _finalize_group(cur, group_id, decision, decided_by)
    return ok


# ---- the CFO's approval --------------------------------------------------------------------------

def approve(conn, record_type: str, key, approved_by) -> dict:
    """The CFO approves the team's decision. Refused (approvalOk false, approvalError) for the person who
    decided, or anyone but the CFO (approver) or an admin."""
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            table, id_col = ("pipeline_reconciliation", "recon_id") if record_type == PIPELINE else ("reconciliation_groups", "group_id")
            cur.execute(f"SELECT * FROM {table} WHERE {id_col} = %s FOR UPDATE", (int(key),))
            row = cur.fetchone()
            who = user(cur, approved_by)
            done = "APPROVED" if record_type == PIPELINE else "CLOSED"
            if row is None:
                result = _refused(approvalOk=False, approvalError="This task no longer exists.")
            elif row["status"] == done and row["approved_by"] is not None and who and row["approved_by"] == who["user_id"]:
                result = dict(approvalOk=True, approvalError="")        # a retried job: already approved
            elif row["status"] != "AWAITING_CFO":
                result = _refused(approvalOk=False, approvalError="There's nothing waiting for approval on this task.")
            elif who is None:
                result = _refused(approvalOk=False, approvalError="The approval didn't say who approved it. Approve again.")
            elif who["role"] not in CFO_ROLES:
                result = _refused(approvalOk=False, approvalError=f"Only the CFO or the Platform Administrator can approve; {who['name']} can't.")
            elif row["decided_by"] == who["user_id"]:
                result = _refused(approvalOk=False, approvalError=f"{who['name']} made this decision, so a different person has to approve it.")
            else:
                if record_type == PIPELINE:
                    cur.execute("UPDATE pipeline_reconciliation SET status = 'APPROVED', approved_by = %s, approved_at = now() WHERE recon_id = %s",
                                (who["user_id"], row["recon_id"]))
                    cur.execute(
                        """UPDATE reconciliation_corrections SET status = 'APPROVED', approved_by = %s, approved_at = now()
                           WHERE recon_id = %s AND status = 'PROPOSED' RETURNING source_table, record_key, field_name, old_value, new_value""",
                        (who["user_id"], row["recon_id"]),
                    )
                    fixes = cur.fetchall()
                    for c in fixes:
                        _audit(cur, who["user_id"], "CORRECTION_APPROVED", "reconciliation_correction",
                               f"{c['source_table']}:{c['record_key']}:{c['field_name']}", c["old_value"], c["new_value"])
                    _audit(cur, who["user_id"], "APPROVED", "reconciliation_item", row["recon_id"], row["decision"], f"{len(fixes)} correction(s)")
                else:
                    _finalize_group(cur, row["group_id"], row["decision"], row["decided_by"], who["user_id"])
                    _audit(cur, who["user_id"], "APPROVED", "reconciliation_group", row["group_id"], row["decision"], None)
                result = dict(approvalOk=True, approvalError="")
        if result["approvalOk"]:
            conn.commit()
        else:
            conn.rollback()
        return result
    except Exception:
        conn.rollback()
        raise


def send_back(conn, record_type: str, key, sent_back_by, note) -> dict:
    """The CFO sends the decision back to the team: it's undone (a group's generated fixes withdrawn;
    an item's proposed values kept for the team to change) and the team decides again."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        if record_type == PIPELINE:
            cur.execute(
                """UPDATE pipeline_reconciliation SET status = 'WITH_TEAM', decision = NULL, decided_by = NULL, decided_at = NULL
                   WHERE recon_id = %s AND status = 'AWAITING_CFO' RETURNING recon_id""",
                (int(key),),
            )
            object_type = "reconciliation_item"
        else:
            cur.execute(
                """UPDATE reconciliation_groups SET status = 'OPEN', decision = NULL, decided_by = NULL, decided_at = NULL
                   WHERE group_id = %s AND status = 'AWAITING_CFO' RETURNING group_id""",
                (int(key),),
            )
            if cur.fetchone() is not None:
                cur.execute("UPDATE reconciliation_corrections SET status = 'WITHDRAWN' WHERE group_id = %s AND status = 'PROPOSED'", (int(key),))
                _audit(cur, sent_back_by, "SENT_BACK", "reconciliation_group", key, "AWAITING_CFO", note)
            conn.commit()
            return {}
        if cur.fetchone() is not None:
            _audit(cur, sent_back_by, "SENT_BACK", object_type, key, "AWAITING_CFO", note)
    conn.commit()
    return {}
