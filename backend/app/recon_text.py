"""Reconciliation tasks in plain words (specs/reconciliation-approvals.md): what happened, and what the
person looking at the task has to decide. The bridge writes each task's one-line title; these are the
fuller sentences at the top of the task popup.
"""

# Why Notebook 2 rejected a row, and the field that caused it (highlighted in the row).
FLAG_FIELD = {
    "INVALID_AMOUNT": "amount", "INVALID_CHANNEL": "channel", "INVALID_CURRENCY": "currency", "INVALID_RATE": "rate",
    "INVALID_RWA": "risk_weighted_assets", "INVALID_SEGMENT": "segment", "INVALID_STAGE": "stage",
    "MISSING_ACCOUNT_ID": "account_id", "MISSING_BRANCH_ID": "branch_id", "MISSING_CUSTOMER_ID": "customer_id",
    "MISSING_DATE": "date", "MISSING_LOAN_ID": "loan_id", "MISSING_MONTH": "month", "MISSING_RISK_RATING": "risk_rating",
    "MISSING_TRANSACTION_ID": "transaction_id", "NEGATIVE_BALANCE": "balance", "NEGATIVE_DPD": "days_past_due",
    "NEGATIVE_HQLA": "hqla", "NEGATIVE_OPEX": "monthly_opex", "NPL_STAGE_MISMATCH": "stage",
    "ORPHAN_ACCOUNT": "account_id", "ORPHAN_BRANCH": "branch_id", "ORPHAN_CUSTOMER": "customer_id",
    "OUTSTANDING_EXCEEDS_PRINCIPAL": "outstanding",
}

# A source, as a sentence names it.
SYSTEM_NAME = {"neon": "core banking", "salesforce": "the CRM", "CORE_CSV": "the core banking files"}
RUN_NAME = {"CORE_CSV": "core banking files", "neon": "core banking comparison", "salesforce": "CRM comparison"}
ENTITY = {"account": "account", "customer": "customer"}


def _day(d) -> str:
    return f"{d.day} {d:%b %Y}" if d else ""


def _plural(n: int, word: str) -> str:
    return f"{n} {word}" + ("" if n == 1 else "s")


def _money(x: float) -> str:
    return f"{abs(x):,.2f}"


def run_name(source_system: str, run_date, run_key: str = "") -> str:
    """E.g. "core banking comparison of 25 Sep 2026"."""
    part = f" (part {run_key.split('#')[1]})" if "#" in (run_key or "") else ""
    return f"{RUN_NAME.get(source_system, source_system + ' run')} of {_day(run_date)}{part}"


def pipeline_summary(item: dict, records: list) -> dict:
    """What happened to a delivery's rows, why each was rejected, and what the team decides."""
    where = f"{item['source_country']} {item['source_table']}"
    when = _day(item["detected_at"].date()) if item.get("detected_at") else ""
    if item.get("note"):
        headline = f"The {where} file was expected in the core banking delivery of {when}, but no rows arrived."
        reasons = []
    else:
        n = item["received_rows"]
        headline = (f"{n:,} row{'' if n == 1 else 's'} of {where} arrived in the core banking delivery of {when}: "
                    f"{item['clean_rows']:,} loaded, {item['rejected_rows']:,} rejected.")
        reasons = [f"{r['record_key']}: {r['description']}" for r in records]
    gaps = [f"{cur} {_money(v['gap'])}" for cur, v in sorted((item.get("amounts_by_currency") or {}).items()) if abs(v.get("gap") or 0) > 0.005]
    return {
        "headline": headline,
        "reasons": reasons,
        "money": f"Not in our books because of this: {', '.join(gaps)}." if gaps else None,
        "job": ("Decide what happens to these rows. Correct our data: enter the right values below and the rows load in the "
                "next run. Accept: they stay out and the gap is explained. Dismiss: not a real problem."),
    }


def difference(b: dict):
    try:
        return round(float(b["source_value"]) - float(b["canonical_value"]), 2)
    except (TypeError, ValueError):
        return None


def group_summary(group: dict, breaks: list) -> dict:
    """What differs between our data and the source system, in one sentence, and what the team decides."""
    system = SYSTEM_NAME.get(group["source_system"], group["source_system"])
    entity = ENTITY.get(group["entity_type"], group["entity_type"])
    field = group["field_name"]
    n = len(breaks) or group["break_count"]
    one = breaks[0] if len(breaks) == 1 else None
    missing = group["mismatch_type"] != "VALUE_MISMATCH"
    if group["mismatch_type"] == "MISSING_IN_CANONICAL":
        headline = (f"{system[0].upper()}{system[1:]} has {entity} {one['entity_id']}, but our data doesn't." if one
                    else f"{system[0].upper()}{system[1:]} has {_plural(n, entity)} that our data doesn't.")
    elif group["mismatch_type"] == "MISSING_IN_SOURCE":
        headline = (f"Our data has {entity} {one['entity_id']}, but {system} doesn't." if one
                    else f"Our data has {_plural(n, entity)} that {system} doesn't.")
    else:
        diffs = [d for d in (difference(b) for b in breaks) if d is not None]
        if one and diffs:
            d = diffs[0]
            headline = (f"{entity.title()} {one['entity_id']}'s {field} is {_money(d)} {'higher' if d > 0 else 'lower'} in {system} "
                        f"than in our data ({one['source_value']} there, {one['canonical_value']} here).")
        elif one:
            headline = f"{entity.title()} {one['entity_id']}'s {field} is \"{one['source_value']}\" in {system} and \"{one['canonical_value']}\" in our data."
        elif diffs and len(set(diffs)) == 1:
            d = diffs[0]
            headline = (f"{_plural(n, entity)} have a {field} {_money(d)} {'higher' if d > 0 else 'lower'} in {system} than in our data "
                        f"({_money(sum(diffs))} in total).")
        elif diffs:
            headline = (f"{_plural(n, entity)} have a {field} that differs from {system} by {group['pattern'].replace('difference ', '')} "
                        f"({_money(sum(abs(d) for d in diffs))} in total).")
        else:
            headline = f"{_plural(n, entity)} have a different {field} in {system}."
    job = ("Decide for the whole group. Accept: the difference is explained. "
           + ("" if missing else f"Correct our data: fix our values ({system}'s value is filled in, and you can change it). ")
           + "Dismiss: not a real difference.")
    if n > 1:
        job += " Leave out any record that needs its own look; it becomes a task of its own."
    if missing:
        job += " A missing record can't be corrected from here: raise it with the team that owns the record."
    return {"headline": headline, "reasons": [], "money": None, "job": job}
