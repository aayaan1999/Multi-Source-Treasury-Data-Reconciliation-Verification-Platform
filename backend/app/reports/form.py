"""The Capital Adequacy return, laid out as the source document's worked example (sections A, B, C).

Only the totals (A.5, A.8, B.4) exist in the bank-wide schema (`capital_positions`). The component lines
(A.1-A.4, A.6-A.7, B.1-B.3) do not, so they are DEMO INPUTS: the real total split in the proportions of the source
document's worked example. They are flagged as such everywhere they appear (screen, PDF, Excel, drill panel).
"""
from decimal import ROUND_HALF_UP, Decimal

SECTION_TITLES = {"A": "CAPITAL", "B": "RISK WEIGHTED ASSETS", "C": "RATIOS"}

# (line_code, section, label, line_kind, unit)
FORM = [
    ("A.1", "A", "Paid-up capital", "input", "currency"),
    ("A.2", "A", "Retained earnings", "input", "currency"),
    ("A.3", "A", "Reserves", "input", "currency"),
    ("A.4", "A", "Deductions", "input", "currency"),
    ("A.5", "A", "TIER 1 CAPITAL", "subtotal", "currency"),
    ("A.6", "A", "Subordinated debt", "input", "currency"),
    ("A.7", "A", "General provisions", "input", "currency"),
    ("A.8", "A", "TIER 2 CAPITAL", "subtotal", "currency"),
    ("A.9", "A", "TOTAL CAPITAL", "total", "currency"),
    ("B.1", "B", "Credit risk", "input", "currency"),
    ("B.2", "B", "Market risk", "input", "currency"),
    ("B.3", "B", "Operational risk", "input", "currency"),
    ("B.4", "B", "TOTAL RWA", "total", "currency"),
    ("C.1", "C", "Tier 1 ratio", "ratio", "percent"),
    ("C.2", "C", "Total capital ratio", "ratio", "percent"),
    ("C.3", "C", "Regulatory minimum", "ratio", "percent"),
    ("C.4", "C", "Surplus / (Shortfall)", "ratio", "currency"),
]
FORM_CODES = [code for code, *_ in FORM]

# Proportions from the source document's worked example (A.5 = 207m, A.8 = 39m, B.4 = 1,985m).
ALLOCATION = {
    "A.5": {"A.1": 150, "A.2": 45, "A.3": 20, "A.4": -8},
    "A.8": {"A.6": 30, "A.7": 9},
    "B.4": {"B.1": 1650, "B.2": 120, "B.3": 215},
}

DEFAULT_MINIMUM_PCT = Decimal("12")


def whole(value: Decimal) -> Decimal:
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def allocate(total: Decimal, weights: dict) -> dict:
    """Splits `total` across lines in proportion to `weights`, in whole currency units that add back up to `total`
    exactly (any rounding remainder goes to the largest line)."""
    weight_sum = sum(Decimal(w) for w in weights.values())
    parts = {code: whole(total * Decimal(w) / weight_sum) for code, w in weights.items()}
    largest = max(weights, key=lambda c: abs(weights[c]))
    parts[largest] += total - sum(parts.values())
    return parts
