"""Builds the Capital Adequacy return for one report instance from the database, writing every line to
`report_line_items` and a matching row to `calculation_audit` (the drill-to-source record).

Real inputs: `capital_positions` (Tier 1, Tier 2, RWA for the latest month with a usable RWA), the `limits` row for the
regulatory minimum, and, as a cross-check on B.1 only, the loan book (`loan_breakdown_by_dimension`) weighted by
`risk_weights`. Everything else is either arithmetic on those or a flagged demo input (see form.py).
"""
from datetime import datetime, timezone
from decimal import Decimal

import psycopg2.extras

from .form import ALLOCATION, DEFAULT_MINIMUM_PCT, FORM, allocate
from .formatting import money

LIMIT_METRIC = "capital_adequacy_ratio"
DEMO_NOTE = ("Demo input. The bank-wide schema has no capital-component data, so this figure is the real total "
             "split in the proportions of the source document's worked example. Confirm with Finance before filing.")


def _pct(weight: Decimal) -> str:
    """35.00 -> '35', 17.50 -> '17.5' (the database stores weights with two decimals)."""
    return f"{weight:f}".rstrip("0").rstrip(".") if "." in f"{weight:f}" else f"{weight:f}"


def _loan_level_rwa(cur):
    """Credit RWA implied by the loans actually in the database: latest product totals (USD) x risk weight."""
    cur.execute(
        """SELECT dimension_value AS product, total_outstanding_usd AS outstanding
           FROM loan_breakdown_by_dimension
           WHERE dimension_type = 'product'
             AND calculation_date = (SELECT max(calculation_date) FROM loan_breakdown_by_dimension)"""
    )
    products = cur.fetchall()
    cur.execute("SELECT product, weight_pct FROM risk_weights WHERE risk_rating = '*'")
    weights = {r["product"]: Decimal(r["weight_pct"]) for r in cur.fetchall()}
    cur.execute(
        "SELECT coalesce(sum(loan_count), 0) AS n FROM loan_stage_summary "
        "WHERE calculation_date = (SELECT max(calculation_date) FROM loan_stage_summary)"
    )
    loans = int(cur.fetchone()["n"])
    rwa = Decimal(0)
    used = []
    for p in products:
        weight = weights.get(p["product"], Decimal(100))
        rwa += Decimal(str(p["outstanding"] or 0)) * weight / 100
        used.append(f"{p['product']} {_pct(weight)}%" + ("" if p["product"] in weights else " (default)"))
    return rwa, loans, used


def build(cur, instance_id: int, now: datetime | None = None) -> dict:
    """(Re)builds the return for `instance_id`. `cur` must be a RealDictCursor. Returns {line_code: value}."""
    now = now or datetime.now(timezone.utc)

    cur.execute(
        """SELECT month, tier1_capital, tier2_capital, risk_weighted_assets FROM capital_positions
           WHERE month IS NOT NULL AND risk_weighted_assets > 0 ORDER BY month DESC LIMIT 1"""
    )
    cap = cur.fetchone()
    if cap is None:
        raise ValueError("capital_positions has no row with a usable risk_weighted_assets: nothing to report on")
    month = cap["month"]
    tier1, tier2, rwa = (Decimal(cap[k]) for k in ("tier1_capital", "tier2_capital", "risk_weighted_assets"))

    # The regulatory minimum (specs/breach-levels.md: limits has early warning / internal appetite /
    # regulatory levels); a limit without a regulatory level falls back to its threshold.
    cur.execute("SELECT COALESCE(regulatory_value, threshold_value) AS minimum FROM limits WHERE metric_name = %s", (LIMIT_METRIC,))
    limit_row = cur.fetchone()
    minimum = Decimal(str(limit_row["minimum"])) if limit_row else DEFAULT_MINIMUM_PCT

    values = {"A.5": tier1, "A.8": tier2, "B.4": rwa}
    for total_code, weights in ALLOCATION.items():
        values.update(allocate(values[total_code], weights))
    values["A.9"] = values["A.5"] + values["A.8"]
    values["C.1"] = values["A.5"] / rwa * 100
    values["C.2"] = values["A.9"] / rwa * 100
    values["C.3"] = minimum
    values["C.4"] = values["A.9"] - minimum / 100 * rwa
    q4 = Decimal("0.0001")
    values = {code: v.quantize(q4) for code, v in values.items()}

    loan_rwa, loan_count, weights_used = _loan_level_rwa(cur)
    coverage = (loan_rwa / values["B.1"] * 100) if values["B.1"] else Decimal(0)

    src_cap = f"capital_positions row for month {month} (latest month with a usable RWA)"
    audit = {  # line_code -> (formula, source_tables, filters, record_count, notes)
        "A.1": ("A.5 x 150 / 207 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.2": ("A.5 x 45 / 207 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.3": ("A.5 x 20 / 207 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.4": ("A.5 x -8 / 207 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.5": ("capital_positions.tier1_capital", ["capital_positions"], src_cap, 1,
                "Real figure from the source table."),
        "A.6": ("A.8 x 30 / 39 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.7": ("A.8 x 9 / 39 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "A.8": ("capital_positions.tier2_capital", ["capital_positions"], src_cap, 1,
                "Real figure from the source table."),
        "A.9": ("A.5 + A.8", ["capital_positions"], src_cap, 1, None),
        "B.1": ("B.4 x 1650 / 1985 (proportional split)", ["capital_positions", "loan_breakdown_by_dimension",
                                                           "loan_stage_summary", "risk_weights"], src_cap, loan_count,
                DEMO_NOTE + (f" Cross-check from the loan book: {loan_count} loans weighted by risk_weights "
                             f"({', '.join(weights_used) or 'none'}) give a credit RWA of {money(loan_rwa)}, "
                             f"only {'less than 0.01' if coverage < Decimal('0.01') else f'{coverage:.2f}'}% of this line. "
                             f"The remainder is not backed by loan-level data "
                             f"in this database.")),
        "B.2": ("B.4 x 120 / 1985 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "B.3": ("B.4 x 215 / 1985 (proportional split)", ["capital_positions"], src_cap, 1, DEMO_NOTE),
        "B.4": ("capital_positions.risk_weighted_assets", ["capital_positions"], src_cap, 1,
                "Real figure from the source table."),
        "C.1": ("A.5 / B.4 x 100", ["capital_positions"], src_cap, 1, None),
        "C.2": ("A.9 / B.4 x 100", ["capital_positions"], src_cap, 1, None),
        "C.3": (f"limits.regulatory_value (else threshold_value) where metric_name = '{LIMIT_METRIC}'", ["limits"],
                "metric_name = " + LIMIT_METRIC, 1 if limit_row else 0,
                None if limit_row else f"No `limits` row for {LIMIT_METRIC}; the default of {DEFAULT_MINIMUM_PCT}% was used."),
        "C.4": ("A.9 - C.3 / 100 x B.4", ["capital_positions", "limits"], src_cap, 1, None),
    }

    cur.execute("DELETE FROM calculation_audit WHERE report_instance_id = %s", (instance_id,))
    cur.execute("DELETE FROM report_line_items WHERE report_instance_id = %s", (instance_id,))
    for order, (code, section, label, kind, unit) in enumerate(FORM, start=1):
        cur.execute(
            """INSERT INTO report_line_items
                   (report_instance_id, line_code, label, value, section, display_order, line_kind, unit, is_demo_input)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (instance_id, code, label, values[code], section, order, kind, unit, DEMO_NOTE in (audit[code][4] or "")),
        )
        formula, tables, filters, count, notes = audit[code]
        cur.execute(
            """INSERT INTO calculation_audit
                   (report_instance_id, line_code, formula_text, source_tables, filters_applied, record_count,
                    calculated_at, notes)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
            (instance_id, code, formula, tables, filters, count, now, notes),
        )
    return values
