"""Postgres side of the breach check (specs/breach-levels.md, client point 8): which level a KPI has
crossed, whether it has held for the limit's consecutive days, and one open breach per limit that
escalates rather than duplicates. Plain psycopg2, no Zeebe, so it's testable without Camunda.
"""
from datetime import date, timedelta

import psycopg2.extras

# limits.metric_name -> kpi_daily_summary column (the same mapping the backend's /kpi-summary/limits
# and the Tasks screen use). A limit whose metric isn't here is skipped, not guessed at.
KPI_COLUMN = {
    "capital_adequacy_ratio": "car_pct",
    "liquidity_coverage_ratio": "lcr_pct",
    "npl_ratio": "npl_ratio_pct",
    "dollarization_ratio": "dollarization_ratio_pct",
    "net_interest_margin": "nim_pct",
    "cost_to_income_ratio": "cost_to_income_pct",
    "return_on_equity": "roe_pct",
    "total_assets": "total_assets_usd",
}

LEVELS = ["EARLY_WARNING", "APPETITE", "REGULATORY"]          # least to most severe
TASK_LEVELS = {"APPETITE", "REGULATORY"}                       # early warning is a notification only


def _crossed(value: float, threshold, direction: str) -> bool:
    if threshold is None:
        return False
    return value < threshold if direction == "BELOW" else value > threshold


def level_for(limit: dict, value: float):
    """The most severe level this value crosses, or None."""
    if _crossed(value, limit["regulatory_value"], limit["direction"]):
        return "REGULATORY"
    if _crossed(value, limit["threshold_value"], limit["direction"]):
        return "APPETITE"
    if _crossed(value, limit["early_warning_value"], limit["direction"]):
        return "EARLY_WARNING"
    return None


def sustained_level(limit: dict, values: list):
    """The level held on every one of the last `consecutive_days` days (newest first in `values`):
    the least severe of those days' levels. None if a day is missing or wasn't in breach."""
    days = max(limit["consecutive_days"], 1)
    recent = values[:days]
    if len(recent) < days or any(v is None for v in recent):
        return None
    levels = [level_for(limit, v) for v in recent]
    if None in levels:
        return None
    return min(levels, key=LEVELS.index)


def _due(level: str, limit: dict, today: date):
    """Breaches that become tasks are due in the limit's resolution days; a regulatory one in half
    that (at least 1 day). Early warnings have no deadline."""
    if level not in TASK_LEVELS:
        return None
    days = limit["resolution_days"] if level == "APPETITE" else max(limit["resolution_days"] // 2, 1)
    return today + timedelta(days=days)


def evaluate(conn, today: date = None) -> list:
    """Checks every limit against the latest KPI days. New breach -> inserted (status OPEN, or
    WARNING for an early warning); an open breach at a lower level -> escalated in place (same
    breach, new level, new due date, audited); an early warning whose KPI has recovered -> CLEARED.
    Never a second open breach for the same limit.
    Returns [(action, metric_name, level)] for the log."""
    today = today or date.today()
    actions = []
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT * FROM limits ORDER BY limit_id")
        limits = cur.fetchall()
        longest = max([l["consecutive_days"] for l in limits] + [1])
        cur.execute("SELECT * FROM kpi_daily_summary ORDER BY calculation_date DESC LIMIT %s", (longest,))
        kpi_days = cur.fetchall()
        if not kpi_days:
            return actions

        for limit in limits:
            column = KPI_COLUMN.get(limit["metric_name"])
            if column is None:
                continue
            values = [day.get(column) for day in kpi_days]
            level = sustained_level(limit, values)
            cur.execute("SELECT breach_id, level, status FROM breaches WHERE limit_id = %s AND resolved_at IS NULL", (limit["limit_id"],))
            open_breach = cur.fetchone()
            if level is None:
                # Back inside the limits: an early warning (nobody works it as a task) clears
                # itself; a breach with a task stays open until a person resolves it.
                if open_breach and open_breach["status"] == "WARNING" and level_for(limit, values[0]) is None:
                    cur.execute("UPDATE breaches SET status = 'CLEARED', resolved_at = now() WHERE breach_id = %s",
                                (open_breach["breach_id"],))
                    actions.append(("CLEARED", limit["metric_name"], open_breach["level"]))
                continue
            status = "OPEN" if level in TASK_LEVELS else "WARNING"
            if open_breach is None:
                cur.execute(
                    """INSERT INTO breaches (limit_id, actual_value, level, status, due_date)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (limit["limit_id"], values[0], level, status, _due(level, limit, today)),
                )
                actions.append(("NEW", limit["metric_name"], level))
            elif LEVELS.index(level) > LEVELS.index(open_breach["level"]):
                cur.execute(
                    """UPDATE breaches SET level = %s, status = CASE WHEN status = 'WARNING' THEN %s ELSE status END,
                              actual_value = %s, due_date = %s
                       WHERE breach_id = %s""",
                    (level, status, values[0], _due(level, limit, today), open_breach["breach_id"]),
                )
                cur.execute(
                    """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
                       VALUES (NULL, 'ESCALATED', 'breach', %s, %s, %s)""",
                    (str(open_breach["breach_id"]), open_breach["level"], level),
                )
                actions.append(("ESCALATED", limit["metric_name"], level))
    conn.commit()
    return actions


def untracked(conn) -> list:
    """Breaches that need a task but don't have one: status OPEN (early warnings are WARNING and
    never become tasks) and no camunda_process_tracking row."""
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT b.breach_id, b.actual_value, b.level, b.due_date, l.metric_name, l.threshold_value,
                      l.regulatory_value, l.direction
               FROM breaches b JOIN limits l ON l.limit_id = b.limit_id
               WHERE b.status = 'OPEN' AND b.resolved_at IS NULL
                 AND NOT EXISTS (
                   SELECT 1 FROM camunda_process_tracking t
                   WHERE t.record_type = 'breach' AND t.source_table = 'breaches'
                     AND t.record_key = b.breach_id::text AND t.flag_label = l.metric_name)
               ORDER BY b.breach_id"""
        )
        return cur.fetchall()


def process_variables(b: dict) -> dict:
    line = b["regulatory_value"] if b["level"] == "REGULATORY" else b["threshold_value"]
    word = "regulatory limit" if b["level"] == "REGULATORY" else "internal limit"
    return {
        "recordType": "breach",
        "sourceTable": "breaches",
        "recordKey": str(b["breach_id"]),
        "flagLabel": b["metric_name"],
        "flagType": "FAULT",
        "flagCategory": "COMPLIANCE",
        "severity": "HIGH" if b["level"] == "REGULATORY" else "MEDIUM",
        "dueDate": b["due_date"].isoformat() if b["due_date"] else None,
        "description": f"{b['metric_name']} at {b['actual_value']:.2f} crossed the {word} of {line:.2f} ({b['direction']})",
    }


def record_tracking(conn, breach_id: int, metric_name: str, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES ('breach', 'breaches', %s, %s, %s)
               ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (str(breach_id), metric_name, process_instance_key),
        )
    conn.commit()
