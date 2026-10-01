"""One approval model for reconciliation tasks (specs/reconciliation-approvals.md): pipeline gaps and
core-system break groups start with the team; the CFO must approve important tasks and any data fix,
never the person who decided; each run is signed off by the CFO once every task is decided, never by
anyone who decided a task in it, and the CFO can send named tasks back. Exercises the bridge's Postgres
side (what the Camunda service tasks call) and the endpoints the Tasks screen reads. Tests run in file
order: they walk one pipeline run and one core-banking run through the whole process."""
import os
import pathlib
import sys
from datetime import date, datetime, timezone

import psycopg2
import psycopg2.extras
import pytest

from conftest import PASSWORD

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / "camunda" / "bridge"))
import recon_groups_db  # noqa: E402
import recon_runs_db  # noqa: E402
import recon_tasks_db  # noqa: E402
import reconciliation_db  # noqa: E402

API = "/api/v1"
OLD, NEW = "CORE_CSV-20260928T070000Z-aaaa0001", "CORE_CSV-20260929T130000Z-bbbb0002"
SEEN = datetime(2026, 9, 25, 6, tzinfo=timezone.utc)
# "Now" for sign-off: before any run's 08:00 cut-off (bank time, UTC+3), and after the pipeline run's (29 Sep).
BEFORE_CUTOFF = datetime(2026, 9, 25, 12, tzinfo=timezone.utc)
AFTER_CUTOFF = datetime(2026, 9, 30, 6, tzinfo=timezone.utc)
T12 = {"transaction_id": "TN12", "account_id": "ACN0001", "date": "2026-09-22", "amount": 4000.0,
       "currency": "USD", "type": "Deposit", "channel": "Cheque"}


def item(batch, country, table, received, rejected, gaps, when, note=None):
    amounts = {cur: {"received": g, "clean": 0.0, "gap": g} for cur, g in gaps.items()}
    return (f"{batch}|CORE_CSV|{country}|{table}", batch, "CORE_CSV", country, table, received, received - rejected, rejected,
            psycopg2.extras.Json(amounts), True, "OPEN", when, note)


def brk(entity_type, entity_id, field, source, ours, mismatch="VALUE_MISMATCH"):
    return ("neon", entity_type, entity_id, field, source, ours, mismatch, "OPEN", SEEN, SEEN, SEEN)


@pytest.fixture(scope="module")
def data(db):
    t_old, t_new = datetime(2026, 9, 28, 7, tzinfo=timezone.utc), datetime(2026, 9, 29, 13, tzinfo=timezone.utc)
    db.executemany(
        """INSERT INTO pipeline_reconciliation (recon_key, ingest_batch_id, source_system, source_country, source_table,
               received_rows, clean_rows, rejected_rows, amounts_by_currency, has_gap, status, detected_at, note)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            item(OLD, "Lebanon", "transactions", 10, 1, {"USD": 4000.0}, t_old),              # replaced by the newer run
            item(NEW, "Lebanon", "transactions", 1419, 1, {"USD": 4000.0}, t_new),            # small: the team decides alone
            item(NEW, "Lebanon", "accounts", 229, 1, {"XYZ": 50000.0}, t_new),                # a big gap: the CFO must approve
            item(NEW, "Qatar", "loans", 0, 0, {}, t_new, note="No rows delivered"),           # nothing arrived: the CFO too
        ],
    )
    db.execute(
        """INSERT INTO data_quality_exceptions (source_table, record_key, flag_label, description, source_system,
               source_country, ingest_batch_id, source_file, record_data) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        ("transactions", "TN12", "INVALID_CHANNEL", "channel 'Cheque' is not one of Branch/ATM/Mobile/Online", "CORE_CSV",
         "Lebanon", NEW, "transactions.csv", psycopg2.extras.Json(T12)),
    )
    db.executemany(
        """INSERT INTO reconciliation_exceptions (source_system, entity_type, entity_id, field_name, source_value,
               canonical_value, mismatch_type, status, detected_at, first_seen, last_seen)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        [
            *[brk("account", f"ACN00{i}", "balance", "1015.0000", "1000.00") for i in range(10, 14)],     # +15 x 4: small bulk
            *[brk("account", f"ACN01{i}", "balance", "1000.00", "10000.00") for i in range(10, 13)],      # -9,000 x 3: 27,000 in all
            brk("customer", "CB-EXTRA-001", None, None, None, mismatch="MISSING_IN_CANONICAL"),             # missing: important
        ],
    )
    yield
    for sql in ("DELETE FROM reconciliation_corrections", "DELETE FROM camunda_process_tracking WHERE record_type IN ('reconciliation', 'recon_group')",
                "DELETE FROM pipeline_reconciliation", "DELETE FROM reconciliation_exceptions", "DELETE FROM reconciliation_groups",
                "DELETE FROM reconciliation_runs", f"DELETE FROM data_quality_exceptions WHERE ingest_batch_id = '{NEW}'"):
        db.execute(sql)


@pytest.fixture(scope="module")
def conn(db):
    c = psycopg2.connect(os.environ["DATABASE_URL"])
    yield c
    c.close()


@pytest.fixture(scope="module")
def users(db):
    db.execute("SELECT r.name, u.user_id FROM users u JOIN roles r ON r.role_id = u.role_id")
    return dict(db.fetchall())


@pytest.fixture(scope="module")
def ids(db, data):
    """Handles on the fixture's rows, by what they are."""
    db.execute("SELECT source_table, recon_id FROM pipeline_reconciliation WHERE ingest_batch_id = %s", (NEW,))
    return {f"pipe_{t}": i for t, i in db.fetchall()}


def login(client, who):
    token = client.post(f"{API}/auth/login", json={"email": f"{who}@bankx.demo", "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def status(db, table, id_col, key):
    db.execute(f"SELECT status FROM {table} WHERE {id_col} = %s", (key,))
    return db.fetchone()[0]


def group_id(db, pattern):
    db.execute("SELECT group_id FROM reconciliation_groups WHERE pattern = %s", (pattern,))
    return db.fetchone()[0]


# ---- starting tasks: pipeline gaps and groups go to the team, important ones flagged for the CFO -------

def test_only_the_newest_delivery_gets_tasks_and_the_older_one_is_superseded(conn, db, ids):
    assert [i["recon_id"] for i in reconciliation_db.fetch_superseded(conn)] and \
        all(reconciliation_db.mark_superseded(conn, i["recon_id"]) for i in reconciliation_db.fetch_superseded(conn))
    db.execute("SELECT status FROM pipeline_reconciliation WHERE ingest_batch_id = %s", (OLD,))
    assert db.fetchone()[0] == "SUPERSEDED"
    unstarted = {i["recon_id"]: i for i in reconciliation_db.fetch_unstarted(conn)}
    assert set(unstarted) == set(ids.values())


def test_pipeline_titles_and_the_cfo_rule(conn, ids):
    rules, due_days = reconciliation_db.rules(conn)
    unstarted = {i["source_table"]: i for i in reconciliation_db.fetch_unstarted(conn)}
    assert reconciliation_db.title(unstarted["transactions"]) == "Lebanon transactions: 1 row not loaded (unknown channel)"
    assert reconciliation_db.title(unstarted["loans"]) == "Qatar loans: no rows delivered"
    assert reconciliation_db.cfo_rule(unstarted["transactions"], rules) == (False, None)
    assert reconciliation_db.cfo_rule(unstarted["accounts"], rules) == (True, "a gap of 50,000.00 XYZ")
    assert reconciliation_db.cfo_rule(unstarted["loans"], rules) == (True, "a delivery with no rows")
    v = reconciliation_db.process_variables(unstarted["accounts"], rules, due_days, date(2026, 9, 30))
    assert (v["teamGroup"], v["severity"], v["dueDate"], v["cfoRequired"]) == ("operations", "HIGH", "2026-10-01", True)
    v = reconciliation_db.process_variables(unstarted["transactions"], rules, due_days, date(2026, 9, 30))
    assert (v["severity"], v["dueDate"], v["cfoRequired"]) == ("MEDIUM", "2026-10-03", False)
    for key, i in enumerate(unstarted.values(), start=1):
        reconciliation_db.record_started(conn, i, 9000 + key, rules)
    assert reconciliation_db.fetch_unstarted(conn) == []


def test_groups_start_with_the_team_and_a_large_bulk_total_needs_the_cfo(conn, db):
    assert recon_groups_db.create_groups(conn, date(2026, 9, 25)) == 3
    groups = {g["pattern"]: g for g in recon_groups_db.fetch_unstarted(conn)}
    assert {p: (g["cfo_required"], g["cfo_reason"]) for p, g in groups.items()} == {
        "+15.00": (False, None),
        "-9,000.00": (True, "a total difference of 27,000.00"),
        "missing in our data": (True, "a missing record"),
    }
    for key, g in enumerate(groups.values(), start=1):
        breaks = recon_groups_db.breaks_of(conn, g["group_id"])
        recon_groups_db.record_started(conn, g["group_id"], 8000 + key, recon_groups_db.title(g, breaks))
    db.execute("SELECT title FROM reconciliation_groups ORDER BY group_id")
    assert [t for (t,) in db.fetchall()] == ["4 accounts: balance 15.00 higher in core banking",
                                             "3 accounts: balance 9,000.00 lower in core banking",
                                             "Customer CB-EXTRA-001: in core banking but missing from our data"]


def test_every_task_is_filed_under_its_run_and_no_run_is_ready_yet(conn, db):
    recon_runs_db.sync_runs(conn)
    db.execute("SELECT source_system, run_key, status FROM reconciliation_runs ORDER BY source_system")
    assert db.fetchall() == [("CORE_CSV", NEW, "OPEN"), ("neon", "2026-09-25", "OPEN")]
    db.execute("SELECT count(*) FROM pipeline_reconciliation WHERE run_id IS NOT NULL")
    assert db.fetchone()[0] == 3                                  # the superseded item belongs to no run
    db.execute("SELECT count(*) FROM reconciliation_groups WHERE run_id IS NULL")
    assert db.fetchone()[0] == 0
    assert recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF) == []


# ---- the team's decision ----------------------------------------------------------------------------

def test_a_decision_is_refused_with_a_reason_the_team_can_act_on(conn, db, ids, users):
    refused = recon_tasks_db.record_decision(conn, "reconciliation", ids["pipe_transactions"], "CORRECT", users["analyst"])
    assert refused == {"decisionOk": False, "decisionError": "Enter at least one corrected value before choosing Assign to CFO."}
    assert not recon_tasks_db.record_decision(conn, "reconciliation", ids["pipe_transactions"], "ACCEPT", None)["decisionOk"]
    assert not recon_tasks_db.record_decision(conn, "reconciliation", ids["pipe_transactions"], "MAYBE", users["analyst"])["decisionOk"]
    missing = group_id(db, "missing in our data")
    assert "missing record can't be corrected" in recon_tasks_db.record_decision(conn, "recon_group", missing, "CORRECT", users["analyst"])["decisionError"]
    db.execute("SELECT exception_id FROM reconciliation_exceptions WHERE group_id = %s", (group_id(db, "+15.00"),))
    every = [e for (e,) in db.fetchall()]
    assert "Leave at least one" in recon_tasks_db.record_decision(conn, "recon_group", group_id(db, "+15.00"), "ACCEPT", users["analyst"], every)["decisionError"]
    assert status(db, "pipeline_reconciliation", "recon_id", ids["pipe_transactions"]) == "WITH_TEAM"   # nothing saved


def test_the_team_enters_a_corrected_value_on_a_rejected_row(client, auth, ids):
    r = client.get(f"{API}/reconciliation/pipeline/{ids['pipe_transactions']}/records", headers=auth).json()
    assert r["records"][0]["bad_field"] == "channel"
    assert r["summary"]["headline"] == "1,419 rows of Lebanon transactions arrived in the core banking delivery of 29 Sep 2026: 1,418 loaded, 1 rejected."
    assert r["summary"]["reasons"] == ["TN12: channel 'Cheque' is not one of Branch/ATM/Mobile/Online"]
    assert r["summary"]["money"] == "Not in our books because of this: USD 4,000.00."
    assert r["run"]["name"] == "core banking files of 29 Sep 2026"
    ok = client.post(f"{API}/reconciliation/pipeline/{ids['pipe_transactions']}/corrections", headers=auth,
                     json={"record_key": "TN12", "field_name": "channel", "new_value": "branch "})
    assert ok.status_code == 200
    fixes = client.get(f"{API}/reconciliation/pipeline/{ids['pipe_transactions']}/corrections", headers=auth).json()
    assert [f["new_value"] for f in fixes] == ["Branch"]          # stored the way the pipeline's check accepts it


@pytest.mark.parametrize("value, says", [
    ("Cheque", "the same as the rejected value"),                  # unchanged: it would be rejected again
    ("cheque ", "the same as the rejected value"),                 # ...whatever the case and spaces
    ("Telegraph", "must be one of ATM, Branch, Mobile, Online"),   # not a value the checks accept (found in QA 2026-10-01)
])
def test_a_fixed_value_the_pipeline_would_reject_again_is_refused(client, auth, ids, value, says):
    r = client.post(f"{API}/reconciliation/pipeline/{ids['pipe_transactions']}/corrections", headers=auth,
                    json={"record_key": "TN12", "field_name": "channel", "new_value": value})
    assert r.status_code == 400 and says in r.json()["detail"], r.text


def test_a_small_task_is_decided_by_the_team_alone(conn, db, ids, users):
    plus15 = group_id(db, "+15.00")
    assert recon_tasks_db.record_decision(conn, "recon_group", plus15, "ACCEPT", users["analyst"]) == \
        {"decisionOk": True, "decisionError": "", "needsCfo": False, "cfoReason": ""}
    assert status(db, "reconciliation_groups", "group_id", plus15) == "CLOSED"
    db.execute("SELECT DISTINCT status FROM reconciliation_exceptions WHERE group_id = %s", (plus15,))
    assert db.fetchall() == [("ACCEPTED",)]


def test_a_data_fix_always_needs_the_cfo_even_on_a_small_task(conn, db, ids, users):
    result = recon_tasks_db.record_decision(conn, "reconciliation", ids["pipe_transactions"], "CORRECT", users["analyst"])
    assert result == {"decisionOk": True, "decisionError": "", "needsCfo": True, "cfoReason": "a proposed data fix"}
    assert status(db, "pipeline_reconciliation", "recon_id", ids["pipe_transactions"]) == "AWAITING_CFO"


def test_values_are_locked_once_the_team_has_decided(client, auth, ids):
    r = client.post(f"{API}/reconciliation/pipeline/{ids['pipe_transactions']}/corrections", headers=auth,
                    json={"record_key": "TN12", "field_name": "channel", "new_value": "ATM"})
    assert r.status_code == 409 and "while the team is reviewing" in r.json()["detail"]


def test_an_important_task_needs_the_cfo_whatever_is_decided(conn, db, ids, users):
    for key in (ids["pipe_accounts"], ids["pipe_loans"]):
        result = recon_tasks_db.record_decision(conn, "reconciliation", key, "ACCEPT", users["risk"])
        assert result["needsCfo"] is True
    assert recon_tasks_db.record_decision(conn, "reconciliation", ids["pipe_accounts"], "ACCEPT", users["risk"])["decisionOk"]  # retry
    # A group fixed from core banking: the fix is core banking's value, tidied ("1000.00" not "1000.0000").
    minus9k = group_id(db, "-9,000.00")
    assert recon_tasks_db.record_decision(conn, "recon_group", minus9k, "CORRECT", users["analyst"])["cfoReason"] == \
        "a total difference of 27,000.00; a proposed data fix"
    db.execute("SELECT source_table, record_key, field_name, old_value, new_value, status FROM reconciliation_corrections WHERE group_id = %s ORDER BY record_key", (minus9k,))
    assert db.fetchall()[0] == ("accounts", "ACN0110", "balance", "10000.00", "1000", "PROPOSED")


# ---- the CFO's approval: never the person who decided, only the CFO or an admin ----------------------

def test_the_person_who_decided_cant_approve_and_only_the_cfo_or_an_admin_can(conn, db, ids, users):
    key = ids["pipe_transactions"]
    assert recon_tasks_db.approve(conn, "reconciliation", key, users["analyst"])["approvalError"] == \
        "Only the CFO or the Platform Administrator can approve; Reconciliation Analyst can't."
    db.execute("UPDATE pipeline_reconciliation SET decided_by = %s WHERE recon_id = %s", (users["approver"], key))
    assert recon_tasks_db.approve(conn, "reconciliation", key, users["approver"])["approvalError"] == \
        "CFO made this decision, so a different person has to approve it."
    db.execute("UPDATE pipeline_reconciliation SET decided_by = %s WHERE recon_id = %s", (users["analyst"], key))
    assert status(db, "pipeline_reconciliation", "recon_id", key) == "AWAITING_CFO"          # still waiting


def test_the_cfo_approves_and_the_fix_is_approved_with_it(conn, db, ids, users):
    key = ids["pipe_transactions"]
    assert recon_tasks_db.approve(conn, "reconciliation", key, users["approver"]) == {"approvalOk": True, "approvalError": ""}
    assert recon_tasks_db.approve(conn, "reconciliation", key, users["approver"])["approvalOk"]   # a retried job
    db.execute("SELECT status, approved_by FROM reconciliation_corrections WHERE recon_id = %s", (key,))
    assert db.fetchall() == [("APPROVED", users["approver"])]
    db.execute("SELECT action FROM audit_log WHERE object_type IN ('reconciliation_item', 'reconciliation_correction') ORDER BY log_id")
    actions = [a for (a,) in db.fetchall()]
    assert actions.count("CORRECTION_APPROVED") == 1 and "APPROVED" in actions and "DECIDED" in actions


def test_the_cfo_sends_a_decision_back_and_the_team_decides_again(conn, db, users):
    minus9k = group_id(db, "-9,000.00")
    shown = recon_tasks_db.send_back(conn, "recon_group", minus9k, users["approver"], "These are fee reversals, not errors")
    # What the team's task shows: who, from which step, when and why; and the reason in the group's comments.
    assert (shown["sentBackByName"], shown["sentBackFrom"], shown["sentBackNote"]) == ("CFO", "CFO_APPROVAL", "These are fee reversals, not errors")
    assert shown["sentBackAt"]
    db.execute("SELECT comment_text FROM comments WHERE source_table = 'reconciliation_groups' AND record_key = %s", (str(minus9k),))
    assert db.fetchall() == [("Sent back at CFO approval: These are fee reversals, not errors",)]
    assert status(db, "reconciliation_groups", "group_id", minus9k) == "OPEN"
    db.execute("SELECT DISTINCT status FROM reconciliation_corrections WHERE group_id = %s", (minus9k,))
    assert db.fetchall() == [("WITHDRAWN",)]
    db.execute("SELECT new_value FROM audit_log WHERE action = 'SENT_BACK' AND object_id = %s", (str(minus9k),))
    assert db.fetchone()[0] == "These are fee reversals, not errors"
    # The reviewer can type the fixed values themselves instead of taking core banking's.
    db.execute("SELECT exception_id FROM reconciliation_exceptions WHERE group_id = %s ORDER BY entity_id", (minus9k,))
    first, second, _third = [e for (e,) in db.fetchall()]
    for values, why in (({first: ""}, "Enter the fixed value for account ACN0110."),
                        ({first: "about 9k"}, "balance is a number: enter a number for account ACN0110."),
                        ({second: "10,000.00"}, "The fixed value for account ACN0111 is the same as ours: change it, or leave the record out.")):
        assert recon_tasks_db.record_decision(conn, "recon_group", minus9k, "CORRECT", users["analyst"], [], values) == \
            {"decisionOk": False, "decisionError": why}
    assert recon_tasks_db.record_decision(conn, "recon_group", minus9k, "CORRECT", users["analyst"], [], {str(first): "9,500.50"})["decisionOk"]
    db.execute("SELECT record_key, new_value FROM reconciliation_corrections WHERE group_id = %s AND status = 'PROPOSED' ORDER BY record_key", (minus9k,))
    assert db.fetchall() == [("ACN0110", "9500.5"), ("ACN0111", "1000"), ("ACN0112", "1000")]    # edited, then core banking's
    recon_tasks_db.send_back(conn, "recon_group", minus9k, users["approver"], "Keep our balances")
    assert recon_tasks_db.record_decision(conn, "recon_group", minus9k, "ACCEPT", users["analyst"])["needsCfo"] is True
    assert recon_tasks_db.approve(conn, "recon_group", minus9k, users["admin"])["approvalOk"]
    db.execute("SELECT DISTINCT status, resolved_by FROM reconciliation_exceptions WHERE group_id = %s", (minus9k,))
    assert db.fetchall() == [("ACCEPTED", users["analyst"])]


def test_a_run_is_ready_for_sign_off_only_once_every_task_is_decided(conn, db, ids, users):
    assert recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF) == []                                 # two important items and one group wait for the CFO
    for key in (ids["pipe_accounts"], ids["pipe_loans"]):
        assert recon_tasks_db.approve(conn, "reconciliation", key, users["approver"])["approvalOk"]
    missing = group_id(db, "missing in our data")
    recon_tasks_db.record_decision(conn, "recon_group", missing, "DISMISS", users["approver"])      # the CFO decides this one
    assert recon_tasks_db.approve(conn, "recon_group", missing, users["admin"])["approvalOk"]
    recon_runs_db.sync_runs(conn)
    ready = {r["source_system"]: r for r in recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF)}
    assert set(ready) == {"CORE_CSV", "neon"}
    assert recon_runs_db.title(ready["neon"]) == "Sign off the core banking comparison of 25 Sep 2026"
    assert recon_runs_db.process_variables(ready["CORE_CSV"])["title"] == "Sign off the core banking files of 29 Sep 2026"
    for key, r in enumerate(ready.values(), start=1):
        recon_runs_db.record_started(conn, r["run_id"], 7000 + key)
    assert recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF) == []


def test_the_sign_off_popup_lists_every_decision(client, auth, db):
    runs = {r["source_system"]: r for r in client.get(f"{API}/reconciliation/runs", headers=auth).json()}
    assert (runs["neon"]["tasks"], runs["neon"]["decided"], runs["neon"]["status"]) == (3, 3, "IN_SIGNOFF")
    detail = client.get(f"{API}/reconciliation/runs/{runs['neon']['run_id']}", headers=auth).json()
    assert detail["summary"]["headline"] == "All 3 tasks from the core banking comparison of 25 Sep 2026 are decided: 2 accepted, 1 dismissed."
    assert [t["cfo_required"] for t in detail["tasks"]] == [True, True, False]     # important ones first
    group = client.get(f"{API}/reconciliation/groups/{detail['tasks'][-1]['id']}", headers=auth).json()
    assert group["summary"]["headline"] == "4 accounts have a balance 15.00 higher in core banking than in our data (60.00 in total)."
    assert group["decided_by_name"] == "Reconciliation Analyst" and group["run"]["status"] == "IN_SIGNOFF"


# ---- run sign-off: never by anyone who decided a task in the run ------------------------------------

def test_sign_off_is_refused_for_anyone_who_decided_a_task_or_isnt_the_cfo(conn, db, users):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE source_system = 'neon'")
    neon = db.fetchone()[0]
    assert "Only the CFO or the Platform Administrator" in recon_runs_db.close_run(conn, neon, users["risk"])["signoffError"]
    assert recon_runs_db.close_run(conn, neon, users["approver"])["signoffError"] == \
        "CFO decided 1 task(s) in this run, so a different person has to sign it off."
    assert recon_runs_db.close_run(conn, neon, users["admin"], "All explained", BEFORE_CUTOFF) == {"signoffOk": True, "signoffError": ""}
    assert recon_runs_db.close_run(conn, neon, users["admin"])["signoffOk"]            # a retried job
    db.execute("SELECT status, sign_note FROM reconciliation_runs WHERE run_id = %s", (neon,))
    assert db.fetchone() == ("SIGNED_OFF", "All explained")


def test_the_cfo_sends_named_tasks_back_and_they_reopen_in_the_same_run(conn, db, ids, users):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE source_system = 'CORE_CSV'")
    run = db.fetchone()[0]
    key = ids["pipe_transactions"]
    assert recon_runs_db.send_back_run(conn, run, users["approver"], [{"kind": "reconciliation", "id": key}], "")["signoffError"] == \
        "Say why the tasks are being sent back."
    assert recon_runs_db.send_back_run(conn, run, users["approver"], [{"kind": "reconciliation", "id": 99999}], "why")["signoffError"] == \
        "Item #99999 isn't a decided task of this run."
    assert recon_runs_db.send_back_run(conn, run, users["approver"], [{"kind": "reconciliation", "id": key}],
                                       "Branch is wrong, it was an ATM deposit") == {"signoffOk": True, "signoffError": ""}
    assert status(db, "pipeline_reconciliation", "recon_id", key) == "OPEN"
    assert status(db, "reconciliation_runs", "run_id", run) == "OPEN"
    db.execute("SELECT status FROM reconciliation_corrections WHERE recon_id = %s", (key,))
    assert db.fetchall() == [("WITHDRAWN",)]                                 # not applied yet, so withdrawn
    reopened = reconciliation_db.fetch_unstarted(conn)
    assert [i["recon_id"] for i in reopened] == [key]                         # the bridge starts it again...
    rules, due_days = reconciliation_db.rules(conn)
    v = reconciliation_db.process_variables(reopened[0], rules, due_days)
    assert (v["sentBackByName"], v["sentBackFrom"], v["sentBackNote"]) == ("CFO", "RUN_SIGNOFF", "Branch is wrong, it was an ATM deposit")
    db.execute("SELECT comment_text FROM comments WHERE source_table = 'pipeline_reconciliation' AND record_key = %s", (str(key),))
    assert db.fetchall()[-1] == ("Sent back at run sign-off: Branch is wrong, it was an ATM deposit",)   # ...saying why
    assert recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF) == []


def test_the_reconciliation_tab_counts_what_was_sent_back(client, auth):
    runs = {r["source_system"]: r for r in client.get(f"{API}/reconciliation/runs", headers=auth).json()}
    assert runs["CORE_CSV"]["sent_back"] == 1


def test_a_new_comparison_during_sign_off_starts_a_follow_on_run(conn, db, users):
    db.execute("""INSERT INTO reconciliation_exceptions (source_system, entity_type, entity_id, field_name, source_value,
                  canonical_value, mismatch_type, status, detected_at, first_seen, last_seen)
                  VALUES ('neon', 'account', 'ACN0999', 'balance', '5.00', '1.00', 'VALUE_MISMATCH', 'OPEN', %s, %s, %s)""",
               (SEEN, SEEN, SEEN))
    recon_groups_db.create_groups(conn, date(2026, 9, 25))
    recon_runs_db.sync_runs(conn)
    db.execute("SELECT run_key, status FROM reconciliation_runs WHERE source_system = 'neon' ORDER BY run_id")
    assert db.fetchall() == [("2026-09-25", "SIGNED_OFF"), ("2026-09-25#2", "OPEN")]
    db.execute("SELECT * FROM reconciliation_runs WHERE run_key = '2026-09-25#2'")
    cols = [c.name for c in db.description]
    assert recon_runs_db.title(dict(zip(cols, db.fetchone()))) == "Sign off the core banking comparison of 25 Sep 2026 (part 2)"


def test_comments_can_be_left_on_a_run_sign_off(client, auth, db):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE source_system = 'CORE_CSV'")
    body = {"source_table": "reconciliation_runs", "record_key": str(db.fetchone()[0]), "flag_label": "RECON_RUN", "comment_text": "Checked"}
    assert client.post(f"{API}/workflow/exceptions/comments", headers=auth, json=body).status_code == 200


# ---- early-morning sign-off: sign off what's decided, carry the rest (section 7) -----------------------

def test_from_the_cut_off_a_run_with_open_tasks_goes_to_sign_off(conn, db):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE source_system = 'CORE_CSV'")
    run = db.fetchone()[0]                        # 2 tasks approved, the transactions gap reopened (open)
    assert run not in [r["run_id"] for r in recon_runs_db.fetch_ready(conn, BEFORE_CUTOFF)]
    assert run in [r["run_id"] for r in recon_runs_db.fetch_ready(conn, AFTER_CUTOFF)]    # 08:00 on 30 Sep has passed
    recon_runs_db.record_started(conn, run, 7101)


def test_signing_off_with_open_tasks_needs_the_cut_off_and_a_reason(conn, db, users):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE source_system = 'CORE_CSV'")
    run = db.fetchone()[0]
    assert recon_runs_db.close_run(conn, run, users["admin"], "why", BEFORE_CUTOFF)["signoffError"] == \
        "1 task(s) aren't decided yet. Before the 08:00 cut-off a run is signed off only once every task is decided."
    assert recon_runs_db.close_run(conn, run, users["admin"], "", AFTER_CUTOFF)["signoffError"] == \
        "Say why the 1 open task(s) are carried over to the next day."
    db.execute("UPDATE pipeline_reconciliation SET status = 'AWAITING_CFO' WHERE run_id = %s AND status = 'OPEN'", (run,))
    assert recon_runs_db.close_run(conn, run, users["admin"], "why", AFTER_CUTOFF)["signoffError"] == \
        "Approve or send back the 1 task(s) waiting for you first."        # the CFO's own approvals can't be carried
    db.execute("UPDATE pipeline_reconciliation SET status = 'OPEN' WHERE run_id = %s AND status = 'AWAITING_CFO'", (run,))


def test_the_cfo_signs_off_the_decided_tasks_and_the_open_one_is_carried(client, auth, conn, db, ids, users):
    db.execute("SELECT run_id, run_date FROM reconciliation_runs WHERE source_system = 'CORE_CSV'")
    run, run_date = db.fetchone()
    assert recon_runs_db.close_run(conn, run, users["admin"], "Waiting on core banking ops", AFTER_CUTOFF) == \
        {"signoffOk": True, "signoffError": ""}
    db.execute("SELECT status, signed_tasks, carried_tasks, carried_to_run_id FROM reconciliation_runs WHERE run_id = %s", (run,))
    status_, signed, carried, carry_run = db.fetchone()
    assert (status_, signed, carried) == ("SIGNED_OFF", 2, 1)
    db.execute("SELECT run_key, run_date, status FROM reconciliation_runs WHERE run_id = %s", (carry_run,))
    assert db.fetchone() == (f"{NEW}#c1", date(2026, 9, 30), "OPEN")          # today, bank time
    db.execute("SELECT run_id, carried_count, carried_since, escalated_at FROM pipeline_reconciliation WHERE recon_id = %s",
               (ids["pipe_transactions"],))
    assert db.fetchone() == (carry_run, 1, run_date, None)
    recon_runs_db.sync_runs(conn)
    db.execute("SELECT status FROM reconciliation_runs WHERE run_id = %s", (carry_run,))
    assert db.fetchone()[0] == "OPEN"                                            # the delivery's carry-over run stays
    assert client.get(f"{API}/reconciliation/carried", headers=auth).json()["reconciliation"] == {
        str(ids["pipe_transactions"]): {"carried_count": 1, "carried_since": run_date.isoformat(), "escalated": False}}
    runs = {r["source_system"]: r for r in client.get(f"{API}/reconciliation/runs", headers=auth).json()}
    assert (runs["CORE_CSV"]["run_id"], runs["CORE_CSV"]["carried_in"], runs["CORE_CSV"]["name"]) == \
        (carry_run, 1, "core banking files of 30 Sep 2026 (carried over)")
    signed_off = client.get(f"{API}/reconciliation/runs/{run}", headers=auth).json()
    assert (signed_off["signed_tasks"], signed_off["carried_tasks"]) == (2, 1)
    # ...and the audit trail has the sign-off, by whom and with the note, and one row per carried task
    db.execute("""SELECT action, user_id, new_value FROM audit_log WHERE action IN ('RUN_SIGNED_OFF', 'CARRIED_OVER')
                  AND (object_id = %s OR object_id = %s) ORDER BY log_id""", (f"CORE_CSV:{NEW}", str(ids["pipe_transactions"])))
    assert db.fetchall() == [("CARRIED_OVER", users["admin"], "carried 1x"),
                             ("RUN_SIGNED_OFF", users["admin"], "2 signed off, 1 carried over: Waiting on core banking ops")]


def test_a_task_carried_three_times_is_escalated(conn, db, ids, users):
    db.execute("SELECT run_id FROM reconciliation_runs WHERE run_key = %s", (f"{NEW}#c1",))
    carry_run = db.fetchone()[0]
    db.execute("UPDATE pipeline_reconciliation SET carried_count = 2 WHERE recon_id = %s", (ids["pipe_transactions"],))
    next_morning = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)
    assert carry_run in [r["run_id"] for r in recon_runs_db.fetch_ready(conn, next_morning)]
    recon_runs_db.record_started(conn, carry_run, 7102)
    assert recon_runs_db.close_run(conn, carry_run, users["admin"], "Still waiting", next_morning)["signoffOk"]
    db.execute("SELECT carried_count, escalated_at IS NOT NULL FROM pipeline_reconciliation WHERE recon_id = %s", (ids["pipe_transactions"],))
    assert db.fetchone() == (3, True)
    db.execute("SELECT new_value FROM audit_log WHERE action = 'ESCALATED' AND object_id = %s", (str(ids["pipe_transactions"]),))
    assert db.fetchone()[0] == "carried 3 times without a decision"
    db.execute("SELECT run_key FROM reconciliation_runs WHERE run_id = (SELECT run_id FROM pipeline_reconciliation WHERE recon_id = %s)",
               (ids["pipe_transactions"],))
    assert db.fetchone()[0] == f"{NEW}#c2"
