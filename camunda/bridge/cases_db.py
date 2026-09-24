"""Postgres side of task cases (specs/task-cases.md, client point 6): group pending transaction flags
into one case per account + day + flag type, score severity, set a due date, and close a case with
one decision for all its flags.

Plain psycopg2, no Zeebe imports, so poll_worker.py and outcome_worker.py share it and the backend
tests can exercise it against a real Postgres.
"""
from collections import defaultdict
from datetime import date, timedelta

import psycopg2.extras

RECORD_TYPE = "fraud_case"
SOURCE_TABLE = "task_cases"
TYPE_LABEL = {"SUSPICIOUS": "Suspicious", "THRESHOLD": "Threshold", "OPERATIONAL": "Operational"}


def settings(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM app_settings WHERE key LIKE 'task.%'")
        return dict(cur.fetchall())


def severity(flag_type: str, flag_count: int, rule_count: int, cfg: dict) -> tuple:
    """(score, level) per app_settings['task.severity'] (spec section 3)."""
    score = cfg["base"].get(flag_type, 1)
    score += flag_count >= cfg["many_flags_at"]
    score += rule_count >= cfg["many_rules_at"]
    level = "HIGH" if score >= cfg["high_min"] else "MEDIUM" if score >= cfg["medium_min"] else "LOW"
    return int(score), level


def title(case: dict) -> str:
    """One line for the task list, e.g. "ACC005 · 9 Sep 2026 · 6 Suspicious flags"."""
    day = case["case_date"]
    day_text = f"{day.day} {day:%b %Y}" if hasattr(day, "strftime") else str(day)
    kind = TYPE_LABEL.get(case["flag_type"], case["flag_type"])
    return f"{case['account_id']} · {day_text} · {case['flag_count']} {kind} flag{'s' if case['flag_count'] != 1 else ''}"


def create_cases(conn, flag_category, today: date = None) -> int:
    """Groups every pending flag not yet in a case (and never given a task of its own) into new
    cases, one per account + day + flag type, with severity, team and due date. Low severity goes to
    the digest instead of becoming a task. Returns how many cases were created. `flag_category`
    is poll_worker's flag_type -> team function, so routing stays in one place."""
    today = today or date.today()
    cfg = settings(conn)
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT f.transaction_id, f.flag_label, f.flag_type, t.account_id, t.date
               FROM flagged_transactions f JOIN transactions t ON t.transaction_id = f.transaction_id
               WHERE f.status = 'PENDING_REVIEW'
                 AND NOT EXISTS (SELECT 1 FROM task_case_flags c
                                 WHERE c.transaction_id = f.transaction_id AND c.flag_label = f.flag_label)
                 AND NOT EXISTS (SELECT 1 FROM camunda_process_tracking k
                                 WHERE k.record_type = 'fraud' AND k.source_table = 'transactions'
                                   AND k.record_key = f.transaction_id AND k.flag_label = f.flag_label)
               ORDER BY t.account_id, t.date, f.flag_type, f.transaction_id, f.flag_label"""
        )
        groups = defaultdict(list)
        for flag in cur.fetchall():
            groups[(flag["account_id"], flag["date"], flag["flag_type"])].append(flag)

        for (account_id, day, flag_type), flags in groups.items():
            score, level = severity(flag_type, len(flags), len({f["flag_label"] for f in flags}), cfg["task.severity"])
            due = today + timedelta(days=cfg["task.due_days"][level])
            cur.execute(
                """INSERT INTO task_cases (account_id, case_date, flag_type, team, severity, severity_score,
                                           flag_count, due_date, status)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING case_id""",
                (account_id, day, flag_type, flag_category(flag_type, "transactions"), level, score, len(flags), due,
                 "DIGEST" if level == "LOW" else "PENDING"),
            )
            case_id = cur.fetchone()["case_id"]
            cur.executemany(
                "INSERT INTO task_case_flags (case_id, transaction_id, flag_label) VALUES (%s, %s, %s)",
                [(case_id, f["transaction_id"], f["flag_label"]) for f in flags],
            )
    conn.commit()
    return len(groups)


def fetch_unstarted(conn) -> list[dict]:
    """Cases waiting for a task: new High/Medium ones, and digest cases someone raised. Most severe
    first, then soonest due, so the most urgent work reaches the queue first."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT case_id, account_id, case_date, flag_type, team, severity, flag_count, due_date
               FROM task_cases WHERE status = 'PENDING' AND process_instance_key IS NULL
               ORDER BY CASE severity WHEN 'HIGH' THEN 0 WHEN 'MEDIUM' THEN 1 ELSE 2 END, due_date, case_id"""
        )
        return cur.fetchall()


def process_variables(case: dict) -> dict:
    """transaction-review's variables: flagCategory routes to the team like a single flag would."""
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(case["case_id"]),
        "flagLabel": case["flag_type"],
        "flagType": case["flag_type"],
        "flagCategory": case["team"],
        "title": title(case),
        "accountId": case["account_id"],
        "severity": case["severity"],
        "dueDate": case["due_date"].isoformat(),
        "description": f"{case['flag_count']} flag(s) on account {case['account_id']}",
    }


def record_started(conn, case_id: int, process_instance_key: int) -> None:
    """The case's task exists: remember it on the case and on each flag, so neither the case nor
    any of its flags is ever started again."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE task_cases SET status = 'OPEN', process_instance_key = %s WHERE case_id = %s AND status = 'PENDING'",
            (process_instance_key, case_id),
        )
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               SELECT 'fraud', 'transactions', transaction_id, flag_label, %s FROM task_case_flags WHERE case_id = %s
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (process_instance_key, case_id),
        )
    conn.commit()


def close_case(conn, case_id: int, outcome: str, reviewed_by: int) -> None:
    """One decision for every flag in the case: each flag's status and its own review_outcomes row,
    then the case is closed - all in one transaction. Idempotent: a retried job changes nothing."""
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE task_cases SET status = 'CLOSED', outcome = %s, closed_at = now() WHERE case_id = %s AND status <> 'CLOSED' RETURNING case_id",
            (outcome, case_id),
        )
        if cur.fetchone() is None:
            conn.rollback()
            return
        cur.execute(
            """UPDATE flagged_transactions f SET status = %s
               FROM task_case_flags c WHERE c.case_id = %s AND f.transaction_id = c.transaction_id AND f.flag_label = c.flag_label""",
            (outcome, case_id),
        )
        cur.execute(
            """INSERT INTO review_outcomes (record_type, source_table, record_key, outcome, corrected_value, reviewed_by)
               SELECT 'fraud', 'transactions', transaction_id, %s, NULL, %s FROM task_case_flags WHERE case_id = %s""",
            (outcome, reviewed_by, case_id),
        )
    conn.commit()
