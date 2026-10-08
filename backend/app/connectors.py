"""Source connectors for the Data Ingestion screen (specs/screen-data-ingestion.md, backlog ING-1).

SOURCE_TYPES is the one list of sources the screen offers, with the fields each one's Connect form asks
for. The frontend draws its forms from it, and validate() re-checks everything the browser sends.

Secrets (passwords, keys, tokens) are never written to Postgres or the logs. connect_to_databricks_pipeline()
puts them in a Databricks secret scope, where the ingestion notebooks read them with dbutils.secrets.get;
when the app isn't connected to Databricks (no DATABRICKS_HOST / DATABRICKS_TOKEN) they are discarded
and the connector is saved without credentials, which the screen says plainly.
"""
import json
import os
import re
import urllib.error
import urllib.request
from typing import Optional
from urllib.parse import urlencode, urlparse

import psycopg2
from fastapi import HTTPException

SECRET_SCOPE = "bank-data-sources"      # Databricks secret scope the notebooks read connector credentials from
MAX_VALUE = 500
# What the core banking notebook (notebooks/multi_source_neon_ingestion.py) reads from a connected PostgreSQL
# database; the reconciliation compares these columns with our own customers and accounts.
CORE_BANKING_TABLES = {
    "customers": ["customer_id", "name", "segment", "risk_rating", "branch_id"],
    "accounts": ["account_id", "customer_id", "type", "currency", "balance"],
}
# What the loan system notebook reads from each loan the REST API returns.
LOAN_COLUMNS = ["loan_id", "customer_id", "product", "currency", "principal", "outstanding", "interest_rate"]
CORE_BANKING_SSL = "require"     # Test connection signs in encrypted only (the tests' local server has no SSL)
APP_DATABASE_REFUSED = ("That is this app's own database. Connect the core banking system's database instead: "
                        "comparing the app with itself would find nothing.")

# field: (key, label, kind, required, placeholder). kind "secret" is never stored or returned.
SOURCE_TYPES = {
    "core_files": {
        "name": "Core banking files", "code": "FILES", "detail": "CSV files in the landing volume (Lebanon, Saudi Arabia, Qatar)",
        "builtin": True, "fields": [],
    },
    # OAuth 2.0 client credentials with a Salesforce External Client App (the only kind new orgs can create
    # since Spring '26, and it doesn't allow the username-password flow). The Run As user is set in Salesforce.
    "salesforce": {
        "name": "Salesforce", "code": "SF", "detail": "CRM: Accounts",
        "fields": [
            ("instance_url", "Instance URL (My Domain)", "url", True, "https://your-domain.my.salesforce.com"),
            ("client_id", "Consumer key", "text", True, "3MVG9..."),
            ("client_secret", "Consumer secret", "secret", True, ""),
        ],
    },
    # Read by notebooks/multi_source_neon_ingestion.py: CORE_BANKING_TABLES below, compared with our own data.
    "postgresql": {
        "name": "PostgreSQL", "code": "PG", "detail": "Core banking database: customers and accounts",
        "fields": [
            ("host", "Host", "text", True, "db.bank.internal"),
            ("port", "Port", "port", True, "5432"),
            ("database", "Database", "text", True, "corebanking"),
            ("username", "Username", "text", True, "readonly_ingest"),
            ("password", "Password", "secret", True, ""),
        ],
    },
    # Read by notebooks/multi_source_rest_api_ingestion.py: a JSON list of loans with LOAN_COLUMNS, compared with
    # our loans. In the demo, a Supabase project's REST API (scripts/seed_loans_api.py).
    "rest_api": {
        "name": "REST API", "code": "API", "detail": "Loan origination system: loans (JSON)",
        "fields": [
            ("base_url", "Base URL", "url", True, "https://your-project.supabase.co/rest/v1"),
            ("endpoint", "Endpoint path", "text", True, "/loans"),
            ("auth_header", "Auth header name", "text", False, "apikey"),
            ("api_key", "API key / bearer token", "secret", False, ""),
        ],
    },
    "aws_s3": {
        "name": "AWS S3", "code": "S3", "detail": "Files dropped in an S3 bucket",
        "fields": [
            ("bucket", "Bucket", "text", True, "bank-exports"),
            ("region", "Region", "text", True, "me-central-1"),
            ("prefix", "Folder (prefix)", "text", False, "daily/"),
            ("access_key_id", "Access key ID", "text", True, "AKIA..."),
            ("secret_access_key", "Secret access key", "secret", True, ""),
        ],
    },
    "snowflake": {
        "name": "Snowflake", "code": "SNO", "detail": "Data warehouse tables",
        "fields": [
            ("account", "Account identifier", "text", True, "xy12345.me-central-1"),
            ("warehouse", "Warehouse", "text", True, "INGEST_WH"),
            ("database", "Database", "text", True, "FINANCE"),
            ("schema", "Schema", "text", True, "PUBLIC"),
            ("username", "Username", "text", True, "INGEST_USER"),
            ("password", "Password", "secret", True, ""),
            ("role", "Role", "text", False, "INGEST_ROLE"),
        ],
    },
}


def public_fields(source_key: str) -> list:
    """The form description the screen draws; nothing secret is in it."""
    return [{"key": k, "label": label, "kind": kind, "required": required, "placeholder": placeholder}
            for k, label, kind, required, placeholder in SOURCE_TYPES[source_key]["fields"]]


def source(source_key: str) -> dict:
    if source_key not in SOURCE_TYPES:
        raise HTTPException(404, "No such source")
    return SOURCE_TYPES[source_key]


def validate(source_key: str, values: dict) -> tuple:
    """Checks the Connect form and splits it into (config to keep, secrets to hand to Databricks).
    Unknown fields are refused rather than ignored."""
    spec = source(source_key)
    if spec.get("builtin"):
        raise HTTPException(409, f"{spec['name']} is set up by the pipeline itself and has nothing to configure")
    fields = {f[0]: f for f in spec["fields"]}
    unknown = set(values) - set(fields)
    if unknown:
        raise HTTPException(422, f"Unknown field: {sorted(unknown)[0]}")
    config, secrets, problems = {}, {}, []
    for key, label, kind, required, _ in spec["fields"]:
        value = values.get(key)
        value = value.strip() if isinstance(value, str) else value
        if value in (None, ""):
            if required:
                problems.append(f"{label} is required")
            continue
        if not isinstance(value, str) or len(value) > MAX_VALUE:
            problems.append(f"{label} must be text of at most {MAX_VALUE} characters")
        elif kind == "url" and not re.match(r"^https://[^\s/$.?#][^\s]*$", value):
            problems.append(f"{label} must be an https:// address")
        elif kind == "port" and not (value.isdigit() and 0 < int(value) < 65536):
            problems.append(f"{label} must be a number from 1 to 65535")
        else:
            (secrets if kind == "secret" else config)[key] = value
    if problems:
        raise HTTPException(422, "; ".join(problems))
    return config, secrets


def databricks_configured() -> bool:
    return bool(os.environ.get("DATABRICKS_HOST") and os.environ.get("DATABRICKS_TOKEN"))


def connect_to_databricks_pipeline(source_key: str, config: dict, secrets: dict) -> dict:
    """Hands a new source to the Databricks ingestion pipeline: its settings and credentials go into the
    secret scope as `<source>-<field>` (e.g. salesforce-client_secret), which the source's notebook reads
    (notebooks/multi_source_salesforce_ingestion.py). Non-secret settings go there too, so the notebook
    needs nothing else. Returns where the credentials went; never the credentials themselves.

    Not connected to Databricks: nothing is stored and the caller saves the source without credentials."""
    if not databricks_configured():
        if not secrets:
            return {"credentials": "none_needed", "detail": "No credentials to store"}
        return {"credentials": "not_stored",
                "detail": "The app isn't connected to Databricks, so the credentials were not stored anywhere. Connect again once it is."}
    from .routers.refresh import _api                     # the Jobs API client: never logs the token
    try:
        _api("POST", "/api/2.0/secrets/scopes/create", {"scope": SECRET_SCOPE})
    except HTTPException as e:
        if "already exists" not in str(e.detail).lower():
            raise
    for field, value in {**config, **secrets}.items():
        _api("POST", "/api/2.0/secrets/put", {"scope": SECRET_SCOPE, "key": f"{source_key}-{field}", "string_value": value})
    stale = {s["key"] for s in _api("GET", f"/api/2.0/secrets/list?scope={SECRET_SCOPE}").get("secrets", [])
             if s["key"].startswith(f"{source_key}-")} - {f"{source_key}-{f}" for f in {**config, **secrets}}
    for key in stale:                                      # e.g. a field an older version of the form asked for
        _api("POST", "/api/2.0/secrets/delete", {"scope": SECRET_SCOPE, "key": key})
    if not secrets:
        return {"credentials": "none_needed", "detail": f"Settings stored in the Databricks secret scope {SECRET_SCOPE}"}
    return {"credentials": "databricks", "detail": f"Credentials stored in the Databricks secret scope {SECRET_SCOPE}"}


def forget_in_databricks(source_key: str) -> None:
    """Disconnect: deletes the source's settings and credentials from the secret scope, so the pipeline
    skips it and nothing is left behind. Nothing to do when the app isn't connected to Databricks."""
    if not databricks_configured():
        return
    from .routers.refresh import _api
    try:
        keys = _api("GET", f"/api/2.0/secrets/list?scope={SECRET_SCOPE}").get("secrets", [])
    except HTTPException as e:
        if "does not exist" in str(e.detail).lower():
            return
        raise
    for key in (k["key"] for k in keys if k["key"].startswith(f"{source_key}-")):
        _api("POST", "/api/2.0/secrets/delete", {"scope": SECRET_SCOPE, "key": key})


def is_app_database(config: dict) -> bool:
    """Whether the PostgreSQL form points at the app's own database. Reconciling the app against itself
    proves nothing and gives the pipeline a login to it, so it is refused. Neon's pooled host counts as the same."""
    parsed = urlparse(os.environ.get("DATABASE_URL", ""))
    def norm(host):
        return (host or "").lower().replace("-pooler.", ".")
    return bool(parsed.hostname) and norm(config.get("host")) == norm(parsed.hostname) \
        and config.get("database") == parsed.path.lstrip("/")


def check_postgresql(config: dict, secrets: dict) -> dict:
    """A live sign-in to the core banking database, read-only, with the settings the notebook will use:
    are CORE_BANKING_TABLES there with the columns it reads, and how many rows each has. The answer never
    contains the password; a failure gives the database's own first line (e.g. wrong password, no such table)."""
    try:
        conn = psycopg2.connect(host=config["host"], port=int(config["port"]), dbname=config["database"],
                                user=config["username"], password=secrets["password"], sslmode=CORE_BANKING_SSL,
                                connect_timeout=10, options="-c default_transaction_read_only=on -c statement_timeout=10000")
    except psycopg2.Error as e:
        first = (str(e).strip().splitlines() or [type(e).__name__])[0]
        return {"ok": False, "live": True, "message": f"Couldn't sign in to {config['host']}/{config['database']}: {first}"}
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT table_name, column_name FROM information_schema.columns
                           WHERE table_schema = ANY (current_schemas(false)) AND table_name = ANY (%s)""",
                        (list(CORE_BANKING_TABLES),))
            found = {}
            for table, column in cur.fetchall():
                found.setdefault(table, set()).add(column)
            problems = []
            for table, columns in CORE_BANKING_TABLES.items():
                if table not in found:
                    problems.append(f"no {table} table")
                elif missing := [c for c in columns if c not in found[table]]:
                    problems.append(f"{table} has no {', '.join(missing)}")
            if problems:
                return {"ok": False, "live": True,
                        "message": f"Signed in, but the pipeline can't read it: {'; '.join(problems)}."}
            counts = {}
            for table in CORE_BANKING_TABLES:                    # fixed names from the constant, never user input
                cur.execute(f"SELECT count(*) FROM {table}")
                counts[table] = cur.fetchone()[0]
    except psycopg2.Error as e:
        return {"ok": False, "live": True, "message": f"Signed in, but reading failed: {str(e).strip().splitlines()[0]}"}
    finally:
        conn.close()
    found_text = " and ".join(f"{n:,} {t}" for t, n in counts.items())
    return {"ok": True, "live": True, "message": f"Signed in to {config['host']}/{config['database']}: found {found_text}."}


def http_get(url: str, headers: dict, timeout: int = 15):
    """One GET: (status, response headers, body text). Kept apart so tests can stand in for the network."""
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers), response.read(1_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers or {}), e.read(2000).decode("utf-8", "replace")


def check_rest_api(config: dict, secrets: dict) -> dict:
    """A live call to the loan system's API with the settings the notebook will use: one loan, asking for
    the total (Supabase answers with Content-Range), and are LOAN_COLUMNS there. Never echoes the key."""
    url = config["base_url"].rstrip("/") + "/" + config["endpoint"].lstrip("/")
    headers = {"Accept": "application/json", "Prefer": "count=exact"}
    if config.get("auth_header") and secrets.get("api_key"):
        headers[config["auth_header"]] = secrets["api_key"]
    try:
        status, response_headers, body = http_get(f"{url}?{urlencode({'limit': 1})}", headers)
    except (urllib.error.URLError, OSError, ValueError) as e:
        reason = getattr(e, "reason", None) or type(e).__name__
        return {"ok": False, "live": True, "message": f"Couldn't reach {url}: {reason}"}
    # 206 Partial Content: Supabase (PostgREST) answers so when asked for the total and sending only part of it.
    if status not in (200, 206):
        hint = ""
        if status == 404 and urlparse(url).hostname.endswith(".supabase.co") and "/rest/v1" not in url:
            hint = " Supabase serves tables under /rest/v1: end the Base URL with /rest/v1."
        return {"ok": False, "live": True, "message": f"The API answered {status} at {url}: {body.strip()[:200]}{hint}"}
    try:
        data = json.loads(body)
    except ValueError:
        return {"ok": False, "live": True, "message": f"Reached {url}, but it didn't answer with JSON."}
    if isinstance(data, dict):
        data = next((data[k] for k in ("data", "items", "records", "results") if isinstance(data.get(k), list)), data)
    if not isinstance(data, list):
        return {"ok": False, "live": True, "message": f"Reached {url}, but it didn't return a list of loans."}
    if not data:
        return {"ok": False, "live": True,
                "message": f"Reached {url}, but it returned no loans. Check the endpoint, and that the key may read them."}
    if not isinstance(data[0], dict) or (missing := [c for c in LOAN_COLUMNS if c not in data[0]]):
        missing = missing if isinstance(data[0], dict) else LOAN_COLUMNS
        return {"ok": False, "live": True, "message": f"Reached {url}, but its loans have no {', '.join(missing)}."}
    total = (response_headers.get("Content-Range") or response_headers.get("content-range") or "").rpartition("/")[2]
    found = f"{int(total):,} loans" if total.isdigit() else "loans"
    return {"ok": True, "live": True, "message": f"Reached {url}: found {found} with every field the comparison needs."}


def test_connection(source_key: str, values: dict) -> dict:
    """The "Test connection" check. PostgreSQL and the REST API connect for real (check_postgresql,
    check_rest_api); the others check the
    form is complete and well-formed until their connector is built (backlog ING-1), and say so."""
    config, secrets = validate(source_key, values)
    name = SOURCE_TYPES[source_key]["name"]
    if source_key == "postgresql":
        if is_app_database(config):
            return {"ok": False, "live": False, "message": APP_DATABASE_REFUSED}
        return {**check_postgresql(config, secrets), "checked": sorted([*config, *secrets])}
    if source_key == "rest_api":
        return {**check_rest_api(config, secrets), "checked": sorted([*config, *secrets])}
    return {"ok": True, "live": False,
            "message": f"{name} details are complete and well-formed. A live sign-in check isn't enabled in this demo yet.",
            "checked": sorted([*config, *secrets])}


def label_config(source_key: str, config: Optional[dict]) -> str:
    """One line for the card, from non-secret settings only (e.g. the instance URL or bucket)."""
    config = config or {}
    first = next((config[f[0]] for f in SOURCE_TYPES[source_key]["fields"] if f[0] in config and f[2] in ("url", "text")), None)
    return first or SOURCE_TYPES[source_key]["detail"]
