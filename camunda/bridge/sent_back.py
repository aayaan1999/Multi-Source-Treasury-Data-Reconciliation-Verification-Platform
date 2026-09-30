"""The process variables that tell the reconciliation team a task was sent back (specs/reconciliation-approvals.md
section 10). No imports, so every bridge module can use it."""


def sent_back_variables(row: dict) -> dict:
    """sentBackNote / sentBackByName / sentBackAt / sentBackFrom from a task's row; empty when it wasn't sent back."""
    if not row.get("sent_back_at"):
        return {}
    return {"sentBackNote": row.get("sent_back_note") or "", "sentBackByName": row.get("sent_back_by_name") or "",
            "sentBackAt": row["sent_back_at"].isoformat(), "sentBackFrom": row.get("sent_back_from") or ""}
