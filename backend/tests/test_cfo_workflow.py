"""CFO reconciliation workflow (specs/cfo-reconciliation-workflow.md, FLOW-5): the bridge's and
outcome worker's Postgres side (camunda/bridge/reconciliation_db.py) and the endpoints the Tasks
screen calls at each step. Tests run in file order: they walk one item through the whole process."""
import os
import pathlib
import sys
from datetime import datetime, timezone

import psycopg2
import psycopg2.extras
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import reconciliation_db  # noqa: E402

API = "/api/v1"
RUN = "CORE_CSV-20260924T120000Z-dddd0004"
T0009 = {"transaction_id": "T0009", "account_id": "ACC004", "date": "2026-09-06", "amount": 1000.0,
         "currency": "USD", "type": "Deposit", "channel": "Cheque"}


@pytest.fixture(scope="module")
def item(db):
    rows = [
        # A gap item and a clean one from the same run.
        (f"{RUN}|CORE_CSV|Lebanon|transactions", RUN, "CORE_CSV", "Lebanon", "transactions", 6, 5, 1, "amount", 0,
         psycopg2.extras.Json({"USD": {"received": 64800.0, "clean": 63800.0, "gap": 1000.0}}), True, "OPEN",
         datetime(2026, 9, 24, 12, tzinfo=timezone.utc)),
        (f"{RUN}|CORE_CSV|Qatar|customers", RUN, "CORE_CSV", "Qatar", "customers", 2, 2, 0, None, 0, None, False,
         "MATCHED", datetime(2026, 9, 24, 12, tzinfo=timezone.utc)),
    ]
    db.executemany(
        """INSERT INTO pipeline_reconciliation (recon_key, ingest_batch_id, source_system, source_country, source_table,
               received_rows, clean_rows, rejected_rows, amount_column, unreadable_amount_rows, amounts_by_currency,
               has_gap, status, detected_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows,
    )
    db.execute(
        """INSERT INTO data_quality_exceptions (source_table, record_key, flag_label, description, source_system,
               source_country, ingest_batch_id, source_file, record_data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        ("transactions", "T0009", "INVALID_CHANNEL", "channel 'Cheque' is not valid", "CORE_CSV", "Lebanon", RUN,
         "transactions.csv", psycopg2.extras.Json(T0009)),
    )
    db.execute("SELECT recon_id FROM pipeline_reconciliation WHERE recon_key = %s", (rows[0][0],))
    recon_id = db.fetchone()[0]
    yield recon_id
    db.execute("DELETE FROM reconciliation_corrections")
    db.execute("DELETE FROM camunda_process_tracking WHERE record_type = 'reconciliation'")
    db.execute("DELETE FROM pipeline_reconciliation")
    db.execute("DELETE FROM data_quality_exceptions WHERE ingest_batch_id = %s", (RUN,))


@pytest.fixture(scope="module")
def conn(db):
    """A transactional connection, as the bridge and outcome worker use (the db fixture autocommits)."""
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


@pytest.fixture(scope="module")
def users(db):
    db.execute("SELECT email, user_id FROM users")
    return {email.split("@")[0]: uid for email, uid in db.fetchall()}


def _status(client, auth, recon_id):
    rows = client.get(f"{API}/reconciliation/pipeline?latest_only=false", headers=auth).json()
    return next(r for r in rows if r["recon_id"] == recon_id)


def _event(client, auth, recon_id, **body):
    return client.post(f"{API}/reconciliation/pipeline/{recon_id}/events", headers=auth, json=body)


def _correct(client, auth, recon_id, **body):
    return client.post(f"{API}/reconciliation/pipeline/{recon_id}/corrections", headers=auth, json=body)


# ---- bridge: one process per gap item, handed to the CFO, never twice ------------------------
def test_bridge_starts_one_process_per_gap_item_for_the_cfo(conn, item, users):
    unstarted = reconciliation_db.fetch_unstarted(conn)
    assert [i["recon_id"] for i in unstarted] == [item]                      # the MATCHED item needs no review
    assert reconciliation_db.title(unstarted[0]) == "CORE_CSV · Lebanon · transactions: 1 of 6 rows rejected"
    cfo = reconciliation_db.cfo_user_id(conn, "approver@bankx.demo")
    variables = reconciliation_db.process_variables(unstarted[0], cfo)
    assert variables["recordType"] == "reconciliation" and variables["recordKey"] == str(item) and variables["cfoUserId"] == users["approver"]

    reconciliation_db.record_started(conn, item, 2251799813685249)
    reconciliation_db.record_started(conn, item, 2251799813685249)            # a retried poll changes nothing
    assert reconciliation_db.fetch_unstarted(conn) == []


def test_a_missing_delivery_gets_a_task_title_that_says_so():
    missing = {"source_system": "CORE_CSV", "source_country": "Qatar", "source_table": "transactions",
               "received_rows": 0, "rejected_rows": 0, "note": "No rows delivered"}
    assert reconciliation_db.title(missing) == "CORE_CSV · Qatar · transactions: No rows delivered"


def test_the_item_is_now_with_the_cfo(client, auth, item):
    assert _status(client, auth, item)["status"] == "WITH_CFO"


# ---- corrections: only real fields of this item's rejected records ---------------------------
def test_the_records_endpoint_shows_the_rejected_rows_own_values(client, auth, item):
    body = client.get(f"{API}/reconciliation/pipeline/{item}/records", headers=auth).json()
    assert body["records"][0]["record_data"]["channel"] == "Cheque"


def test_a_correction_keeps_the_old_value_and_a_second_one_replaces_the_first(client, auth, item):
    assert _correct(client, auth, item, record_key="T0009", field_name="channel", new_value="Branch").status_code == 200
    assert _correct(client, auth, item, record_key="T0009", field_name="channel", new_value="Online").status_code == 200
    corrections = client.get(f"{API}/reconciliation/pipeline/{item}/corrections", headers=auth).json()
    assert [(c["field_name"], c["old_value"], c["new_value"], c["status"]) for c in corrections] == [("channel", "Cheque", "Online", "PROPOSED")]


@pytest.mark.parametrize("body, message", [
    ({"record_key": "T0001", "field_name": "channel", "new_value": "Branch"}, "not a rejected record"),
    ({"record_key": "T0009", "field_name": "colour", "new_value": "red"}, "no field"),
    ({"record_key": "T0009", "field_name": "transaction_id", "new_value": "T9999"}, "identifies the record"),
    ({"record_key": "T0009", "field_name": "channel", "new_value": "  "}, "Enter the corrected value"),
    ({"record_key": "T0009", "field_name": "amount", "new_value": "a thousand"}, "enter a number"),
])
def test_corrections_are_refused_for_anything_but_a_real_field_of_a_rejected_record(client, auth, item, body, message):
    r = _correct(client, auth, item, **body)
    assert r.status_code == 400 and message in r.json()["detail"]


# ---- steps: reassign -> submit -> return -> submit, wrong order refused ----------------------
def test_steps_out_of_order_are_refused(client, auth, item):
    r = _event(client, auth, item, event="SUBMITTED")
    assert r.status_code == 409 and "WITH_CFO" in r.json()["detail"]
    assert _event(client, auth, item, event="REASSIGNED").status_code == 400          # to whom?


def test_the_cfo_reassigns_and_the_assignee_can_still_correct(client, auth, item, users):
    assert _event(client, auth, item, event="REASSIGNED", assignee_user_id=users["reviewer"], comment="please fix").json() == {"status": "ASSIGNED"}
    row = _status(client, auth, item)
    assert row["status"] == "ASSIGNED" and row["assigned_to_name"] == "Demo Reviewer"
    assert _correct(client, auth, item, record_key="T0009", field_name="amount", new_value="1000.00").status_code == 200


def test_after_submitting_values_are_locked_and_a_return_needs_a_reason(client, auth, item):
    assert _event(client, auth, item, event="SUBMITTED", comment="fixed the channel").json() == {"status": "SUBMITTED"}
    assert _correct(client, auth, item, record_key="T0009", field_name="channel", new_value="ATM").status_code == 409
    assert _event(client, auth, item, event="RETURNED").status_code == 400
    assert _event(client, auth, item, event="RETURNED", comment="check the amount too").json() == {"status": "ASSIGNED"}
    assert _event(client, auth, item, event="SUBMITTED").json() == {"status": "SUBMITTED"}


def test_comments_can_be_added_on_a_reconciliation_item(client, auth, item):
    key = {"source_table": "pipeline_reconciliation", "record_key": str(item), "flag_label": "RECONCILIATION"}
    assert client.post(f"{API}/workflow/exceptions/comments", headers=auth, json={**key, "comment_text": "looks right"}).status_code == 200
    assert [c["comment_text"] for c in client.get(f"{API}/workflow/exceptions/comments", headers=auth, params=key).json()] == ["looks right"]


# ---- approval: the outcome worker's write, atomic and idempotent -----------------------------
def test_approval_approves_the_item_and_every_proposed_correction_with_audit_rows(db, conn, client, auth, item, users):
    reconciliation_db.approve(conn, item, users["approver"])
    reconciliation_db.approve(conn, item, users["approver"])                   # a retried job changes nothing
    row = _status(client, auth, item)
    assert row["status"] == "APPROVED" and row["approved_by"] == users["approver"]
    corrections = client.get(f"{API}/reconciliation/pipeline/{item}/corrections", headers=auth).json()
    assert {(c["field_name"], c["status"]) for c in corrections} == {("channel", "APPROVED"), ("amount", "APPROVED")}
    db.execute("SELECT action FROM audit_log WHERE object_type IN ('reconciliation_item', 'reconciliation_correction') ORDER BY log_id")
    actions = [a for (a,) in db.fetchall()]
    assert actions.count("APPROVED") == 1 and actions.count("CORRECTION_APPROVED") == 2
    assert actions.count("REASSIGNED") == 1 and actions.count("SUBMITTED") == 2 and actions.count("RETURNED") == 1


def test_an_approved_item_takes_no_more_corrections_or_steps(client, auth, item):
    assert _correct(client, auth, item, record_key="T0009", field_name="channel", new_value="ATM").status_code == 409
    assert _event(client, auth, item, event="RETURNED", comment="too late").status_code == 409


def test_the_assignee_list_has_every_demo_user(client, auth):
    names = [u["name"] for u in client.get(f"{API}/reconciliation/assignees", headers=auth).json()]
    assert {"Demo Analyst", "Demo Reviewer", "Demo Approver", "Demo Admin"} <= set(names)
