"""One place that turns a stored figure into the text printed on the form, so the screen, the PDF and the Excel file
can never disagree about how a number reads."""
from decimal import ROUND_HALF_UP, Decimal


def _dec(value) -> Decimal:
    return value if isinstance(value, Decimal) else Decimal(str(value))


def money(value) -> str:
    """Whole currency units, thousands separators, negatives in parentheses: (8,000,000)."""
    if value is None:
        return ""
    whole = _dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP)
    text = f"{abs(whole):,}"
    return f"({text})" if whole < 0 else text


def percent(value) -> str:
    if value is None:
        return ""
    return f"{_dec(value).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}%"


def line_text(unit: str, value) -> str:
    return percent(value) if unit == "percent" else money(value)
