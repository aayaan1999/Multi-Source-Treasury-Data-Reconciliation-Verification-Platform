"""Pipeline reconciliation per source (specs/pipeline-reconciliation.md, FLOW-3): the list of
received-vs-kept items and the rejected records behind each one."""
from datetime import datetime, timezone

import psycopg2.extras
import pytest

API = "/api/v1"
OLD, NEW, ERP = "CORE_CSV-20260923T100000Z-aaaa0001", "CORE_CSV-20260924T100000Z-bbbb0002", "LB_ERP-20260924T090000Z-cccc0003"
T_OLD = datetime(2026, 9, 23, 10, tzinfo=timezone.utc)
T_NEW = datetime(2026, 9, 24, 10, tzinfo=timezone.utc)


def _item(batch, system, country, table, received, kept, amounts, detected):
    rejected = received - kept
    gap = rejected > 0 or any(abs(v["gap"]) > 0.005 for v in (amounts or {}).values())
    return (f"{batch}|{system}|{country}|{table}", batch, system, country, table, received, kept, rejected,
            "amount" if amounts else None, 0, psycopg2.extras.Json(amounts) if amounts else None,
            gap, "OPEN" if gap else "MATCHED", detected)


@pytest.fixture(scope="module")
def items(db):
    rows = [
        # An older run of CORE_CSV: history, hidden by default.
        _item(OLD, "CORE_CSV", "Lebanon", "transactions", 6, 4, {"USD": {"received": 100.0, "clean": 60.0, "gap": 40.0}}, T_OLD),
        # The newest CORE_CSV run.
        _item(NEW, "CORE_CSV", "Lebanon", "transactions", 6, 5,
              {"USD": {"received": 64800.0, "clean": 63800.0, "gap": 1000.0}, "LBP": {"received": 2e6, "clean": 2e6, "gap": 0.0}}, T_NEW),
        _item(NEW, "CORE_CSV", "Qatar", "transactions", 2, 2, {"QAR": {"received": 30000.0, "clean": 30000.0, "gap": 0.0}}, T_NEW),
        _item(NEW, "CORE_CSV", "Lebanon", "customers", 5, 3, None, T_NEW),
        # A second source, one run.
        _item(ERP, "LB_ERP", "Lebanon", "accounts", 4, 4, {"USD": {"received": 10.0, "clean": 10.0, "gap": 0.0}}, T_NEW),
    ]
    db.executemany(
        """INSERT INTO pipeline_reconciliation (recon_key, ingest_batch_id, source_system, source_country, source_table,
               received_rows, clean_rows, rejected_rows, amount_column, unreadable_amount_rows, amounts_by_currency,
               has_gap, status, detected_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        rows,
    )
    # The exceptions log holds the newest run only; one reject is from another country, to prove the filter.
    db.executemany(
        """INSERT INTO data_quality_exceptions (source_table, record_key, flag_label, description,
               source_system, source_country, ingest_batch_id, source_file) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
        [("transactions", "T0009", "INVALID_CHANNEL", "channel 'Cheque' is not valid", "CORE_CSV", "Lebanon", NEW, "transactions.csv"),
         ("transactions", "T0009", "ORPHAN_ACCOUNT", "account_id 'ACC004' has no match", "CORE_CSV", "Lebanon", NEW, "transactions.csv"),
         ("transactions", "T0010", "ORPHAN_ACCOUNT", "account_id 'ACC999' has no match", "CORE_CSV", "Unknown", NEW, "transactions.csv"),
         ("customers", "C004", "MISSING_RISK_RATING", "risk_rating is missing", "CORE_CSV", "Lebanon", NEW, "customers.csv")],
    )
    db.execute("SELECT recon_key, recon_id FROM pipeline_reconciliation")
    ids = {key: rid for key, rid in db.fetchall()}
    yield ids
    db.execute("DELETE FROM pipeline_reconciliation")
    db.execute("DELETE FROM data_quality_exceptions WHERE ingest_batch_id IS NOT NULL")


def _id(ids, batch, system, country, table):
    return ids[f"{batch}|{system}|{country}|{table}"]


def test_default_list_is_each_sources_newest_run_with_gaps_first(client, auth, items):
    rows = client.get(f"{API}/reconciliation/pipeline", headers=auth).json()
    assert {r["ingest_batch_id"] for r in rows} == {NEW, ERP}                  # the older CORE_CSV run is history
    assert [r["has_gap"] for r in rows] == sorted((r["has_gap"] for r in rows), reverse=True)
    top = rows[0]
    assert (top["source_country"], top["source_table"], top["rejected_rows"]) == ("Lebanon", "customers", 2)


def test_amounts_come_back_per_currency_never_summed(client, auth, items):
    rows = client.get(f"{API}/reconciliation/pipeline?source_table=transactions&source_country=Lebanon", headers=auth).json()
    assert len(rows) == 1
    assert rows[0]["amounts_by_currency"]["USD"] == {"received": 64800.0, "clean": 63800.0, "gap": 1000.0}
    assert set(rows[0]["amounts_by_currency"]) == {"USD", "LBP"}


def test_history_and_filters(client, auth, items):
    everything = client.get(f"{API}/reconciliation/pipeline?latest_only=false", headers=auth).json()
    assert len(everything) == 5
    gaps = client.get(f"{API}/reconciliation/pipeline?gaps_only=true", headers=auth).json()
    assert {(r["source_country"], r["source_table"]) for r in gaps} == {("Lebanon", "transactions"), ("Lebanon", "customers")}
    erp = client.get(f"{API}/reconciliation/pipeline?source_system=LB_ERP", headers=auth).json()
    assert [r["status"] for r in erp] == ["MATCHED"]


def test_an_item_opens_onto_exactly_its_own_rejected_records(client, auth, items):
    body = client.get(f"{API}/reconciliation/pipeline/{_id(items, NEW, 'CORE_CSV', 'Lebanon', 'transactions')}/records", headers=auth).json()
    assert body["records_available"] is True
    # T0009's two flags; T0010 is the same run and table but another country, so it isn't here.
    assert [(r["record_key"], r["flag_label"]) for r in body["records"]] == [("T0009", "INVALID_CHANNEL"), ("T0009", "ORPHAN_ACCOUNT")]
    assert body["item"]["rejected_rows"] == 1


def test_an_older_runs_item_says_its_detail_is_gone_instead_of_showing_another_runs(client, auth, items):
    body = client.get(f"{API}/reconciliation/pipeline/{_id(items, OLD, 'CORE_CSV', 'Lebanon', 'transactions')}/records", headers=auth).json()
    assert body["records"] == [] and body["records_available"] is False


def test_a_matched_item_has_nothing_to_show_and_says_so_plainly(client, auth, items):
    body = client.get(f"{API}/reconciliation/pipeline/{_id(items, NEW, 'CORE_CSV', 'Qatar', 'transactions')}/records", headers=auth).json()
    assert body["records"] == [] and body["records_available"] is True


def test_unknown_item_is_404_and_login_is_required(client, auth, items):
    assert client.get(f"{API}/reconciliation/pipeline/999999/records", headers=auth).status_code == 404
    assert client.get(f"{API}/reconciliation/pipeline").status_code == 401
