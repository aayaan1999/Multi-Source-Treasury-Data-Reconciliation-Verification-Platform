"""Refresh Now (specs/refresh-now.md, FLOW-6). Databricks' Jobs API is replaced by a fake: these
tests never start a real job."""
import io
import json
import urllib.error

import pytest

from conftest import PASSWORD

API = "/api/v1"
TOKEN = "dapi-secret-test-token"


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("DATABRICKS_HOST", "adb-123.azuredatabricks.net")
    monkeypatch.setenv("DATABRICKS_TOKEN", TOKEN)
    monkeypatch.setenv("DATABRICKS_JOB_ID", "42")


@pytest.fixture
def jobs_api(monkeypatch, configured):
    """A fake Jobs API: `state` is the latest run's life-cycle state; calls are recorded."""
    fake = {"state": "TERMINATED", "calls": []}

    def api(method, path, body=None):
        fake["calls"].append((method, path, body))
        if path.startswith("/api/2.1/jobs/runs/list"):
            return {"runs": [{"run_id": 7, "state": {"life_cycle_state": fake["state"], "result_state": "SUCCESS" if fake["state"] == "TERMINATED" else None},
                              "start_time": 1790240000000, "end_time": 1790240540000 if fake["state"] == "TERMINATED" else 0,
                              "trigger": "FILE_ARRIVAL", "run_page_url": "https://adb-123/run/7"}]}
        if path == "/api/2.1/jobs/run-now":
            return {"run_id": 8}
        raise AssertionError(path)

    monkeypatch.setattr("app.routers.refresh._api", api)
    return fake


@pytest.fixture(scope="module")
def cfo(client):
    token = client.post(f"{API}/auth/login", json={"email": "approver@bankx.demo", "password": PASSWORD}).json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


def test_without_databricks_settings_it_says_it_isnt_set_up(client, cfo, monkeypatch):
    monkeypatch.delenv("DATABRICKS_HOST", raising=False)
    monkeypatch.delenv("DATABRICKS_TOKEN", raising=False)
    r = client.get(f"{API}/refresh/status", headers=cfo)
    assert r.status_code == 503 and "DATABRICKS_HOST" in r.json()["detail"]


def test_status_reports_the_latest_run(client, auth, jobs_api):
    body = client.get(f"{API}/refresh/status", headers=auth).json()                     # anyone may look
    assert body["running"] is False
    assert body["last_run"]["result"] == "SUCCESS" and body["last_run"]["ended_at"].startswith("2026-09-")


def test_only_the_cfo_or_an_admin_can_refresh(client, auth, jobs_api):
    r = client.post(f"{API}/refresh", headers=auth)                                      # auth = the analyst
    assert r.status_code == 403
    assert not [c for c in jobs_api["calls"] if c[1] == "/api/2.1/jobs/run-now"]


def test_the_cfo_starts_a_run_and_it_is_audited(client, cfo, db, jobs_api):
    assert client.post(f"{API}/refresh", headers=cfo).json() == {"run_id": 8}
    assert ("POST", "/api/2.1/jobs/run-now", {"job_id": 42}) in jobs_api["calls"]
    db.execute("SELECT action, object_id FROM audit_log WHERE object_type = 'pipeline_job' ORDER BY log_id DESC LIMIT 1")
    assert db.fetchone() == ("REFRESH_REQUESTED", "8")


def test_a_second_click_while_running_is_refused_not_queued(client, cfo, jobs_api):
    jobs_api["state"] = "RUNNING"
    assert client.get(f"{API}/refresh/status", headers=cfo).json()["running"] is True
    r = client.post(f"{API}/refresh", headers=cfo)
    assert r.status_code == 409 and "already running" in r.json()["detail"]
    assert not [c for c in jobs_api["calls"] if c[1] == "/api/2.1/jobs/run-now"]


def test_a_databricks_error_is_reported_without_leaking_the_token(client, cfo, configured, monkeypatch):
    def refuse(request, timeout):
        assert request.headers["Authorization"] == f"Bearer {TOKEN}"                       # sent, but only there
        raise urllib.error.HTTPError(request.full_url, 403, "Forbidden", {}, io.BytesIO(json.dumps({"message": "Invalid access token"}).encode()))

    monkeypatch.setattr("urllib.request.urlopen", refuse)
    r = client.get(f"{API}/refresh/status", headers=cfo)
    assert r.status_code == 502 and "Invalid access token" in r.json()["detail"] and TOKEN not in r.text
