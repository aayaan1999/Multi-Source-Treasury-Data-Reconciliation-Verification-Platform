"""Applies one SQL migration file to the application database (e.g. Neon). Migrations are idempotent, so running one twice is fine.

    python db/apply_migration.py db/migrations/001_screens_2_to_5.sql

The connection string comes from the DATABASE_URL environment variable, or (if that is unset) from backend/.env.
It is never printed.
"""
import os
import pathlib
import sys

try:
    import psycopg2
except ModuleNotFoundError:
    sys.exit(
        "psycopg2 is not installed for the Python running this script:\n"
        f"  {sys.executable}\n"
        f'Install it into exactly that Python:  "{sys.executable}" -m pip install psycopg2-binary'
    )

if len(sys.argv) != 2:
    sys.exit(__doc__)

migration = pathlib.Path(sys.argv[1])
if not migration.is_file():
    sys.exit(f"Migration file not found: {migration}")

url = os.environ.get("DATABASE_URL")
if not url:
    env_file = pathlib.Path(__file__).resolve().parent.parent / "backend" / ".env"
    if env_file.is_file():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == "DATABASE_URL":
                url = value.strip().strip("\"'")
if not url:
    sys.exit("No DATABASE_URL: set the environment variable or fill it in backend/.env.")

conn = psycopg2.connect(url, connect_timeout=45)  # Neon may take a few seconds to wake
try:
    with conn.cursor() as cur:
        cur.execute(migration.read_text(encoding="utf-8"))  # the file wraps itself in BEGIN/COMMIT
    print(f"Applied {migration.name}.")
finally:
    conn.close()
