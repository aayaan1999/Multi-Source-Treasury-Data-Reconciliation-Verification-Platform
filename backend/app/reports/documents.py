"""PDF and Excel renderings of a report. Both read the same rows and use the same formatter (formatting.py), so the
two files show identical figures. The PDF follows the regulator-form layout: bank name, period, sections A/B/C with line
codes, page numbers, and signature blocks."""
import io
import re
from datetime import datetime
from decimal import Decimal

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .form import SECTION_TITLES
from .formatting import line_text

STATUS_LABELS = {"NOT_STARTED": "Not started", "DRAFT": "Draft", "UNDER_REVIEW": "Under review",
                 "APPROVED": "Approved", "SUBMITTED": "Submitted"}


def filename(report: dict, extension: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9]+", "_", f"{report['name']} {report['period']}").strip("_")
    return f"{stem}.{extension}"


def _sections(lines: list) -> list:
    out = []
    for section in sorted({l["section"] for l in lines}):
        out.append((section, SECTION_TITLES.get(section, section), [l for l in lines if l["section"] == section]))
    return out


# ------------------------------------------------------------------------------------------------ PDF
class _NumberedCanvas(canvas.Canvas):
    """Two-pass canvas so each page can say 'Page x of y'."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_pages = []

    def showPage(self):
        self._saved_pages.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        total = len(self._saved_pages)
        for state in self._saved_pages:
            self.__dict__.update(state)
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawRightString(A4[0] - 18 * mm, 10 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def build_pdf(report: dict, lines: list, bank_name: str) -> bytes:
    styles = getSampleStyleSheet()
    title = ParagraphStyle("t", parent=styles["Title"], fontSize=17, leading=21, alignment=0, spaceAfter=2)
    meta = ParagraphStyle("m", parent=styles["Normal"], fontSize=9, textColor=colors.HexColor("#444444"))
    note = ParagraphStyle("n", parent=styles["Normal"], fontSize=8, textColor=colors.HexColor("#555555"), leading=10)
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm, topMargin=16 * mm,
                            bottomMargin=18 * mm, title=f"{report['name']} {report['period']}", author=bank_name)

    story = [
        Paragraph(bank_name, ParagraphStyle("b", parent=styles["Normal"], fontSize=11, leading=14,
                                            textColor=colors.HexColor("#222222"))),
        Paragraph(f"{report['name']} Return", title),
        Paragraph(f"Period: {report['period']} &nbsp;&nbsp;|&nbsp;&nbsp; Status: "
                  f"{STATUS_LABELS.get(report['status'], report['status'])} &nbsp;&nbsp;|&nbsp;&nbsp; "
                  f"Generated: {datetime.now().strftime('%d %b %Y %H:%M')}", meta),
        Spacer(1, 6 * mm),
    ]
    has_demo = False
    for section, heading, rows in _sections(lines):
        data = [[f"SECTION {section} — {heading}", "", ""]]
        bold_rows = []
        for l in rows:
            text = line_text(l["unit"], l["value"])
            if l["is_demo_input"]:
                text += "*"
                has_demo = True
            data.append([l["line_code"], l["label"], text])
            if l["line_kind"] in ("subtotal", "total"):
                bold_rows.append(len(data) - 1)
        table = Table(data, colWidths=[16 * mm, 92 * mm, 60 * mm])
        style = [
            ("SPAN", (0, 0), (-1, 0)), ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 10),
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#e9edf3")),
            ("FONT", (0, 1), (-1, -1), "Helvetica", 9.5), ("ALIGN", (2, 1), (2, -1), "RIGHT"),
            ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
            ("LINEBELOW", (0, 1), (-1, -1), 0.25, colors.HexColor("#d5d9df")),
        ]
        for r in bold_rows:
            style += [("FONT", (0, r), (-1, r), "Helvetica-Bold", 9.5), ("LINEABOVE", (2, r), (2, r), 0.8, colors.black)]
        table.setStyle(TableStyle(style))
        story += [table, Spacer(1, 6 * mm)]

    if has_demo:
        story.append(Paragraph("* Demo input: this figure is not derivable from the bank's source data and is shown "
                               "in the proportions of a worked example. Confirm before filing.", note))
    story += [Spacer(1, 14 * mm)]
    sign = Table([["Prepared by", "Reviewed by", "Approved by"],
                  ["\n\n______________________", "\n\n______________________", "\n\n______________________"],
                  ["Name / Date", "Name / Date", "Name / Date"]], colWidths=[56 * mm] * 3)
    sign.setStyle(TableStyle([("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 9), ("FONT", (0, 1), (-1, -1), "Helvetica", 9),
                              ("TEXTCOLOR", (0, 2), (-1, 2), colors.HexColor("#666666"))]))
    story.append(sign)
    doc.build(story, canvasmaker=_NumberedCanvas)
    return buf.getvalue()


# ------------------------------------------------------------------------------------------------ Excel
def build_xlsx(report: dict, lines: list, audits: list, bank_name: str) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Return"
    bold = Font(bold=True)
    ws["A1"], ws["A1"].font = bank_name, Font(bold=True, size=13)
    ws["A2"], ws["A2"].font = f"{report['name']} Return", Font(bold=True, size=15)
    ws["A3"] = f"Period: {report['period']}    Status: {STATUS_LABELS.get(report['status'], report['status'])}"
    ws.append([])
    ws.append(["Line", "Description", "Value", "Note"])
    for cell in ws[5]:
        cell.font, cell.fill = bold, PatternFill("solid", fgColor="E9EDF3")
    top = Border(top=Side(style="thin"))
    for section, heading, rows in _sections(lines):
        ws.append([f"SECTION {section}", heading])
        ws.cell(ws.max_row, 1).font = ws.cell(ws.max_row, 2).font = bold
        for l in rows:
            ws.append([l["line_code"], l["label"], None, "Demo input" if l["is_demo_input"] else None])
            row = ws.max_row
            value = ws.cell(row, 3)
            number = None if l["value"] is None else float(Decimal(str(l["value"])))
            value.value = number
            value.number_format = '0.00"%"' if l["unit"] == "percent" else "#,##0;(#,##0)"
            value.alignment = Alignment(horizontal="right")
            if l["line_kind"] in ("subtotal", "total"):
                for c in range(1, 4):
                    ws.cell(row, c).font = bold
                value.border = top
    for col, width in zip("ABCD", (12, 34, 22, 14)):
        ws.column_dimensions[col].width = width

    src = wb.create_sheet("Sources")
    src.append(["Line", "Formula", "Source tables", "Filters", "Records", "Calculated at", "Notes"])
    for cell in src[1]:
        cell.font = bold
    for a in audits:
        src.append([a["line_code"], a["formula_text"], ", ".join(a["source_tables"]), a["filters_applied"],
                    a["record_count"], a["calculated_at"].strftime("%Y-%m-%d %H:%M") if a["calculated_at"] else None,
                    a["notes"]])
    for col, width in zip("ABCDEFG", (8, 46, 42, 46, 9, 18, 90)):
        src.column_dimensions[col].width = width
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()
