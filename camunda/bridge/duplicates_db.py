"""Possible duplicate customers (specs/entity-matching.md, client point 3): clean names, score pairs,
save candidates for a person to decide, and rebuild the customer -> group link from confirmed pairs.
Nothing is ever merged automatically, and the customer records themselves are never changed.

Plain psycopg2 + the standard library (difflib), no Zeebe, so it's testable without Camunda.
Pairs are compared within blocks (same first letter of the cleaned name, or an abbreviation that
expands into the block), which keeps it quick at demo scale; at millions of customers this belongs
in Databricks (spec section 6).
"""
import re
from collections import defaultdict
from datetime import date, timedelta
from difflib import SequenceMatcher

import psycopg2.extras

RECORD_TYPE = "entity_match"
SOURCE_TABLE = "entity_match_candidates"
FLAG_LABEL = "POSSIBLE_DUPLICATE"


def settings(conn) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT key, value FROM app_settings WHERE key IN ('dedup.matching', 'task.due_days')")
        return dict(cur.fetchall())


def clean_name(name: str, cfg: dict) -> str:
    """Upper case, punctuation to spaces, legal words ("SAL", "Ltd", ...) removed, known
    abbreviations expanded: "Tata Consultancy Services Ltd." and "TCS" both -> "TATA CONSULTANCY SERVICES"."""
    # Dots go without a space first, so "S.A.L." reads as the legal word "SAL"; other punctuation
    # separates words.
    words = re.sub(r"[^A-Z0-9 ]+", " ", (name or "").upper().replace(".", "")).split()
    legal = set(cfg["legal_words"])
    cleaned = " ".join(w for w in words if w not in legal)
    return cfg["abbreviations"].get(cleaned, cleaned)


def _initials(cleaned: str) -> str:
    return "".join(w[0] for w in cleaned.split())


def score_pair(a: dict, b: dict, cfg: dict) -> tuple:
    """(score 0-1, reasons). The score is how alike the cleaned names are; an acronym ("TCS" for
    "Tata Consultancy Services") counts as a match. Shared branch/country only add reasons - they
    help a reviewer decide but never make two different names a match on their own."""
    name_a, name_b = clean_name(a["name"], cfg), clean_name(b["name"], cfg)
    if not name_a or not name_b:
        return 0.0, []
    reasons = []
    if name_a == name_b:
        score = 1.0
        reasons.append("same name once legal words and abbreviations are set aside")
    elif (len(name_a.split()) == 1 and name_a == _initials(name_b)) or (len(name_b.split()) == 1 and name_b == _initials(name_a)):
        score = 0.95
        reasons.append("one name is the other's initials")
    else:
        score = SequenceMatcher(None, name_a, name_b).ratio()
        reasons.append(f"names {round(score * 100)}% alike")
    if a.get("branch_id") and a.get("branch_id") == b.get("branch_id"):
        reasons.append("same branch")
    if a.get("country") and a.get("country") == b.get("country"):
        reasons.append("same country")
    if a.get("segment") and a.get("segment") == b.get("segment"):
        reasons.append(f"both {a['segment']}")
    return round(score, 4), reasons


def find_candidates(conn) -> int:
    """Scores customer pairs and saves new ones at or above min_score as PENDING. A pair already
    decided (or already pending) is never raised again. Returns how many were added."""
    cfg = settings(conn)["dedup.matching"]
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute("SELECT customer_id, name, segment, branch_id, country FROM customers")
        customers = cur.fetchall()
        blocks = defaultdict(list)
        for c in customers:
            cleaned = clean_name(c["name"], cfg)
            if cleaned:
                blocks[cleaned[0]].append(c)
        added = 0
        for members in blocks.values():
            members.sort(key=lambda c: c["customer_id"])
            for i, a in enumerate(members):
                for b in members[i + 1:]:
                    score, reasons = score_pair(a, b, cfg)
                    if score < cfg["min_score"]:
                        continue
                    cur.execute(
                        """INSERT INTO entity_match_candidates (customer_a, customer_b, name_a, name_b, score, reasons)
                           VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (customer_a, customer_b) DO NOTHING""",
                        (a["customer_id"], b["customer_id"], a["name"], b["name"], score, reasons),
                    )
                    added += cur.rowcount
    conn.commit()
    return added


def fetch_unstarted(conn) -> list:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            """SELECT candidate_id, customer_a, customer_b, name_a, name_b, score, reasons, created_at
               FROM entity_match_candidates WHERE status = 'PENDING' AND process_instance_key IS NULL
               ORDER BY score DESC, candidate_id"""
        )
        return cur.fetchall()


def process_variables(c: dict, due_days: int, today: date = None) -> dict:
    today = today or date.today()
    return {
        "recordType": RECORD_TYPE,
        "sourceTable": SOURCE_TABLE,
        "recordKey": str(c["candidate_id"]),
        "flagLabel": FLAG_LABEL,
        "flagType": "FAULT",
        "flagCategory": "OPERATIONS",     # placeholder owner until the bank names one (spec section 5)
        "title": f"Same company? {c['name_a']} ({c['customer_a']}) / {c['name_b']} ({c['customer_b']}) · {round(c['score'] * 100)}%",
        "severity": "MEDIUM",
        "dueDate": (today + timedelta(days=due_days)).isoformat(),
        "description": "; ".join(c["reasons"]),
    }


def record_started(conn, candidate_id: int, process_instance_key: int) -> None:
    with conn.cursor() as cur:
        cur.execute("UPDATE entity_match_candidates SET process_instance_key = %s WHERE candidate_id = %s",
                    (process_instance_key, candidate_id))
        cur.execute(
            """INSERT INTO camunda_process_tracking (record_type, source_table, record_key, flag_label, process_instance_key)
               VALUES (%s, %s, %s, %s, %s) ON CONFLICT (record_type, source_table, record_key, flag_label) DO NOTHING""",
            (RECORD_TYPE, SOURCE_TABLE, str(candidate_id), FLAG_LABEL, process_instance_key),
        )
    conn.commit()


def rebuild_groups(cur) -> None:
    """customer_entity from every CONFIRMED pair: connected customers form one group, led by the
    lowest customer id. Rebuilt whole so a later decision can never leave a stale link."""
    cur.execute("SELECT customer_a, customer_b FROM entity_match_candidates WHERE status = 'CONFIRMED'")
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in cur.fetchall():
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)
    cur.execute("DELETE FROM customer_entity")
    rows = [(c, find(c)) for c in parent]
    if rows:
        cur.executemany("INSERT INTO customer_entity (customer_id, master_customer_id) VALUES (%s, %s)", rows)


def decide(conn, candidate_id: int, outcome: str, decided_by: int) -> None:
    """A person's decision (APPROVED = same company, REJECTED = different): the pair's status, the
    group links rebuilt, one audit row - one transaction. Idempotent for a retried job."""
    status = "CONFIRMED" if outcome == "APPROVED" else "REJECTED"
    with conn.cursor() as cur:
        cur.execute(
            """UPDATE entity_match_candidates SET status = %s, decided_by = %s, decided_at = now()
               WHERE candidate_id = %s AND status = 'PENDING' RETURNING customer_a, customer_b""",
            (status, decided_by, candidate_id),
        )
        pair = cur.fetchone()
        if pair is None:
            conn.rollback()
            return
        rebuild_groups(cur)
        cur.execute(
            """INSERT INTO audit_log (user_id, action, object_type, object_id, old_value, new_value)
               VALUES (%s, %s, 'entity_match', %s, 'PENDING', %s)""",
            (decided_by, "SAME_ENTITY" if status == "CONFIRMED" else "DIFFERENT_ENTITIES", f"{pair[0]}:{pair[1]}", status),
        )
    conn.commit()
