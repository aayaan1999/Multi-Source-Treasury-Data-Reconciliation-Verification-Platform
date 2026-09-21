"""Creates (or refreshes) the demo data behind Screen 3, Regulatory Reporting. Safe to run repeatedly.

    cd backend
    $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
    python seed_reports.py

Needs the migration in db/migrations/ applied first, and the pipeline to have loaded `capital_positions` (the return's
totals come from it). It writes:
  * the five report definitions, risk weights, the regulatory-minimum limit and four validation rules;
  * a report calendar of example rows, with due dates set relative to today so the urgency colours show;
  * the full Capital Adequacy return for the current quarter (every line plus its calculation_audit record).
The example calendar rows other than Capital Adequacy have no figures: only that template is built.
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import psycopg2
import psycopg2.extras

from app.reports import capital_adequacy

DEFINITIONS = [  # name, frequency, due_day_rule, owner_department
    ("Capital Adequacy", "Quarterly", "15 days after quarter end", "Finance"),
    ("Liquidity Coverage", "Monthly", "10 days after month end", "Treasury"),
    ("Credit Classification", "Quarterly", "20 days after quarter end", "Risk"),
    ("Large Exposures", "Quarterly", "20 days after quarter end", "Risk"),
    ("FX Position", "Monthly", "8 days after month end", "Treasury"),
]

RISK_WEIGHTS = [("Mortgage", 35), ("Personal", 75), ("SME", 100), ("Corporate", 100)]

RULES = [  # rule_key, name, severity, failure message, expression (documentation of the check)
    ("REQUIRED_FIELDS", "All required fields completed", "BLOCKING",
     "One or more lines have no value", "every line A.1-C.4 has a value"),
    ("SECTION_TOTALS", "Section totals equal the sum of their line items", "BLOCKING",
     "A section total does not equal its components", "A.5=A.1..A.4; A.8=A.6+A.7; B.4=B.1..B.3; C.1, C.2, C.4 recomputed"),
    ("TIER_TOTAL", "Tier 1 + Tier 2 equals total capital", "BLOCKING",
     "Tier 1 + Tier 2 does not equal total capital", "A.5 + A.8 = A.9"),
    ("CAPITAL_BUFFER", "Capital ratio comfortably above the regulatory minimum", "COMMENT_REQUIRED",
     "Capital ratio is close to the minimum: explanation required", "C.2 - C.3 >= 1 point"),
]


def _quarter(d: date) -> str:
    return f"Q{(d.month - 1) // 3 + 1} {d.year}"


def _month(d: date) -> str:
    return d.strftime("%b %Y")


def _previous_month(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


def _previous_quarter(d: date) -> date:
    first_of_quarter = d.replace(month=3 * ((d.month - 1) // 3) + 1, day=1)
    return first_of_quarter - timedelta(days=1)


def seed(cur, today: date | None = None) -> dict:
    """cur must be a RealDictCursor. Returns {'capital_adequacy_instance': id, 'instances': n}."""
    today = today or date.today()
    ids = {}
    for name, frequency, rule, department in DEFINITIONS:
        cur.execute(
            """INSERT INTO report_definitions (name, regulator, frequency, due_day_rule, owner_department, template_format)
               VALUES (%s, 'Central bank', %s, %s, %s, %s)
               ON CONFLICT (name) DO UPDATE SET frequency = EXCLUDED.frequency, due_day_rule = EXCLUDED.due_day_rule,
                   owner_department = EXCLUDED.owner_department, template_format = EXCLUDED.template_format
               RETURNING report_id""",
            (name, frequency, rule, department, "capital_adequacy" if name == "Capital Adequacy" else None),
        )
        ids[name] = cur.fetchone()["report_id"]

    for product, weight in RISK_WEIGHTS:
        cur.execute(
            """INSERT INTO risk_weights (product, risk_rating, weight_pct) VALUES (%s, '*', %s)
               ON CONFLICT (product, risk_rating) DO UPDATE SET weight_pct = EXCLUDED.weight_pct""",
            (product, weight),
        )
    cur.execute(
        """INSERT INTO limits (metric_name, threshold_value, direction, resolution_days)
           VALUES (%s, 12, 'BELOW', 30)
           ON CONFLICT (metric_name) DO UPDATE SET threshold_value = EXCLUDED.threshold_value""",
        (capital_adequacy.LIMIT_METRIC,),
    )
    for key, name, severity, message, expression in RULES:
        cur.execute(
            """INSERT INTO validation_rules (report_id, rule_key, name, severity, message, expression)
               VALUES (%s, %s, %s, %s, %s, %s)
               ON CONFLICT (report_id, rule_key) DO UPDATE SET name = EXCLUDED.name, severity = EXCLUDED.severity,
                   message = EXCLUDED.message, expression = EXCLUDED.expression""",
            (ids["Capital Adequacy"], key, name, severity, message, expression),
        )

    last_month, last_quarter = _previous_month(today), _previous_quarter(today)
    instances = [  # report, period, status, due in N days from today
        ("Capital Adequacy", _quarter(today), "DRAFT", 24),
        ("Liquidity Coverage", _month(today), "UNDER_REVIEW", 19),
        ("Credit Classification", _quarter(today), "NOT_STARTED", 29),
        ("Large Exposures", _quarter(today), "APPROVED", 29),
        ("FX Position", _month(today), "SUBMITTED", 17),
        ("Liquidity Coverage", _month(last_month), "DRAFT", 3),            # unsubmitted, < 5 days: red
        ("Credit Classification", _quarter(last_quarter), "UNDER_REVIEW", 8),  # unsubmitted, < 10 days: amber
        ("FX Position", _month(last_month), "APPROVED", -2),               # unsubmitted and past due: red
    ]
    instance_ids = {}
    for name, period, status, due_in in instances:
        submitted = datetime.now(timezone.utc) if status == "SUBMITTED" else None
        cur.execute(
            """INSERT INTO report_instances (report_id, period, status, due_date, submitted_at)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (report_id, period) DO UPDATE SET status = EXCLUDED.status, due_date = EXCLUDED.due_date,
                   submitted_at = EXCLUDED.submitted_at
               RETURNING report_instance_id""",
            (ids[name], period, status, today + timedelta(days=due_in), submitted),
        )
        instance_ids[(name, period)] = cur.fetchone()["report_instance_id"]

    instance = instance_ids[("Capital Adequacy", _quarter(today))]
    capital_adequacy.build(cur, instance)
    return {"capital_adequacy_instance": instance, "instances": len(instances)}


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL first (see this file's docstring).")
    conn = psycopg2.connect(url, connect_timeout=45)
    try:
        with conn, conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            result = seed(cur)
    finally:
        conn.close()
    print(f"Demo report data ready: {result['instances']} calendar rows; Capital Adequacy return built "
          f"(report instance {result['capital_adequacy_instance']}).")
