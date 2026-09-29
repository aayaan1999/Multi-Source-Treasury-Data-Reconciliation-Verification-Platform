"""Ask a Question on Reports (specs/ask-a-question.md, CHT-1..5).

POST /ask turns a typed question into one approved, read-only query and returns its table; the
model only classifies the question (app/ask/llm.py), plain code reads exact values from the text
(app/ask/extract.py), and every call is audited. POST /ask/export re-runs the query for Excel.
GET / DELETE /ask/history read and clear the user's own saved answers (kept across logins).
"""
import time
from collections import defaultdict, deque
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from openpyxl import Workbook
from pydantic import BaseModel, Field

from ..ask import llm, service
from ..exports import _save, _sheet
from ..security import current_user

router = APIRouter(prefix="/ask", tags=["ask a question"], dependencies=[Depends(current_user)])

RATE_LIMIT = 10          # questions per user per minute (section 7)
_recent: dict = defaultdict(deque)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
NUMBER_FORMATS = {"usd": "#,##0", "pct": "0.0", "count": "#,##0", "number": "#,##0.00"}


class AskRequest(BaseModel):
    question: str = Field("", max_length=300)
    query: Optional[str] = Field(None, max_length=40)
    filters: Optional[dict] = None
    history_id: Optional[int] = None      # a chip edit on a saved answer replaces it in the history


class ExportRequest(BaseModel):
    question: str = Field("", max_length=300)
    query: str = Field(..., max_length=40)
    filters: dict = {}


def _rate_limit(user_id: int) -> None:
    now, window = time.monotonic(), _recent[user_id]
    while window and now - window[0] > 60:
        window.popleft()
    if len(window) >= RATE_LIMIT:
        raise HTTPException(429, "Too many questions in a minute - wait a moment and try again")
    window.append(now)


@router.post("")
def ask(body: AskRequest, user: dict = Depends(current_user)):
    question = body.question.strip()
    if body.query is None and not question:
        raise HTTPException(422, "Type a question")
    _rate_limit(user["user_id"])
    return service.ask(user, question, body.query, body.filters, history_id=body.history_id)


@router.get("/history")
def history(limit: int = Query(10, ge=1, le=service.PAGE_MAX), before: Optional[int] = None,
            user: dict = Depends(current_user)):
    if before is None:
        llm.warm_up()              # the Ask a question tab just opened: load the model before the first question
    return service.history(user, limit, before)


@router.get("/context")
def context(user: dict = Depends(current_user)):
    """The assistant's side panel: which data it reads, how fresh it is, and this user's scope."""
    return service.context(user)


@router.delete("/history")
def clear_history(user: dict = Depends(current_user)):
    return {"cleared": service.clear_history(user)}


@router.post("/export")
def export(body: ExportRequest, user: dict = Depends(current_user)):
    entry, filters, ran = service.export_rows(user, body.query, body.filters, body.question.strip())
    wb = Workbook()
    columns = [(c["key"], c["label"] + (" (USD)" if c["unit"] == "usd" else " %" if c["unit"] == "pct" else ""),
                NUMBER_FORMATS.get(c["unit"])) for c in ran["columns"]]
    _sheet(wb, entry.label, columns, ran["rows"], first=True)
    about = [
        {"item": "Question", "value": body.question.strip() or "(chosen from the filters)"},
        *({"item": chip["label"], "value": chip["text"]} for chip in service.chips(entry.id, filters)),
        {"item": "Source table", "value": ran["source"]["table"]},
        {"item": "Data as of", "value": ran["source"]["as_of"]},
        {"item": "Exported", "value": datetime.now().strftime("%Y-%m-%d %H:%M")},
        {"item": "Exported by", "value": user["name"]},
        *({"item": "Note", "value": note} for note in ran["notes"]),
    ]
    _sheet(wb, "About this answer", [("item", "Item", None), ("value", "Value", None)], about)
    name = f"ask_{entry.id}_{ran['source']['as_of']}.xlsx"
    return Response(_save(wb), media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{name}"'})
