"""What the user is told when a question can't be answered as asked (specs/ask-a-question.md section 6.7).

Two kinds, from the problems extract.py finds:
  * explanations - no table at all, because any table would answer a different question (leaving
    things out, an unknown place or measure, a forecast, one customer, a split no report has, a
    request to change something, or nothing to do with the reports);
  * notices - the table is shown, with a plain note of what was not applied (a threshold, a change
    over time, two measures, a "why", a corrected typo).
Every explanation says why, how the panel works, and what to ask instead (buttons).
"""
from typing import Optional

from . import vocab
from .catalogue import ENTRIES

HOW = ("How this works: I match your question to one of the bank's approved reports, read the dates, places "
       "and numbers from your words, and run that report's fixed query. Every figure comes straight from the "
       "database - the AI never calculates or writes a number.")

# Order matters: the first problem found is the one explained.
REFUSALS = ("action", "customer", "forecast", "negation", "unknown_place", "unknown_measure", "unsupported_split")
BREAKDOWNS = [("country_breakdown", "by country"), ("product_performance", "by loan product"),
              ("segment_performance", "by segment"), ("branch_ranking", "by branch")]


def _join(items: list) -> str:
    items = list(items)
    return items[0] if len(items) == 1 else ", ".join(items[:-1]) + " and " + items[-1]


def _question(text: str) -> dict:
    return {"label": text, "question": text}


def breakdown_questions(metric: Optional[str]) -> list:
    """"NPL ratio by country", "... by loan product": the reports that split this measure."""
    if not metric:
        return [_question(q) for q in ("NPL ratio by country", "Profit by segment", "Loan book by currency")]
    fallbacks = {"segment_performance": {"npl_ratio": "bad_loans"}, "product_performance": {"bad_loans": "npl_ratio"}}
    out = []
    for entry_id, words in BREAKDOWNS:
        key = fallbacks.get(entry_id, {}).get(metric, metric)
        if key in ENTRIES[entry_id].metrics:
            out.append(_question(f"{vocab.METRICS[key].label} {words}"))
    return out[:3]


def explanation(problem: dict, entry_id: Optional[str], names: dict, suggestions: list) -> dict:
    code, detail = problem["code"], problem.get("detail", "")
    entry = ENTRIES.get(entry_id) if entry_id else None
    if code == "action":
        title, why = "I can only read reports", ("Your question asks me to change, delete or send something. This panel is "
                                                 "read-only: it can show the bank's figures, never alter them.")
    elif code == "customer":
        title, why = "I only work with summary figures", (
            "Your question is about one customer or account. This panel reads bank-wide summary tables only - no "
            "customer-level records - so personal data never appears in an answer. The largest borrowers are in "
            "the top-exposures report.")
    elif code == "forecast":
        title, why = "I can't forecast", (
            f"Your question asks about the future (“{detail}”). I only report figures the bank has already recorded. For "
            "what-if projections, use the Scenario modelling tab.")
    elif code == "negation":
        title, why = "I can't leave things out yet", (
            f"Your question says “{detail}”. I can narrow a report to the places, products or segments you name, but "
            "not exclude them - applying it would show you exactly what you asked me to leave out. You can see the "
            "full list instead and skip those rows.")
    elif code == "unknown_place":
        branches = _join([b["name"] for b in names.get("branches", [])]) or "none loaded"
        title, why = "I don't know that place", (
            f"“{detail}” isn't one of the bank's countries or branches in this data. The countries are Lebanon, "
            f"Saudi Arabia and Qatar; the branches are {branches}.")
    elif code == "unknown_measure":
        known = _join([vocab.METRICS[k].label for k in (entry.metrics if entry and entry.metrics else ENTRIES["kpi_value"].metrics)])
        where = f"for “{entry.label}”" if entry and entry.metrics else "among the headline KPIs"
        shown = detail.upper() if " " not in detail and len(detail) <= 6 else detail     # EBITDA, ROA, NSFR
        title, why = "I don't have that measure", (
            f"“{shown}” isn't in any report I can read. The measures I know {where} are {known}.")
    elif code == "unsupported_split":
        title, why = f"I can't split figures by {detail}", (
            f"None of the approved reports is broken down by {detail}. I can split figures by country, branch, "
            "segment, loan product or currency.")
    else:
        title, why = "That's not a question about the bank's reports", (
            "I couldn't match it to any of the approved reports: headline KPIs, countries, branches, segments, loan "
            "products, IFRS 9 stages, largest exposures, loan ageing, data quality and limit breaches.")
    return {"code": code, "title": title, "why": why, "how": HOW, "suggestions": suggestions}


def notices(ex, entry_id: str, filters: dict, extra_metrics: list) -> list:
    """Plain notes shown above a table that was answered, about what was not applied."""
    out = []
    metric = filters.get("metric")
    label = vocab.METRICS[metric].label if metric else None
    threshold = ex.problem("threshold")
    if threshold:
        first = "highest" if threshold.get("direction") == "high" else "lowest"
        out.append({"code": "threshold", "title": "Your limit isn't applied",
                    "message": f"I can't filter by “{threshold['detail']}” yet, so this shows every row, "
                               + (f"with the {first} {label} first - the rows that meet your "
                                  "condition are at the top." if metric else "unfiltered.")})
    two = ex.problem("two_periods")
    if two:
        out.append({"code": "two_periods", "title": "Both dates are shown, not the difference",
                    "message": f"You asked about {two['detail']}. I show every recorded day in between so you can compare "
                               "them; I don't calculate the change itself."})
    elif ex.problem("change"):
        out.append({"code": "change", "title": "Values are shown, not the change",
                    "message": f"You asked how the figures “{ex.problem('change')['detail']}”. I show the recorded values"
                               + (" for the period" if filters.get("date_from") else "")
                               + "; I don't calculate differences. Ask for a period, e.g. “... over the last 7 days”, "
                                 "to see how it moved."})
    if extra_metrics:
        others = _join([vocab.METRICS[k].label for k in extra_metrics])
        if metric:
            out.append({"code": "two_measures", "title": "One measure at a time",
                        "message": f"This report ranks by one measure: this is {label}. Switch the Measure chip to {others} "
                                   "to see the other."})
        else:
            out.append({"code": "two_measures", "title": "All measures shown",
                        "message": f"You asked for more than one measure, so every measure is shown, including {others}."})
    if ex.problem("why"):
        out.append({"code": "why", "title": "Figures, not causes",
                    "message": "I can show the figures, but not explain what caused them. Breaking them down often shows "
                               "where a change comes from:",
                    "suggestions": breakdown_questions(metric)})
    for typed, phrase in ex.typos:
        out.append({"code": "typo", "title": "Spelling corrected", "message": f"I read “{typed}” as “{phrase}”."})
    return out
