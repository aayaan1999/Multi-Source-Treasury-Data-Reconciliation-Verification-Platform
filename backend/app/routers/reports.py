from fastapi import APIRouter, Depends, HTTPException, Response

from ..config import get_settings
from ..db import query, query_one
from ..reports.documents import build_pdf, build_xlsx, filename
from ..reports.form import SECTION_TITLES
from ..reports.validation import is_blocked, run_validation
from ..security import current_user

router = APIRouter(prefix="/reports", tags=["screen 3 - regulatory reporting"], dependencies=[Depends(current_user)])

INSTANCE_COLUMNS = """i.report_instance_id, d.report_id, d.name, d.frequency, i.period, i.status, i.due_date,
                      i.submitted_at, d.owner_department"""
INSTANCE_FROM = "FROM report_instances i JOIN report_definitions d ON d.report_id = i.report_id"
INSTANCE_SQL = f"SELECT {INSTANCE_COLUMNS} {INSTANCE_FROM}"


def _instance(report_id: int) -> dict:
    row = query_one(INSTANCE_SQL + " WHERE i.report_instance_id = %s", (report_id,))
    if row is None:
        raise HTTPException(404, "No such report")
    return row


def _lines(report_id: int) -> list:
    return query(
        """SELECT line_code, label, value, prior_value, explanation, section, display_order, line_kind, unit,
                  is_demo_input
           FROM report_line_items WHERE report_instance_id = %s ORDER BY display_order""",
        (report_id,),
    )


@router.get("")
def calendar():
    """The report calendar: one row per report instance. Days-left and urgency colouring are worked out in the browser
    (they depend on today's date), and `has_lines` says whether a full return exists to open."""
    return query(
        f"""SELECT {INSTANCE_COLUMNS},
                   EXISTS (SELECT 1 FROM report_line_items l
                           WHERE l.report_instance_id = i.report_instance_id) AS has_lines
            {INSTANCE_FROM} ORDER BY i.due_date, d.name"""
    )


@router.get("/{report_id}")
def open_report(report_id: int):
    report = _instance(report_id)
    lines = _lines(report_id)
    if not lines:
        return {"report": report, "available": False, "sections": [], "validation": [], "blocked": False, "comparison": []}

    by_code = {l["line_code"]: l["value"] for l in lines}
    rules = query(
        """SELECT rule_key, name, severity, message FROM validation_rules
           WHERE report_id = %s AND rule_key IS NOT NULL ORDER BY rule_id""",
        (report["report_id"],),
    )
    validation = run_validation(rules, by_code)

    sections = [
        {"section": s, "title": SECTION_TITLES.get(s, s), "lines": [l for l in lines if l["section"] == s]}
        for s in sorted({l["section"] for l in lines})
    ]
    comparison = []
    for l in lines:
        prior, current = l["prior_value"], l["value"]
        change = None if prior is None or current is None else current - prior
        pct = None if change is None or not prior else change / abs(prior) * 100
        comparison.append({"line_code": l["line_code"], "label": l["label"], "unit": l["unit"], "current": current,
                           "prior": prior, "change": change, "change_pct": pct,
                           "needs_explanation": pct is not None and abs(pct) > 10})
    return {"report": report, "available": True, "sections": sections, "validation": validation,
            "blocked": is_blocked(validation), "comparison": comparison}


@router.get("/{report_id}/drill/{line_code}")
def drill(report_id: int, line_code: str):
    """The single most important endpoint on the screen: how was this number arrived at?"""
    row = query_one(
        """SELECT a.line_code, l.label, l.value, l.unit, l.is_demo_input, a.formula_text, a.source_tables,
                  a.filters_applied, a.record_count, a.calculated_at, a.notes
           FROM calculation_audit a
           JOIN report_line_items l ON l.report_instance_id = a.report_instance_id AND l.line_code = a.line_code
           WHERE a.report_instance_id = %s AND a.line_code = %s
           ORDER BY a.calculated_at DESC LIMIT 1""",
        (report_id, line_code),
    )
    if row is None:
        raise HTTPException(404, "No calculation record for that line")
    row["detail_link"] = "/portfolio" if line_code == "B.1" else None
    return row


def _document(report_id: int):
    report = _instance(report_id)
    lines = _lines(report_id)
    if not lines:
        raise HTTPException(404, "This report has no figures to export yet")
    return report, lines


@router.post("/{report_id}/export/pdf")
def export_pdf(report_id: int):
    report, lines = _document(report_id)
    return Response(build_pdf(report, lines, get_settings().bank_name), media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename(report, "pdf")}"'})


@router.post("/{report_id}/export/excel")
def export_excel(report_id: int):
    report, lines = _document(report_id)
    audits = query(
        """SELECT line_code, formula_text, source_tables, filters_applied, record_count, calculated_at, notes
           FROM calculation_audit WHERE report_instance_id = %s ORDER BY line_code""",
        (report_id,),
    )
    order = {l["line_code"]: l["display_order"] for l in lines}
    audits.sort(key=lambda a: order.get(a["line_code"], 0))
    return Response(
        build_xlsx(report, lines, audits, get_settings().bank_name),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename(report, "xlsx")}"'},
    )
