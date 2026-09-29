"""Source connectors on the Data Ingestion screen (app/connectors.py, ING-1): connect, test, disconnect,
sync and "Run all sources now" - and that a secret never reaches Postgres or the audit log."""
import pytest

from app import connectors
from app.routers import refresh

API = "/api/v1"
SALESFORCE = {"instance_url": "https://bankx.my.salesforce.com", "client_id": "3MVG9abc", "client_secret": "cs-SECRET-1",
              "username": "ingest@bankx.com", "password": "pw-SECRET-2", "security_token": "tok-SECRET-3"}


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
    assert fields["instance_url"]["kind"] == "url" and fields["client_secret"]["kind"] == "secret"
    assert fields["security_token"]["required"] is False


def test_connect_saves_settings_but_never_a_secret(client, admin, db, no_databricks):
    r = client.post(f"{API}/ingestion/sources/salesforce/connect", headers=admin, json={"values": SALESFORCE})
    assert r.status_code == 200
    card = r.json()["source"]
    assert card["status"] == "connected" and card["detail"] == "https://bankx.my.salesforce.com"
    assert card["config"] == {"instance_url": "https://bankx.my.salesforce.com", "client_id": "3MVG9abc", "username": "ingest@bankx.com"}
    assert card["secret_fields"] == ["client_secret", "password", "security_token"] and card["credentials"] == "not_stored"
    assert "not stored anywhere" in r.json()["message"]
    db.execute("SELECT count(*) FROM source_connectors WHERE config::text LIKE '%SECRET%' OR secret_fields::text LIKE '%SECRET%'")
    assert db.fetchone()[0] == 0
    db.execute("SELECT count(*) FROM audit_log WHERE new_value LIKE '%SECRET%'")
    assert db.fetchone()[0] == 0
    db.execute("SELECT count(*) FROM audit_log WHERE action = 'SOURCE_CONNECTED' AND object_id = 'salesforce'")
    assert db.fetchone()[0] >= 1
    assert sources(client, admin)["salesforce"]["status"] == "connected"


def test_with_databricks_connected_the_secrets_go_to_its_secret_scope(client, admin, monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "https://adb-1.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    calls = []

    def fake_api(method, path, body=None):
        calls.append((path, body))
        if path.endswith("scopes/create"):
            raise refresh.HTTPException(502, "Databricks refused the request (400): Scope bank-data-sources already exists!")
        return {}

    monkeypatch.setattr(refresh, "_api", fake_api)
    r = client.post(f"{API}/ingestion/sources/salesforce/connect", headers=admin, json={"values": SALESFORCE})
    assert r.json()["source"]["credentials"] == "databricks"
    puts = {b["key"]: b["string_value"] for p, b in calls if p.endswith("secrets/put")}
    assert puts == {"salesforce-client_secret": "cs-SECRET-1", "salesforce-password": "pw-SECRET-2", "salesforce-security_token": "tok-SECRET-3"}
    assert all(b["scope"] == connectors.SECRET_SCOPE for p, b in calls if p.endswith("secrets/put"))


def test_the_form_is_checked_on_the_server_too(client, admin, no_databricks):
    def connect(values, key="salesforce"):
        return client.post(f"{API}/ingestion/sources/{key}/connect", headers=admin, json={"values": values})
    missing = connect({**SALESFORCE, "password": "  "})
    assert missing.status_code == 422 and "Password is required" in missing.json()["detail"]
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


def test_only_the_cfo_or_an_admin_can_connect_or_run(client, auth):
    assert client.post(f"{API}/ingestion/sources/salesforce/connect", headers=auth, json={"values": SALESFORCE}).status_code == 403
    assert client.post(f"{API}/ingestion/run", headers=auth).status_code == 403
    assert client.delete(f"{API}/ingestion/sources/salesforce", headers=auth).status_code == 403
