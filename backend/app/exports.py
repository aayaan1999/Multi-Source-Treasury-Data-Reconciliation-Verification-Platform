"""Excel exports of what Screens 2 and 5 show (risk and retail teams "live in Excel"). One workbook per screen, one sheet
per table, built from exactly the rows the screen reads, so the file and the screen cannot disagree."""
import io
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HEADER_FILL = PatternFill("solid", fgColor="E9EDF3")


def _plain(value):
    """openpyxl can't store Decimal or date-times with time zones; numbers become floats."""
    return float(value) if isinstance(value, Decimal) else value


def _sheet(wb: Workbook, title: str, columns: list, rows: list, first: bool = False):
    """columns: [(key, header, number_format or None)]."""
    ws = wb.active if first else wb.create_sheet()
    ws.title = title[:31]
    ws.append([header for _, header, _ in columns])
    for cell in ws[1]:
        cell.font, cell.fill = Font(bold=True), HEADER_FILL
        cell.alignment = Alignment(wrap_text=True, vertical="top")
    for row in rows:
        ws.append([_plain(row.get(k)) for k, _, _ in columns])
    for idx, (_, header, fmt) in enumerate(columns, start=1):
        letter = get_column_letter(idx)
        width = max([len(str(header))] + [len(str(c.value)) for c in ws[letter][1:] if c.value is not None][:200]) + 2
        ws.column_dimensions[letter].width = min(max(width, 10), 48)
        if fmt:
            for cell in ws[letter][1:]:
                cell.number_format = fmt
    ws.freeze_panes = "A2"
    return ws


def _save(wb: Workbook) -> bytes:
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


USD = "#,##0"
PCT = "0.0"


def portfolio_workbook(data: dict) -> bytes:
    """data: the lists the Screen 2 endpoints return (see routers/portfolio.py)."""
    wb = Workbook()
    _sheet(wb, "IFRS 9 stages", [("stage", "Stage", None), ("loan_count", "Loans", "0"),
                                 ("outstanding_usd", "Outstanding (USD)", USD), ("provisions_usd", "Provisions (USD)", USD),
                                 ("coverage_pct", "Coverage %", PCT)], data["stages"], first=True)
    for dimension in ("product", "segment", "branch", "currency"):
        _sheet(wb, f"By {dimension}", [("dimension_value", dimension.title(), None),
                                       ("total_outstanding_usd", "Total loans (USD)", USD),
                                       ("bad_loan_outstanding_usd", "Bad loans (USD)", USD)], data["breakdown"][dimension])
    _sheet(wb, "Top exposures", [("customer_id", "Customer", None), ("customer_name", "Name", None),
                                 ("outstanding_usd", "Outstanding (USD)", USD), ("product", "Product", None),
                                 ("days_past_due", "Days past due", "0"), ("pct_of_capital", "% of capital", "0.00")],
           data["top_exposures"])
    _sheet(wb, "Ageing", [("bucket", "Bucket", None), ("outstanding_usd", "Outstanding (USD)", USD),
                          ("pct_of_book", "% of book", PCT)], data["ageing"])
    _sheet(wb, "LTV", [("bucket", "LTV bucket", None), ("outstanding_usd", "Outstanding (USD)", USD),
                       ("loan_count", "Loans", "0")], data["ltv"])
    return _save(wb)


def performance_workbook(data: dict) -> bytes:
    wb = Workbook()
    _sheet(wb, "Branches", [("branch_id", "Branch", None), ("branch_name", "Name", None), ("region", "Region", None),
                            ("deposits_usd", "Deposits (USD)", USD), ("loans_usd", "Loans (USD)", USD),
                            ("revenue_usd", "Revenue (USD)", USD), ("cost_usd", "Cost (USD)", USD),
                            ("profit_usd", "Profit (USD)", USD), ("cost_to_income_pct", "Cost-to-income %", PCT),
                            ("staff_count", "Staff", "0"), ("profit_per_staff_usd", "Profit per staff (USD)", USD)],
           data["branches"], first=True)
    _sheet(wb, "Regions", [("region", "Region", None), ("branches", "Branches", "0"), ("revenue_usd", "Revenue (USD)", USD),
                           ("cost_usd", "Cost (USD)", USD), ("profit_usd", "Profit (USD)", USD)], data["regions"])
    _sheet(wb, "Segments", [("segment", "Segment", None), ("customer_count", "Customers", "0"),
                            ("deposits_usd", "Deposits (USD)", USD), ("loans_usd", "Loans (USD)", USD),
                            ("revenue_usd", "Revenue (USD)", USD), ("bad_loans_usd", "Bad loans (USD)", USD),
                            ("profit_usd", "Profit, cost allocated proportionally (USD)", USD),
                            ("revenue_per_customer_usd", "Revenue per customer (USD)", USD)], data["segments"])
    _sheet(wb, "Products", [("product", "Product", None), ("outstanding_usd", "Outstanding (USD)", USD),
                            ("avg_interest_rate", "Avg rate %", "0.00"), ("interest_income_usd", "Interest income (USD)", USD),
                            ("npl_pct", "NPL %", PCT), ("net_contribution_usd", "Net contribution (USD)", USD)],
           data["products"])
    _sheet(wb, "Channels", [("channel", "Channel", None), ("transaction_count", "Transactions", "0"),
                            ("share_pct", "Share %", PCT)], data["channels"])
    return _save(wb)
