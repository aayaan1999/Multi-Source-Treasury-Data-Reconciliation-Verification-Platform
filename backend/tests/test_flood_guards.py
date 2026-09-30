"""Guards against one wrong file flooding the task list (specs/reconciliation-groups.md section 4a):
many records missing at once become one "check the file" task, and duplicate-customer reviews are
started a limited number at a time. The upload's own check is in test_file_upload.py."""
import os
import pathlib
import sys
from datetime import date, datetime, timezone

import psycopg2
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import duplicates_db  # noqa: E402
import recon_groups_db  # noqa: E402

SEEN = datetime(2026, 9, 30, 12, tzinfo=timezone.utc)


def missing(entity_id, mismatch="MISSING_IN_CANONICAL"):
    return ("salesforce", "customer", entity_id, None, None, None, mismatch, "OPEN", SEEN, SEEN, SEEN)


@pytest.fixture
def conn():
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


@pytest.fixture
def breaks(db):
    def add(rows):
        db.executemany(
            """INSERT INTO reconciliation_exceptions (source_system, entity_type, entity_id, field_name, source_value,
                   canonical_value, mismatch_type, status, detected_at, first_seen, last_seen)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            rows,
        )
    yield add
    db.execute("DELETE FROM reconciliation_exceptions WHERE entity_id LIKE 'FLOOD%%'")
    db.execute("DELETE FROM reconciliation_groups WHERE group_key LIKE 'salesforce|%%'")


def groups(db):
    db.execute("""SELECT group_key, break_count, cfo_required, cfo_reason FROM reconciliation_groups
                  WHERE group_key LIKE 'salesforce|%%' ORDER BY break_count DESC, group_key""")
    return db.fetchall()


def test_many_missing_records_at_once_become_one_check_the_file_task_for_the_cfo(db, conn, breaks):
    breaks([missing(f"FLOOD{i:03}") for i in range(30)] + [missing(f"FLOODX{i}", "MISSING_IN_SOURCE") for i in range(2)])
    recon_groups_db.create_groups(conn, date(2026, 9, 30))
    found = groups(db)
    mass = found[0]
    assert mass[0].endswith("|mass") and mass[1] == 30
    assert mass[2] is True and "30 missing records at once" in mass[3]
    # below the limit, a missing record is still a task of its own
    assert [g[1] for g in found[1:]] == [1, 1] and all("single:" in g[0] for g in found[1:])
    db.execute("SELECT * FROM reconciliation_groups WHERE group_key = %s", (mass[0],))
    cols = [d[0] for d in db.description]
    g = dict(zip(cols, db.fetchone()))
    title = recon_groups_db.title(g, recon_groups_db.breaks_of(conn, g["group_id"]))
    assert title == "30 customers: in the CRM but missing from our data - check the file that was loaded"


def test_the_limit_comes_from_the_rules(db, conn, breaks, monkeypatch):
    real = recon_groups_db.settings
    monkeypatch.setattr(recon_groups_db, "settings", lambda c: {**real(c), "recon.rules": {**real(c)["recon.rules"], "mass_missing_min": 3}})
    breaks([missing(f"FLOOD{i}") for i in range(3)])
    recon_groups_db.create_groups(conn, date(2026, 9, 30))
    assert [(g[0].endswith("|mass"), g[1]) for g in groups(db)] == [(True, 3)]


@pytest.fixture
def candidates(db):
    db.executemany(
        "INSERT INTO entity_match_candidates (customer_a, customer_b, name_a, name_b, score, reasons) VALUES (%s, %s, 'X', 'X', %s, '{}')",
        [(f"FLOODA{i:02}", f"FLOODB{i:02}", 0.9 + i / 1000) for i in range(40)],
    )
    yield
    db.execute("DELETE FROM entity_match_candidates WHERE customer_a LIKE 'FLOOD%%'")


def test_duplicate_reviews_start_a_limited_number_at_a_time_best_first(db, conn, candidates):
    first = duplicates_db.fetch_unstarted(conn)
    assert len(first) == duplicates_db.MAX_OPEN_REVIEWS == 25
    assert first[0]["customer_a"] == "FLOODA39"                              # best score first
    for c in first:
        duplicates_db.record_started(conn, c["candidate_id"], 1000 + c["candidate_id"])
    assert duplicates_db.fetch_unstarted(conn) == []                          # full: the rest wait
    db.execute("UPDATE entity_match_candidates SET status = 'REJECTED' WHERE candidate_id = ANY(%s)",
               ([c["candidate_id"] for c in first[:5]],))
    assert len(duplicates_db.fetch_unstarted(conn)) == 5                      # five decided, five more start
    db.execute("DELETE FROM camunda_process_tracking WHERE record_type = 'entity_match' AND record_key = ANY(%s)",
               ([str(c["candidate_id"]) for c in first],))
