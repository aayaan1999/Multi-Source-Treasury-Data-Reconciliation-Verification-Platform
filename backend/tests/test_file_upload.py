"""Upload files on the Data Ingestion screen (specs/screen-data-ingestion.md section 3b): one of the pipeline's eight CSVs is
checked, then written into the landing folder with the Databricks Files API, which starts the pipeline."""
import json
import urllib.error
import urllib.parse

import pytest

from app.routers import ingestion

API = "/api/v1"
TRANSACTIONS = b"transaction_id,account_id,date,amount,currency,type,channel\nT1,A1,2026-09-30,10,USD,debit,branch\nT2,A1,2026-09-30,20,USD,credit,online\n"


def login(client, email):
    from conftest import PASSWORD
    token = client.post(f"{API}/auth/login", json={"email": email, "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def upload(client, headers, name, content):
    return client.post(f"{API}/ingestion/upload", content=content,
                       headers={**headers, "Content-Type": "text/csv", "X-File-Name": urllib.parse.quote(name)})


@pytest.fixture
def admin(client):
    return login(client, "admin@bankx.demo")


@pytest.fixture
def landing(monkeypatch):
    """The landing folder held in a dict, behind the Files API call the app makes."""
    monkeypatch.setenv("DATABRICKS_HOST", "adb-1.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", "dapi-test")
    monkeypatch.delenv("DATABRICKS_LANDING_PATH", raising=False)
    folder = {}

    class Reply:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        assert request.get_method() == "PUT"
        assert request.headers["Authorization"] == "Bearer dapi-test"
        url = urllib.parse.urlparse(request.full_url)
        assert url.netloc == "adb-1.azuredatabricks.net" and url.query == "overwrite=true"
        folder[urllib.parse.unquote(url.path.removeprefix("/api/2.0/fs/files"))] = request.data
        return Reply()

    monkeypatch.setattr(ingestion.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(ingestion.refresh, "_job_id", lambda: 7)
    monkeypatch.setattr(ingestion.refresh, "_api", lambda method, path, body=None: {"settings": {"trigger": {"pause_status": "UNPAUSED"}}})
    return folder


def test_a_dated_file_lands_under_the_name_notebook_1_reads_and_is_audited(client, admin, landing, db):
    r = upload(client, admin, "Transactions_2026-09-30.csv", TRANSACTIONS)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["stored_as"] == "transactions.csv" and body["rows"] == 2
    assert "starts about 2 minutes after the last file" in body["message"]
    assert landing == {f"{ingestion.DEFAULT_LANDING_PATH}/transactions.csv": TRANSACTIONS}
    db.execute("SELECT object_id, new_value FROM audit_log WHERE action = 'FILE_UPLOADED' ORDER BY log_id DESC LIMIT 1")
    row = db.fetchone()
    assert row[0] == "transactions.csv"
    details = row[1] if isinstance(row[1], dict) else json.loads(row[1])
    assert details["file"] == "Transactions_2026-09-30.csv" and details["rows"] == 2


def test_when_the_automatic_start_is_paused_it_says_to_run_the_pipeline(client, admin, landing, monkeypatch):
    monkeypatch.setattr(ingestion.refresh, "_api", lambda method, path, body=None: {"settings": {"trigger": {"pause_status": "PAUSED"}}})
    body = upload(client, admin, "transactions.csv", TRANSACTIONS).json()
    assert body["auto_start"] is False
    assert "press Run all sources now once all files are in" in body["message"]
    assert len(landing) == 1                                                     # the file still lands


def test_if_the_job_cant_be_read_the_upload_still_succeeds(client, admin, landing, monkeypatch):
    def fail(method, path, body=None):
        raise ingestion.HTTPException(502, "down")
    monkeypatch.setattr(ingestion.refresh, "_api", fail)
    r = upload(client, admin, "transactions.csv", TRANSACTIONS)
    assert r.status_code == 200 and r.json()["auto_start"] is True


def test_the_landing_folder_can_be_changed(client, admin, landing, monkeypatch):
    monkeypatch.setenv("DATABRICKS_LANDING_PATH", "/Volumes/test/raw/raw/incoming/")
    assert upload(client, admin, "transactions.csv", TRANSACTIONS).status_code == 200
    assert list(landing) == ["/Volumes/test/raw/raw/incoming/transactions.csv"]


@pytest.mark.parametrize("name, content, says", [
    ("notes.docx", b"x", "Only CSV files"),
    ("loans2.csv", b"x", "isn't one of the pipeline's files"),
    ("transactions.csv", b"  \n", "is empty"),
    ("transactions.csv", "café".encode("latin-1"), "isn't UTF-8"),
    ("transactions.csv", b"transaction_id,account_id,date,amount\nT1,A1,2026-09-30,10\n", "missing column(s) currency, type, channel"),
])
def test_a_file_the_pipeline_cant_read_is_refused_and_never_sent(client, admin, landing, name, content, says):
    r = upload(client, admin, name, content)
    assert r.status_code == 400 and says in r.json()["detail"]
    assert landing == {}


def test_a_file_over_the_limit_is_refused(client, admin, landing, monkeypatch):
    monkeypatch.setattr(ingestion, "UPLOAD_MAX_BYTES", 50)
    r = upload(client, admin, "transactions.csv", TRANSACTIONS)
    assert r.status_code == 400 and "larger than" in r.json()["detail"]


def test_a_missing_name_is_refused(client, admin, landing):
    r = client.post(f"{API}/ingestion/upload", content=TRANSACTIONS, headers=admin)
    assert r.status_code == 400 and "name is missing" in r.json()["detail"]


def test_without_databricks_it_says_so(client, admin, monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    r = upload(client, admin, "transactions.csv", TRANSACTIONS)
    assert r.status_code == 503 and "isn't connected to the Databricks pipeline" in r.json()["detail"]


def test_a_databricks_refusal_is_passed_on(client, admin, landing, monkeypatch):
    def refuse(request, timeout=None):
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, __import__("io").BytesIO(b'{"message": "no WRITE VOLUME"}'))
    monkeypatch.setattr(ingestion.urllib.request, "urlopen", refuse)
    r = upload(client, admin, "transactions.csv", TRANSACTIONS)
    assert r.status_code == 502 and r.json()["detail"] == "Databricks refused the file (403): no WRITE VOLUME"


def test_the_cfo_can_upload_but_the_analyst_and_auditor_cannot(client, landing):
    assert upload(client, login(client, "cfo@bankx.demo"), "transactions.csv", TRANSACTIONS).status_code == 200
    assert upload(client, login(client, "recon.analyst@bankx.demo"), "transactions.csv", TRANSACTIONS).status_code == 403
    assert upload(client, login(client, "auditor@bankx.demo"), "transactions.csv", TRANSACTIONS).status_code == 403
    assert len(landing) == 1


def test_the_overview_lists_the_files_the_pipeline_reads(client, admin):
    body = client.get(f"{API}/ingestion/overview", headers=admin).json()
    assert body["upload_formats"] == ["CSV"]
    assert body["upload_files"] == ["customers.csv", "accounts.csv", "loans.csv", "transactions.csv", "branches.csv",
                                    "capital_positions.csv", "liquidity_daily.csv", "fx_rates.csv"]


@pytest.mark.parametrize("name, table", [
    ("transactions.csv", "transactions"), ("LOANS.CSV", "loans"), ("fx_rates-sep.csv", "fx_rates"),
    ("capital_positions 2026.csv", "capital_positions"), ("loans2.csv", None), ("my_loans.csv", None),
    ("loans.json", None), ("loans", None), (".csv", None),
])
def test_which_file_a_name_is(name, table):
    assert ingestion.upload_table(name) == table
