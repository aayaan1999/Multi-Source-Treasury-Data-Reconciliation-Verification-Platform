"""Validation checks run on an open report before it can be approved.

Rules live in the `validation_rules` table (name, severity, failure message) so wording and severity can change without a
release; the *test* each rule performs is code, looked up by the rule's `rule_key`. A passing rule is green; a failing
COMMENT_REQUIRED rule is amber (needs a written explanation); a failing BLOCKING/PASS_REQUIRED rule is red and blocks
submission.
"""
from decimal import Decimal

from .form import FORM_CODES
from .formatting import money, percent

TOL_MONEY = Decimal("1")          # one currency unit: figures are stored to 4 decimals but shown whole
TOL_PCT = Decimal("0.005")        # half a hundredth of a percentage point
THIN_BUFFER_POINTS = Decimal("1")  # amber when the total capital ratio is within this many points of the minimum


def _v(lines: dict, code: str) -> Decimal:
    return Decimal(str(lines[code]))


def tier_total(lines):
    lhs, rhs = _v(lines, "A.5") + _v(lines, "A.8"), _v(lines, "A.9")
    if abs(lhs - rhs) <= TOL_MONEY:
        return True, f"Tier 1 ({money(lines['A.5'])}) + Tier 2 ({money(lines['A.8'])}) = total capital ({money(rhs)})"
    return False, f"Tier 1 + Tier 2 is {money(lhs)} but total capital (A.9) shows {money(rhs)}"


def required_fields(lines):
    missing = [c for c in FORM_CODES if lines.get(c) is None]
    if not missing:
        return True, f"All {len(FORM_CODES)} lines have a value"
    return False, "Missing values: " + ", ".join(missing)


def section_totals(lines):
    problems = []
    for total, parts in (("A.5", ("A.1", "A.2", "A.3", "A.4")), ("A.8", ("A.6", "A.7")), ("B.4", ("B.1", "B.2", "B.3"))):
        got = sum(_v(lines, p) for p in parts)
        if abs(got - _v(lines, total)) > TOL_MONEY:
            problems.append(f"{' + '.join(parts)} = {money(got)}, but {total} shows {money(lines[total])}")
    rwa = _v(lines, "B.4")
    for code, numerator in (("C.1", "A.5"), ("C.2", "A.9")):
        expected = _v(lines, numerator) / rwa * 100
        if abs(expected - _v(lines, code)) > TOL_PCT:
            problems.append(f"{code} shows {percent(lines[code])}, but {numerator} / B.4 is {percent(expected)}")
    surplus = _v(lines, "A.9") - _v(lines, "C.3") / 100 * rwa
    if abs(surplus - _v(lines, "C.4")) > TOL_MONEY:
        problems.append(f"C.4 shows {money(lines['C.4'])}, but A.9 less the minimum on B.4 is {money(surplus)}")
    if problems:
        return False, "; ".join(problems)
    return True, "Every section total and ratio agrees with its components"


def capital_buffer(lines):
    headroom = _v(lines, "C.2") - _v(lines, "C.3")
    if headroom >= THIN_BUFFER_POINTS:
        return True, f"Total capital ratio is {headroom:.2f} points above the regulatory minimum"
    if headroom < 0:
        return False, (f"Total capital ratio ({percent(lines['C.2'])}) is below the regulatory minimum "
                       f"({percent(lines['C.3'])}): a shortfall of {money(-_v(lines, 'C.4'))}. Explanation required")
    return False, (f"Total capital ratio is only {headroom:.2f} points above the regulatory minimum: "
                   f"a written explanation is required")


CHECKS = {
    "TIER_TOTAL": tier_total,
    "REQUIRED_FIELDS": required_fields,
    "SECTION_TOTALS": section_totals,
    "CAPITAL_BUFFER": capital_buffer,
}


def run_validation(rules: list, lines: dict) -> list:
    """rules: rows of validation_rules. lines: {line_code: value}. Returns one result per rule, in rule order."""
    results = []
    for rule in rules:
        check = CHECKS.get(rule["rule_key"])
        if check is None:
            results.append({"rule_key": rule["rule_key"], "name": rule["name"], "severity": rule["severity"],
                            "passed": False, "level": "warn",
                            "message": "No check is implemented for this rule, so it could not be evaluated"})
            continue
        try:
            passed, detail = check(lines)
        except (KeyError, ArithmeticError) as exc:   # a line is missing or B.4 is zero: report, don't crash
            passed, detail = False, f"Could not evaluate ({type(exc).__name__}): a required line is missing or zero"
        if passed:
            level = "pass"
        else:
            level = "warn" if rule["severity"] == "COMMENT_REQUIRED" else "fail"
        results.append({"rule_key": rule["rule_key"], "name": rule["name"], "severity": rule["severity"],
                        "passed": passed, "level": level, "message": detail})
    return results


def is_blocked(results: list) -> bool:
    return any(r["level"] == "fail" for r in results)
