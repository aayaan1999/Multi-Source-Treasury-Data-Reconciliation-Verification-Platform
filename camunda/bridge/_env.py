"""Shared env loading for the bridge/outcome workers.

Same DATABASE_URL convention as db/apply_migration.py: env var first, falling back to
backend/.env so the workers don't need their own copy of the Neon connection string. Zeebe
connection settings come from camunda/.env instead, since that's the file that already documents
this project's Zeebe deployment (auth mode, ports).
"""
import os
import pathlib


def _load_env_file(path: pathlib.Path) -> dict:
    values = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip().strip("\"'")
    return values


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    values = _load_env_file(repo_root / "backend" / ".env")
    url = values.get("DATABASE_URL")
    if not url:
        raise SystemExit("No DATABASE_URL: set the environment variable or fill it in backend/.env.")
    return url


def zeebe_address() -> str:
    if os.environ.get("ZEEBE_ADDRESS"):
        return os.environ["ZEEBE_ADDRESS"]
    repo_root = pathlib.Path(__file__).resolve().parent.parent.parent
    values = _load_env_file(repo_root / "camunda" / "bridge" / ".env")
    return values.get("ZEEBE_ADDRESS", "localhost:26500")  # matches camunda/README.md's gRPC gateway port
