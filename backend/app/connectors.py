"""Source connectors for the Data Ingestion screen (specs/screen-data-ingestion.md, backlog ING-1).

SOURCE_TYPES is the one list of sources the screen offers, with the fields each one's Connect form asks
for. The frontend draws its forms from it, and validate() re-checks everything the browser sends.

Secrets (passwords, keys, tokens) are never written to Postgres or the logs. connect_to_databricks_pipeline()
puts them in a Databricks secret scope, where the ingestion notebooks read them with dbutils.secrets.get;
when the app isn't connected to Databricks (no DATABRICKS_HOST / DATABRICKS_TOKEN) they are discarded
and the connector is saved without credentials, which the screen says plainly.
"""
import os
import re
from typing import Optional

from fastapi import HTTPException

SECRET_SCOPE = "bank-data-sources"      # Databricks secret scope the notebooks read connector credentials from
MAX_VALUE = 500

# field: (key, label, kind, required, placeholder). kind "secret" is never stored or returned.
SOURCE_TYPES = {
    "core_files": {
        "name": "Core banking files", "code": "FILES", "detail": "CSV files in the landing volume (Lebanon, Saudi Arabia, Qatar)",
        "builtin": True, "fields": [],
    },
    "salesforce": {
        "name": "Salesforce", "code": "SF", "detail": "CRM: customers and relationship managers",
        "fields": [
            ("instance_url", "Instance URL", "url", True, "https://your-domain.my.salesforce.com"),
            ("client_id", "Client ID / Consumer key", "text", True, "3MVG9..."),
            ("client_secret", "Client secret", "secret", True, ""),
            ("username", "Username", "text", True, "integration.user@bank.com"),
            ("password", "Password", "secret", True, ""),
            ("security_token", "Security token", "secret", False, "Only if your org requires one"),
        ],
    },
    "postgresql": {
        "name": "PostgreSQL", "code": "PG", "detail": "Core banking or ERP database",
        "fields": [
            ("host", "Host", "text", True, "db.bank.internal"),
            ("port", "Port", "port", True, "5432"),
            ("database", "Database", "text", True, "corebanking"),
            ("username", "Username", "text", True, "readonly_ingest"),
            ("password", "Password", "secret", True, ""),
        ],
    },
    "rest_api": {
        "name": "REST API", "code": "API", "detail": "Any JSON API, e.g. a loan origination system",
        "fields": [
            ("base_url", "Base URL", "url", True, "https://api.example.com/v1"),
            ("endpoint", "Endpoint path", "text", True, "/loans"),
            ("auth_header", "Auth header name", "text", False, "Authorization"),
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
    """Hands a new source to the Databricks ingestion pipeline: its credentials go into the secret scope
    as `<source>-<field>` (e.g. salesforce-password), which the ingestion notebooks read. Returns where
    the credentials went; never the credentials themselves.

    Not connected to Databricks: nothing is stored and the caller saves the source without credentials."""
    if not secrets:
        return {"credentials": "none_needed", "detail": "No credentials to store"}
    if not databricks_configured():
        return {"credentials": "not_stored",
                "detail": "The app isn't connected to Databricks, so the credentials were not stored anywhere. Connect again once it is."}
    from .routers.refresh import _api                     # the Jobs API client: never logs the token
    try:
        _api("POST", "/api/2.0/secrets/scopes/create", {"scope": SECRET_SCOPE})
    except HTTPException as e:
        if "already exists" not in str(e.detail).lower():
            raise
    for field, value in secrets.items():
        _api("POST", "/api/2.0/secrets/put", {"scope": SECRET_SCOPE, "key": f"{source_key}-{field}", "string_value": value})
    return {"credentials": "databricks", "detail": f"Credentials stored in the Databricks secret scope {SECRET_SCOPE}"}


def test_connection(source_key: str, values: dict) -> dict:
    """The "Test connection" check. Today it checks the form is complete and well-formed; a live sign-in
    to each system comes with its connector (backlog ING-1), so the answer says which it was."""
    config, secrets = validate(source_key, values)
    name = SOURCE_TYPES[source_key]["name"]
    return {"ok": True, "live": False,
            "message": f"{name} details are complete and well-formed. A live sign-in check isn't enabled in this demo yet.",
            "checked": sorted([*config, *secrets])}


def label_config(source_key: str, config: Optional[dict]) -> str:
    """One line for the card, from non-secret settings only (e.g. the instance URL or bucket)."""
    config = config or {}
    first = next((config[f[0]] for f in SOURCE_TYPES[source_key]["fields"] if f[0] in config and f[2] in ("url", "text")), None)
    return first or SOURCE_TYPES[source_key]["detail"]
