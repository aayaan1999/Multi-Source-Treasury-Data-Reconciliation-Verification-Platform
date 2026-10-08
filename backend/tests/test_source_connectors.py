"""Source connectors on the Data Ingestion screen (app/connectors.py, ING-1): connect, test, disconnect,
sync and "Run All Sources" - and that a secret never reaches Postgres or the audit log."""
import pytest

from app import connectors
from app.routers import refresh

API = "/api/v1"
SALESFORCE = {"instance_url": "https://bankx.my.salesforce.com", "client_id": "3MVG9abc", "client_secret": "cs-SECRET-1"}


def login(client, email):
    from conftest import PASSWORD
    token = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def admin(client, db):
    headers = login(client, "admin@bankx.demo")
    yield headers
    db.execute("DELETE FROM source_connectors")


@pytest.fixture
def no_databricks(monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)


def sources(client, headers):
    return {s["key"]: s for s in client.get(f"{API}/ingestion/overview", headers=headers).json()["connectors"]["items"]}


def test_every_source_starts_disconnected_except_the_core_banking_files(client, admin):
    items = sources(client, admin)
    assert list(items) == ["core_files", "salesforce", "postgresql", "rest_api", "aws_s3", "snowflake"]
    assert items["core_files"]["status"] == "connected" and items["core_files"]["builtin"]
    assert all(items[k]["status"] == "disconnected" for k in items if k != "core_files")
    fields = {f["key"]: f for f in items["salesforce"]["fields"]}
    assert list(fields) == ["instance_url", "client_id", "client_secret"]      # client credentials: no user password
    assert fields["instance_url"]["kind"] == "url" and fields["client_secret"]["kind"] == "secret"


def test_connect_saves_settings_but_never_a_secret(client, admin, db, no_databricks):
    r = client.post(f"{API}/ingestion/sources/salesforce/connect", headers=admin, json={"values": SALESFORCE})
    assert r.status_code == 200
    card = r.json()["source"]
    assert card["status"] == "connected" and card["detail"] == "https://bankx.my.salesforce.com"
    assert card["config"] == {"instance_url": "https://bankx.my.salesforce.com", "client_id": "3MVG9abc"}
    assert card["secret_fields"] == ["client_secret"] and card["credentials"] == "not_stored"
    assert "not stored anywhere" in r.json()["message"]
    db.execute("SELECT count(*) FROM source_connectors WHERE config::text LIKE '%SECRET%' OR secret_fields::text LIKE '%SECRET%'")
    assert db.fetchone()[0] == 0
    db.execute("SELECT count(*) FROM audit_log WHERE new_value LIKE '%SECRET%'")
    assert db.fetchone()[0] == 0
    db.execute("SELECT count(*) FROM audit_log WHERE action = 'SOURCE_CONNECTED' AND object_id = 'salesforce'")
    assert db.fetchone()[0] >= 1
    assert sources(client, admin)["salesforce"]["status"] == "connected"


@pytest.fixture
def fake_databricks(monkeypatch):
    """A secret scope held in a dict, behind the same _api calls the app makes."""
    monkeypatch.setenv("DATABRICKS_HOST", "https://adb-1.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    scope = {"salesforce-password": "left over from the old form", "neon-host": "other source"}

    def fake_api(method, path, body=None):
        if path.endswith("scopes/create"):
            raise refresh.HTTPException(502, "Databricks refused the request (400): Scope bank-data-sources already exists!")
        if path.endswith("secrets/put"):
            assert body["scope"] == connectors.SECRET_SCOPE
            scope[body["key"]] = body["string_value"]
        elif path.endswith("secrets/delete"):
            scope.pop(body["key"])
        elif "secrets/list" in path:
            return {"secrets": [{"key": k} for k in scope]}
        return {}

    monkeypatch.setattr(refresh, "_api", fake_api)
    return scope


def test_with_databricks_connected_everything_the_notebook_needs_goes_to_its_secret_scope(client, admin, fake_databricks):
    r = client.post(f"{API}/ingestion/sources/salesforce/connect", headers=admin, json={"values": SALESFORCE})
    assert r.json()["source"]["credentials"] == "databricks"
    # the notebook reads these three; the old form's password is removed; other sources are untouched
    assert fake_databricks == {"salesforce-instance_url": "https://bankx.my.salesforce.com", "salesforce-client_id": "3MVG9abc",
                               "salesforce-client_secret": "cs-SECRET-1", "neon-host": "other source"}
    client.delete(f"{API}/ingestion/sources/salesforce", headers=admin)
    assert fake_databricks == {"neon-host": "other source"}                       # disconnect leaves nothing behind


def test_the_form_is_checked_on_the_server_too(client, admin, no_databricks):
    def connect(values, key="salesforce"):
        return client.post(f"{API}/ingestion/sources/{key}/connect", headers=admin, json={"values": values})
    missing = connect({**SALESFORCE, "client_secret": "  "})
    assert missing.status_code == 422 and "Consumer secret is required" in missing.json()["detail"]
    assert "https://" in connect({**SALESFORCE, "instance_url": "http://plain.example.com"}).json()["detail"]
    assert connect({**SALESFORCE, "sql": "DROP TABLE x"}).status_code == 422
    assert "65535" in connect({"host": "db", "port": "99999", "database": "d", "username": "u", "password": "p"}, "postgresql").json()["detail"]
    assert connect({}, "core_files").status_code == 409
    assert connect(SALESFORCE, "nosuch").status_code == 404


def test_test_connection_checks_the_details_and_says_it_was_not_a_live_sign_in(client, admin):
    r = client.post(f"{API}/ingestion/sources/aws_s3/test", headers=admin,
                    json={"values": {"bucket": "b", "region": "me-central-1", "access_key_id": "AKIA1", "secret_access_key": "s"}})
    assert r.json()["ok"] is True and r.json()["live"] is False and "isn't enabled" in r.json()["message"]
    assert client.post(f"{API}/ingestion/sources/aws_s3/test", headers=admin, json={"values": {}}).status_code == 422


def test_disconnect(client, admin, no_databricks):
    client.post(f"{API}/ingestion/sources/salesforce/connect", headers=admin, json={"values": SALESFORCE})
    assert client.delete(f"{API}/ingestion/sources/salesforce", headers=admin).json()["source"]["status"] == "disconnected"
    assert client.delete(f"{API}/ingestion/sources/core_files", headers=admin).status_code == 409


def test_run_all_and_sync_start_the_pipeline_job(client, admin, monkeypatch, no_databricks):
    assert client.post(f"{API}/ingestion/run", headers=admin).status_code == 503        # not connected to Databricks
    monkeypatch.setenv("DATABRICKS_HOST", "https://adb-1.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.setattr(refresh, "refresh_now", lambda user: {"run_id": 42})
    assert client.post(f"{API}/ingestion/run", headers=admin).json() == {"run_id": 42, "message": "Databricks ingestion pipeline started"}
    assert client.post(f"{API}/ingestion/sources/snowflake/sync", headers=admin).status_code == 409   # not connected yet
    assert client.post(f"{API}/ingestion/sources/core_files/sync", headers=admin).json()["run_id"] == 42


def test_only_the_cfo_or_an_admin_can_connect_or_run(client):
    analyst = login(client, "recon.analyst@bankx.demo")          # sees Data ingestion, read only
    assert client.post(f"{API}/ingestion/sources/salesforce/connect", headers=analyst, json={"values": SALESFORCE}).status_code == 403
    assert client.post(f"{API}/ingestion/run", headers=analyst).status_code == 403
    assert client.delete(f"{API}/ingestion/sources/salesforce", headers=analyst).status_code == 403


def test_loads_recorded_by_source_notebooks_appear_under_recent_ingestions(client, admin, db):
    db.execute("""INSERT INTO ingestion_runs (source_key, data_name, status, rows_received, message)
                  VALUES ('salesforce', 'Account', 'success', 13, '13 Accounts loaded'),
                         ('salesforce', 'Account', 'failed', 0, 'Salesforce refused the sign-in (400): invalid_client')""")
    try:
        items = client.get(f"{API}/ingestion/overview", headers=admin).json()["recent"]["items"]
        salesforce = [r for r in items if r["source"] == "Salesforce"]
        assert {(r["status"], r["received"]) for r in salesforce} == {("success", 13), ("failed", 0)}
        assert any("invalid_client" in (r["reason"] or "") for r in salesforce)
    finally:
        db.execute("DELETE FROM ingestion_runs")


# ---- PostgreSQL (core banking): Test connection signs in for real -----------------------------------------
@pytest.fixture
def core_banking(db, monkeypatch):
    """A second database on the test server standing in for the core banking system, and the Connect form for it."""
    from urllib.parse import urlparse
    import os
    import psycopg2
    monkeypatch.setattr(connectors, "CORE_BANKING_SSL", "disable")          # the local test server has no SSL
    db.execute("DROP DATABASE IF EXISTS corebanking")
    db.execute("CREATE DATABASE corebanking")
    url = urlparse(os.environ["DATABASE_URL"])
    conn = psycopg2.connect(host=url.hostname, port=url.port, user=url.username, dbname="corebanking")
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("""CREATE TABLE customers (customer_id text, name text, segment text, risk_rating text, branch_id text, extra text);
                   CREATE TABLE accounts (account_id text, customer_id text, type text, currency text, balance numeric);
                   INSERT INTO customers VALUES ('C1', 'A', 'Retail', 'A', 'B1', NULL), ('C2', 'B', 'SME', 'B', 'B1', NULL);
                   INSERT INTO accounts VALUES ('A1', 'C1', 'Current', 'USD', 10)""")
    form = {"host": url.hostname, "port": str(url.port), "database": "corebanking", "username": url.username, "password": "pw"}
    yield form, cur
    conn.close()
    db.execute("DROP DATABASE IF EXISTS corebanking WITH (FORCE)")


def test_postgresql_test_connection_signs_in_and_counts_what_the_pipeline_will_read(client, admin, core_banking):
    form, _ = core_banking
    r = client.post(f"{API}/ingestion/sources/postgresql/test", headers=admin, json={"values": form}).json()
    assert r["ok"] is True and r["live"] is True
    assert r["message"] == f"Signed in to {form['host']}/corebanking: found 2 customers and 1 accounts."
    assert "pw" not in r["message"]


def test_postgresql_test_connection_names_what_is_missing(client, admin, core_banking):
    form, cur = core_banking
    cur.execute("ALTER TABLE accounts DROP COLUMN balance")
    r = client.post(f"{API}/ingestion/sources/postgresql/test", headers=admin, json={"values": form}).json()
    assert r["ok"] is False and r["live"] is True and "accounts has no balance" in r["message"]
    cur.execute("DROP TABLE customers")
    assert "no customers table" in client.post(f"{API}/ingestion/sources/postgresql/test", headers=admin, json={"values": form}).json()["message"]


def test_postgresql_test_connection_reports_a_failed_sign_in(client, admin, core_banking):
    form, _ = core_banking
    r = client.post(f"{API}/ingestion/sources/postgresql/test", headers=admin,
                    json={"values": {**form, "database": "no_such_db"}}).json()
    assert r["ok"] is False and r["live"] is True
    assert r["message"].startswith(f"Couldn't sign in to {form['host']}/no_such_db:") and "no_such_db" in r["message"]


def test_postgresql_refuses_the_apps_own_database(client, admin, core_banking, no_databricks):
    form, _ = core_banking
    own = {**form, "database": "postgres"}                     # the database DATABASE_URL points at
    r = client.post(f"{API}/ingestion/sources/postgresql/test", headers=admin, json={"values": own}).json()
    assert r["ok"] is False and "this app's own database" in r["message"]
    c = client.post(f"{API}/ingestion/sources/postgresql/connect", headers=admin, json={"values": own})
    assert c.status_code == 422 and "this app's own database" in c.json()["detail"]
    assert connectors.is_app_database({"host": "ep-x-pooler.eu.aws.neon.tech", "database": "db"}) is False


def test_postgresql_connect_hands_the_notebook_its_settings(client, admin, core_banking, fake_databricks):
    form, _ = core_banking
    r = client.post(f"{API}/ingestion/sources/postgresql/connect", headers=admin, json={"values": form})
    assert r.status_code == 200 and r.json()["source"]["credentials"] == "databricks"
    # exactly the keys notebooks/multi_source_neon_ingestion.py reads
    assert {k: v for k, v in fake_databricks.items() if k.startswith("postgresql-")} == {
        "postgresql-host": form["host"], "postgresql-port": form["port"], "postgresql-database": "corebanking",
        "postgresql-username": form["username"], "postgresql-password": "pw"}


def test_core_banking_loads_show_as_database_runs(client, admin, db):
    db.execute("""INSERT INTO ingestion_runs (source_key, data_name, status, rows_received, message)
                  VALUES ('postgresql', 'customers', 'success', 200, '200 customers loaded')""")
    try:
        items = client.get(f"{API}/ingestion/overview", headers=admin).json()["recent"]["items"]
        assert [(r["type"], r["data"], r["received"]) for r in items if r["source"] == "PostgreSQL"] == [("Database", "customers", 200)]
    finally:
        db.execute("DELETE FROM ingestion_runs")


# ---- REST API (loan origination system): Test connection calls the API for real -------------------------
LOS = {"base_url": "https://abc.supabase.co/rest/v1", "endpoint": "/loans", "auth_header": "apikey", "api_key": "sb_publishable_SECRET"}
LOAN = {"loan_id": "L001", "customer_id": "C001", "product": "Corporate", "principal": 1000000, "outstanding": 800000,
        "currency": "USD", "interest_rate": 6.5, "maturity_date": "2026-01-10"}


@pytest.fixture
def api_answers(monkeypatch):
    """Stands in for the network: records each call, answers with what the test sets."""
    # What Supabase really answers for ?limit=1 with Prefer: count=exact - 206 Partial Content, the total in Content-Range.
    calls, answer = [], {"status": 206, "headers": {"Content-Range": "0-0/313"}, "body": [LOAN]}

    def fake_get(url, headers, timeout=15):
        calls.append((url, headers))
        body = answer["body"]
        if isinstance(body, Exception):
            raise body
        return answer["status"], answer["headers"], body if isinstance(body, str) else connectors.json.dumps(body)

    monkeypatch.setattr(connectors, "http_get", fake_get)
    return calls, answer


def try_rest_api(client, headers, values=None):
    return client.post(f"{API}/ingestion/sources/rest_api/test", headers=headers, json={"values": values or LOS}).json()


def test_rest_api_test_connection_reads_one_loan_with_the_key_in_the_named_header(client, admin, api_answers):
    calls, _ = api_answers
    r = try_rest_api(client, admin)
    assert r["ok"] is True and r["live"] is True
    assert r["message"] == "Reached https://abc.supabase.co/rest/v1/loans: found 313 loans with every field the comparison needs."
    url, sent = calls[0]
    assert url == "https://abc.supabase.co/rest/v1/loans?limit=1"
    assert sent["apikey"] == "sb_publishable_SECRET" and sent["Prefer"] == "count=exact"
    assert "SECRET" not in r["message"]


def test_rest_api_test_connection_explains_what_is_wrong(client, admin, api_answers):
    _, answer = api_answers
    answer.update(status=401, body='{"message":"Invalid API key"}')
    assert try_rest_api(client, admin)["message"] == 'The API answered 401 at https://abc.supabase.co/rest/v1/loans: {"message":"Invalid API key"}'
    answer.update(status=200, body=[])
    assert "returned no loans" in try_rest_api(client, admin)["message"]
    answer.update(body=[{"loan_id": "L1", "amount": 5}])
    r = try_rest_api(client, admin)
    assert r["ok"] is False and "have no customer_id, product, currency, principal, outstanding, interest_rate" in r["message"]
    answer.update(body="<html>login</html>")
    assert "didn't answer with JSON" in try_rest_api(client, admin)["message"]
    answer.update(status=200, body={"data": [LOAN]}, headers={})   # an ordinary 200 with a wrapped list, no total: still fine
    assert try_rest_api(client, admin)["message"].endswith("found loans with every field the comparison needs.")
    answer.update(body=connectors.urllib.error.URLError("Name or service not known"))
    assert try_rest_api(client, admin)["message"] == "Couldn't reach https://abc.supabase.co/rest/v1/loans: Name or service not known"


def test_rest_api_without_a_key_sends_no_auth_header(client, admin, api_answers):
    calls, _ = api_answers
    assert try_rest_api(client, admin, {"base_url": "https://loans.example.com", "endpoint": "loans"})["ok"] is True
    url, sent = calls[0]
    assert url == "https://loans.example.com/loans?limit=1" and set(sent) == {"Accept", "Prefer"}


def test_rest_api_connect_hands_the_notebook_its_settings(client, admin, fake_databricks):
    r = client.post(f"{API}/ingestion/sources/rest_api/connect", headers=admin, json={"values": LOS})
    assert r.status_code == 200 and r.json()["source"]["detail"] == "https://abc.supabase.co/rest/v1"
    # exactly the keys notebooks/multi_source_rest_api_ingestion.py reads
    assert {k: v for k, v in fake_databricks.items() if k.startswith("rest_api-")} == {
        "rest_api-base_url": LOS["base_url"], "rest_api-endpoint": "/loans", "rest_api-auth_header": "apikey",
        "rest_api-api_key": "sb_publishable_SECRET"}


def test_rest_api_a_supabase_url_without_rest_v1_says_how_to_fix_it(client, admin, api_answers):
    _, answer = api_answers
    answer.update(status=404, body='{"error":"requested path is invalid"}')
    r = try_rest_api(client, admin, {**LOS, "base_url": "https://abc.supabase.co"})
    assert r["message"].endswith("end the Base URL with /rest/v1.")
    assert "/rest/v1" not in try_rest_api(client, admin, {**LOS, "base_url": "https://loans.example.com"})["message"]
