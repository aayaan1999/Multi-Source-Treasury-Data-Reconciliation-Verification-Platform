"""A run already waiting for sign-off when a newer delivery replaces all its tasks (found in QA on
2026-10-01: run 18 sat in the CFO's sign-off list with nothing in it, saying "found nothing to review"). It is
retired with the run it was replaced by, and the poll worker gets its sign-off process back to cancel; a
run that still holds decided tasks stays for the CFO to sign off."""
import os
import pathlib
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import recon_runs_db  # noqa: E402
import reconciliation_db  # noqa: E402

SRC = "QA_SRC"
A, B, C = "QA_SRC-20260928T070000Z-a", "QA_SRC-20260929T070000Z-b", "QA_SRC-20260930T070000Z-c"


def gap(batch, table, when):
    return (f"{batch}|{SRC}|Lebanon|{table}", batch, SRC, "Lebanon", table, 10, 9, 1,
            psycopg2.extras.Json({"USD": {"received": 5.0, "clean": 0.0, "gap": 5.0}}), True, "OPEN", when)


def add(db, *rows):
    db.executemany(
        """INSERT INTO pipeline_reconciliation (recon_key, ingest_batch_id, source_system, source_country, source_table,
               received_rows, clean_rows, rejected_rows, amounts_by_currency, has_gap, status, detected_at)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows,
    )


@pytest.fixture
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()
    db.execute("DELETE FROM pipeline_reconciliation WHERE source_system = %s", (SRC,))
    db.execute("DELETE FROM reconciliation_runs WHERE source_system = %s", (SRC,))


def run_of(db, key):
    db.execute("SELECT run_id, status FROM reconciliation_runs WHERE source_system = %s AND run_key = %s", (SRC, key))
    return db.fetchone()


def supersede_old_items(conn):
    for i in reconciliation_db.fetch_superseded(conn):
        reconciliation_db.mark_superseded(conn, i["recon_id"])


def test_a_run_in_sign_off_whose_tasks_were_all_replaced_is_retired_and_its_sign_off_cancelled(conn, db):
    add(db, gap(A, "transactions", datetime(2026, 9, 28, 7, tzinfo=timezone.utc)))
    recon_runs_db.sync_runs(conn)
    run_a, _ = run_of(db, A)
    recon_runs_db.record_started(conn, run_a, 4242)                      # the 08:00 cut-off put it in sign-off
    assert run_of(db, A)[1] == "IN_SIGNOFF"

    add(db, gap(B, "transactions", datetime(2026, 9, 29, 7, tzinfo=timezone.utc)))    # the next delivery
    supersede_old_items(conn)
    retired = recon_runs_db.sync_runs(conn)

    assert run_of(db, A)[1] == "SUPERSEDED"
    assert retired == [{"run_id": run_a, "process_instance_key": 4242}]   # the worker cancels this sign-off
    assert run_of(db, B)[1] == "OPEN"
    assert recon_runs_db.sync_runs(conn) == []                            # nothing to cancel twice


def test_a_run_in_sign_off_that_still_holds_a_decided_task_stays_for_the_cfo(conn, db):
    when = datetime(2026, 9, 29, 7, tzinfo=timezone.utc)
    add(db, gap(B, "transactions", when), gap(B, "accounts", when))
    recon_runs_db.sync_runs(conn)
    run_b, _ = run_of(db, B)
    db.execute("UPDATE pipeline_reconciliation SET status = 'DECIDED', decision = 'ACCEPT' WHERE ingest_batch_id = %s AND source_table = 'accounts'", (B,))
    recon_runs_db.record_started(conn, run_b, 4343)

    add(db, gap(C, "transactions", datetime(2026, 9, 30, 7, tzinfo=timezone.utc)))
    supersede_old_items(conn)                                             # B's undecided gap is replaced
    retired = recon_runs_db.sync_runs(conn)

    assert run_of(db, B)[1] == "IN_SIGNOFF" and retired == []             # its decided task still needs signing off
