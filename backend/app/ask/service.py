"""Steps 3-5 of specs/ask-a-question.md: merge the model's classification with the values read from
the text, validate against the catalogue, run the approved query, audit.

The merge rules (section 6.3) are the safety net for a wrong model answer: named values, dates and
"top N" come only from the text; the model's metric is used only when the text names none.
"""
import json
import time
from datetime import date
from typing import Optional

from fastapi import HTTPException

from ..db import write
from . import llm, vocab
from .catalogue import ENTRIES, EXAMPLES, METRIC_FALLBACKS, NoData
from .extract import Extracted, Period, extract

LIST_FILTERS = ("countries", "regions", "branches", "segments", "products", "stages", "tables")
FILTER_LABELS = {"metric": "Measure", "dimension": "Split by", "order": "Order", "top_n": "Show", "period": "Period",
                 "countries": "Country", "regions": "Region", "branches": "Branch", "segments": "Segment",
                 "products": "Product", "stages": "Stage", "tables": "Table", "status": "Status", "view": "View"}
MODEL_SORT = {"best": "good", "worst": "bad", "highest": "high", "lowest": "low"}
STATUS_TEXT = {"open": "Open only", "closed": "Closed only", "all": "Open and closed"}
VIEW_TEXT = {"table": "Per table", "flag": "Per check"}
MAX_OPTIONS = 6


# ---- merge (section 6.3) ------------------------------------------------------------------------------
def _entry_metric(entry_id: str, key: Optional[str]) -> Optional[str]:
    if not key:
        return None
    key = METRIC_FALLBACKS.get(entry_id, {}).get(key, key)
    return key if key in ENTRIES[entry_id].metrics else None


def _order(word: Optional[str], metric: Optional[str]) -> str:
    """high/low are literal; good/bad depend on whether more of the metric is better (section 6.4)."""
    better_high = vocab.METRICS[metric].higher_is_better if metric else None
    if word == "low" or (word == "good" and better_high is False) or (word == "bad" and better_high is not False):
        return "asc"
    return "desc"


def merge(model: dict, ex: Extracted) -> dict:
    """-> {"status": "answer"|"clarify"|"unsupported", "query", "filters", "ignored", "clarify"}."""
    entry_id = model.get("query") if model.get("query") in ENTRIES else None
    if entry_id is None:
        return {"status": "unsupported"}

    # A bank-wide KPI asked "in Lebanon" is really a country question, where the measure exists per country.
    if entry_id == "kpi_value" and ex.countries:
        metric = next((m for m in ex.metrics + [model.get("metric")] if _entry_metric("country_breakdown", m)), None)
        if metric or not ex.metrics:
            entry_id = "country_breakdown"
    entry = ENTRIES[entry_id]
    filters, ignored = {}, []

    text_metrics = [m for m in (_entry_metric(entry_id, k) for k in ex.metrics) if m]
    if text_metrics:
        filters["metric"] = text_metrics[0]
    elif ex.metrics and entry.metrics:
        names = ", ".join(vocab.METRICS[k].label for k in ex.metrics)
        return _clarify_metric(entry_id, {}, f"{names} isn't available in “{entry.label}”. Which measure should I show?")
    elif _entry_metric(entry_id, model.get("metric")):
        filters["metric"] = _entry_metric(entry_id, model.get("metric"))
    if entry.metric_required and "metric" not in filters:
        return _clarify_metric(entry_id, {}, f"Which measure should {entry.label.lower()} use?")

    if "dimension" in entry.filters:
        dimension = ex.dimension or (model.get("dimension") if model.get("dimension") in vocab.DIMENSIONS else None)
        if not dimension:
            return {"status": "clarify", "query": entry_id, "clarify": {
                "question": "How should the loan book be split?",
                "options": [{"label": label, "query": entry_id, "filters": {"dimension": key}}
                            for key, label in vocab.DIMENSIONS.items()]}}
        filters["dimension"] = dimension

    if ex.period is not None:
        if "period" in entry.filters:
            filters.update(date_from=ex.period.date_from.isoformat(), date_to=ex.period.date_to.isoformat(),
                           period_label=ex.period.label)
        else:
            ignored.append(ex.period.label)
    names = vocab.names()
    branch_names = {b["id"]: b["name"] for b in names["branches"]}
    for key in LIST_FILTERS:
        values = getattr(ex, key)
        if not values:
            continue
        if key in entry.filters:
            filters[key] = list(values)
        elif key in ("countries", "regions", "branches", "stages"):
            # Reported back so the user sees what wasn't applied. Segment, product and table words are
            # often just part of the wording ("loans by country"), so those are dropped quietly.
            ignored += [branch_names.get(v, v) if key == "branches" else (f"Stage {v}" if key == "stages" else v)
                        for v in values]
    if ex.top_n and "top_n" in entry.filters:
        filters["top_n"] = min(ex.top_n, 500)
    if "order" in entry.filters and filters.get("metric"):
        filters["order"] = _order(ex.sort_word or MODEL_SORT.get(model.get("sort")), filters["metric"])
    if "status" in entry.filters and ex.status:
        filters["status"] = ex.status
    if "view" in entry.filters and ex.by_flag:
        filters["view"] = "flag"
    return {"status": "answer", "query": entry_id, "filters": filters, "ignored": ignored}


def _clarify_metric(entry_id: str, base: dict, question: str) -> dict:
    options = [{"label": vocab.METRICS[k].label, "query": entry_id, "filters": {**base, "metric": k}}
               for k in list(ENTRIES[entry_id].metrics)[:MAX_OPTIONS]]
    return {"status": "clarify", "query": entry_id, "clarify": {"question": question, "options": options}}


# ---- validation of filters sent back by the panel (chip edits, clarify buttons) -----------------------
def validate(entry_id: str, filters: dict) -> dict:
    """The panel may send a query + filters instead of a question; they are checked as strictly as a
    model answer. Anything unknown is a 422, never passed to SQL."""
    if entry_id not in ENTRIES:
        raise HTTPException(422, "Unknown question type")
    entry = ENTRIES[entry_id]
    allowed = (set(entry.filters) - {"period"}) | {"metric"}
    if "period" in entry.filters:
        allowed |= {"date_from", "date_to", "period_label"}
    unknown = set(filters) - allowed
    if unknown:
        raise HTTPException(422, f"Not a filter for this question: {', '.join(sorted(unknown))}")
    clean = {}

    def bad(name):
        raise HTTPException(422, f"Invalid value for {name}")

    if filters.get("metric") is not None:
        if filters["metric"] not in entry.metrics:
            bad("metric")
        clean["metric"] = filters["metric"]
    if entry.metric_required and "metric" not in clean:
        bad("metric")
    if "dimension" in entry.filters:
        if filters.get("dimension") not in vocab.DIMENSIONS:
            bad("dimension")
        clean["dimension"] = filters["dimension"]
    if filters.get("order") is not None:
        if filters["order"] not in ("asc", "desc"):
            bad("order")
        clean["order"] = filters["order"]
    if filters.get("top_n") is not None:
        if not isinstance(filters["top_n"], int) or isinstance(filters["top_n"], bool) or not 1 <= filters["top_n"] <= 500:
            bad("top_n")
        clean["top_n"] = filters["top_n"]
    if filters.get("date_from") or filters.get("date_to"):
        try:
            start, end = date.fromisoformat(filters["date_from"]), date.fromisoformat(filters["date_to"])
        except (KeyError, TypeError, ValueError):
            bad("period")
        if start > end:
            bad("period")
        clean.update(date_from=start.isoformat(), date_to=end.isoformat(),
                     period_label=str(filters.get("period_label") or f"{start.isoformat()} to {end.isoformat()}")[:60])
    names = vocab.names()
    known = {"countries": set(vocab.COUNTRIES), "regions": set(names["regions"]),
             "branches": {b["id"] for b in names["branches"]}, "segments": set(names["segments"]),
             "products": set(names["products"]), "stages": {1, 2, 3}, "tables": set(vocab.SOURCE_TABLES)}
    for key in LIST_FILTERS:
        if filters.get(key):
            values = filters[key]
            if not isinstance(values, list) or len(values) > 50 or any(v not in known[key] for v in values):
                bad(key)
            clean[key] = values
    if filters.get("status") is not None:
        if filters["status"] not in STATUS_TEXT:
            bad("status")
        clean["status"] = filters["status"]
    if filters.get("view") is not None:
        if filters["view"] not in VIEW_TEXT:
            bad("view")
        clean["view"] = filters["view"]
    return clean


# ---- run + describe -------------------------------------------------------------------------------
def _runtime(filters: dict) -> dict:
    f = dict(filters)
    if f.get("date_from"):
        f["period"] = Period(date.fromisoformat(f["date_from"]), date.fromisoformat(f["date_to"]), f.get("period_label", ""))
    return f


def _fmt_day(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    d = date.fromisoformat(iso) if isinstance(iso, str) else iso
    return f"{d.day} {d.strftime('%b')} {d.year}"


def chips(entry_id: str, filters: dict) -> list:
    """The "What I understood" chips (section 8): each removable, some changeable from a short list."""
    entry, names = ENTRIES[entry_id], vocab.names()
    branch_names = {b["id"]: b["name"] for b in names["branches"]}
    out = []

    def add(key, text, removable=True, options=None, value=None):
        out.append({"key": key, "label": FILTER_LABELS[key], "text": text, "value": value if value is not None else filters.get(key),
                    "removable": removable, "options": options or []})

    if entry.metrics:
        # Changed from the list; "All measures" is offered only where the question works without one.
        options = ([] if entry.metric_required else [{"value": "", "text": "All measures"}]) + \
                  [{"value": k, "text": vocab.METRICS[k].label} for k in entry.metrics]
        add("metric", vocab.METRICS[filters["metric"]].label if filters.get("metric") else "All measures",
            removable=False, value=filters.get("metric") or "", options=options)
    if filters.get("dimension"):
        add("dimension", vocab.DIMENSIONS[filters["dimension"]], removable=False,
            options=[{"value": k, "text": v} for k, v in vocab.DIMENSIONS.items()])
    if filters.get("order"):
        add("order", "Highest first" if filters["order"] == "desc" else "Lowest first", removable=False,
            options=[{"value": "desc", "text": "Highest first"}, {"value": "asc", "text": "Lowest first"}])
    if filters.get("top_n"):
        add("top_n", f"Top {filters['top_n']}")
    if filters.get("date_from"):
        add("period", filters.get("period_label") or f"{filters['date_from']} to {filters['date_to']}",
            value={"date_from": filters["date_from"], "date_to": filters["date_to"]})
    elif "period" in entry.filters:
        add("period", "Latest", removable=False, value="")
    for key in LIST_FILTERS:
        if filters.get(key):
            shown = [branch_names.get(v, v) if key == "branches" else (f"Stage {v}" if key == "stages" else str(v))
                     for v in filters[key]]
            add(key, ", ".join(shown))
    if "status" in entry.filters:
        status = filters.get("status") or "open"
        add("status", STATUS_TEXT[status], removable=False, value=status,
            options=[{"value": k, "text": v} for k, v in STATUS_TEXT.items()])
    if "view" in entry.filters:
        view = filters.get("view") or "table"
        add("view", VIEW_TEXT[view], removable=False, value=view,
            options=[{"value": k, "text": v} for k, v in VIEW_TEXT.items()])
    return out


def execute(entry_id: str, filters: dict) -> dict:
    """Runs the approved query. Missing period data becomes a clarify with the range that exists."""
    entry = ENTRIES[entry_id]
    try:
        columns, rows, as_of, notes = entry.run(_runtime(filters))
    except NoData as e:
        if e.first is None:
            return {"status": "clarify", "query": entry_id, "clarify": {
                "question": f"There is no data for “{entry.label}” yet - the pipeline hasn't loaded it.", "options": []}}
        latest = {k: v for k, v in filters.items() if k not in ("date_from", "date_to", "period_label")}
        return {"status": "clarify", "query": entry_id, "clarify": {
            "question": f"No data for {filters.get('period_label') or 'that period'}. "
                        f"Data available: {_fmt_day(e.first.isoformat())} – {_fmt_day(e.last.isoformat())}.",
            "options": [{"label": f"Use the latest ({_fmt_day(e.last.isoformat())})", "query": entry_id, "filters": latest}]}}
    return {"status": "answer", "query": entry_id, "columns": columns, "rows": rows,
            "source": {"table": entry.source, "as_of": as_of}, "notes": notes}


def _audit(user: dict, action: str, object_id: str, details: dict) -> Optional[int]:
    row = write(
        """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
           VALUES (%s, %s, 'ask', %s, NULL, %s) RETURNING log_id""",
        (user["user_id"], action, object_id, json.dumps(details, default=str)),
    )
    return row["log_id"] if row else None


def _check_role(entry_id: str, user: dict) -> None:
    if user["role"] not in ENTRIES[entry_id].roles:
        raise HTTPException(403, "Your role can't run this question")


def ask(user: dict, question: str, entry_id: Optional[str] = None, filters: Optional[dict] = None,
        today: Optional[date] = None) -> dict:
    """POST /ask. With entry_id + filters (a clarify button or chip edit) the model isn't called."""
    started = time.monotonic()
    model_raw, ignored = None, []
    if entry_id is not None:
        result = {"status": "answer", "query": entry_id, "filters": validate(entry_id, filters or {})}
    else:
        try:
            model_raw = llm.classify(question)
        except llm.Unavailable as e:
            _audit(user, "ASK_QUESTION", "unavailable", {"question": question, "status": "unavailable", "error": str(e),
                                                          "model_name": llm.model_name()})
            raise HTTPException(503, "Ask a question isn't available right now - the model server isn't running.")
        result = merge(model_raw, extract(question, today or date.today(), vocab.names()))
        ignored = result.get("ignored", [])

    response = {"status": result["status"], "question": question, "examples": EXAMPLES, "ignored": ignored}
    if result["status"] == "answer":
        _check_role(result["query"], user)
        ran = execute(result["query"], result["filters"])
        response["status"] = ran["status"]
        if ran["status"] == "answer":
            response.update(columns=ran["columns"], rows=ran["rows"], source=ran["source"], notes=ran["notes"])
        else:
            response["clarify"] = ran["clarify"]
        response["understood"] = {"query": result["query"], "label": ENTRIES[result["query"]].label,
                                  "filters": result["filters"], "chips": chips(result["query"], result["filters"])}
    elif result["status"] == "clarify":
        response["clarify"] = result["clarify"]
        response["understood"] = {"query": result["query"], "label": ENTRIES[result["query"]].label}

    response["audit_id"] = _audit(user, "ASK_QUESTION", result.get("query") or "unsupported", {
        "question": question, "model": model_raw, "model_name": llm.model_name() if model_raw is not None else None,
        "filters": result.get("filters"), "status": response["status"], "rows": len(response.get("rows", [])),
        "ignored": ignored, "ms": round((time.monotonic() - started) * 1000),
    })
    return response


def export_rows(user: dict, entry_id: str, filters: dict, question: str) -> tuple:
    """Re-runs the query server-side for the Excel file; never trusts rows from the browser."""
    clean = validate(entry_id, filters)
    _check_role(entry_id, user)
    ran = execute(entry_id, clean)
    if ran["status"] != "answer":
        raise HTTPException(409, ran["clarify"]["question"])
    _audit(user, "ASK_EXPORT", entry_id, {"question": question, "filters": clean, "rows": len(ran["rows"])})
    return ENTRIES[entry_id], clean, ran
