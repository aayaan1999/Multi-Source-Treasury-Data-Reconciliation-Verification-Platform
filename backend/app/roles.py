"""Who sees what (specs/user-roles.md): the one table the menu, each person's home screen, the Tasks list and
the server's checks all read. A role's screens are the only ones in its menu, and the server refuses the
others' data; the auditor reads everything it may see and changes nothing.

screens: screen key -> "full" (works there) or "read" (looks, doesn't act). Keys match the frontend's routes:
    summary (/ and /kpi/*), portfolio, performance, scenario, reports, reconciliation, tasks, audit,
    ingestion, ask
tasks: which tasks the Tasks screen lists - by record type, and for reconciliation tasks by step (the
    Camunda group of the step: operations = team review, cfo = CFO approval and run sign-off)
"""
from fastapi import Depends, HTTPException, Request

from .security import current_user

ROLES = {
    "approver": {
        "title": "Chief Financial Officer (CFO)",
        "home": "/",
        "screens": {"summary": "full", "portfolio": "full", "performance": "full", "scenario": "full", "reports": "full",
                    "reconciliation": "read", "tasks": "full", "audit": "full", "ingestion": "full", "ask": "full"},
        "tasks": {"groups": ["cfo"]},
    },
    "risk": {
        "title": "Chief Risk Officer (CRO)",
        "home": "/portfolio",
        "screens": {"summary": "full", "portfolio": "full", "performance": "full", "scenario": "full", "reports": "full",
                    "tasks": "full", "ask": "full"},
        "tasks": {"types": ["breach"]},
    },
    "analyst": {
        "title": "Reconciliation Analyst",
        "home": "/tasks",
        "screens": {"summary": "read", "reconciliation": "full", "tasks": "full", "ingestion": "read", "ask": "full"},
        "tasks": {"groups": ["operations"], "types": ["data_quality", "entity_match"]},
    },
    "preparer": {
        "title": "Regulatory Reporting Officer",
        "home": "/reports",
        "screens": {"summary": "full", "portfolio": "read", "reports": "full", "tasks": "full", "ask": "full"},
        "tasks": {"types": ["report"]},              # the report workflow's steps, once it's built
    },
    "compliance": {
        "title": "Compliance Officer",
        "home": "/tasks",
        "screens": {"summary": "read", "tasks": "full", "ask": "full"},
        "tasks": {"types": ["fraud", "fraud_case"]},
    },
    "auditor": {
        "title": "Internal Auditor",
        "home": "/audit-oversight",
        "screens": {"summary": "read", "portfolio": "read", "performance": "read", "reports": "read",
                    "reconciliation": "read", "audit": "full", "ingestion": "read", "ask": "full"},
        "tasks": {},
        "read_only": True,
    },
    "admin": {
        "title": "Platform Administrator",
        "home": "/ingestion",
        "screens": {"summary": "read", "reconciliation": "read", "tasks": "full", "audit": "full", "ingestion": "full",
                    "ask": "full"},
        "tasks": {"all": True},
    },
}

# Requests an auditor may still send with POST: signing in, asking a question (it reads data; only the
# question is kept, in the audit log) and exports (a file of what's on screen).
READ_ONLY_ALLOWED = ("/api/v1/auth/", "/api/v1/ask")
READ_ONLY_ALLOWED_PART = "/export"


def access(role: str) -> dict:
    """What the frontend needs to shape the app for this role."""
    r = ROLES.get(role)
    if r is None:
        return {"title": role, "home": "/", "screens": {"summary": "read"}, "tasks": {}, "read_only": True}
    return {"title": r["title"], "home": r["home"], "screens": r["screens"], "tasks": r["tasks"],
            "read_only": bool(r.get("read_only"))}


def roles_with(screen: str) -> set:
    return {name for name, r in ROLES.items() if screen in r["screens"]}


def screen(*names: str):
    """A router dependency: only roles that have one of these screens get its data."""
    allowed = set().union(*(roles_with(n) for n in names))

    def check(user: dict = Depends(current_user)) -> dict:
        if user["role"] not in allowed:
            raise HTTPException(403, f"{access(user['role'])['title']} doesn't use this screen")
        return user
    return check


def no_writes_for_read_only(request: Request, user: dict = Depends(current_user)) -> dict:
    """The auditor reads and changes nothing: every write is refused, whatever screen it comes from."""
    if (ROLES.get(user["role"], {}).get("read_only") and request.method not in ("GET", "HEAD", "OPTIONS")
            and not request.url.path.startswith(READ_ONLY_ALLOWED) and READ_ONLY_ALLOWED_PART not in request.url.path):
        raise HTTPException(403, f"{access(user['role'])['title']} can look but not change anything")
    return user
