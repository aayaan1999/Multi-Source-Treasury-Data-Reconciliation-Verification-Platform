"""Applies db/schema.sql to a Postgres database (e.g. Neon). One-off setup, refuses to run twice.

    pip install psycopg2-binary
    set DATABASE_URL=postgresql://user:password@host/dbname?sslmode=require     (PowerShell: $env:DATABASE_URL="...")
    python db/apply_schema.py

Copy the connection string from the Neon console (Connection Details). The password never goes
into the repo: it is read from the environment only.
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
        "Install it into exactly that Python, then run this script again:\n"
        f'  "{sys.executable}" -m pip install psycopg2-binary'
    )

url = os.environ.get("DATABASE_URL")
if not url:
    sys.exit("Set DATABASE_URL to the Neon connection string first (see this file's docstring).")

sql = (pathlib.Path(__file__).resolve().parent / "schema.sql").read_text(encoding="utf-8")

conn = psycopg2.connect(url, connect_timeout=30)  # Neon may take a few seconds to wake from suspend
try:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('public.customers')")
        if cur.fetchone()[0] is not None:
            sys.exit("public.customers already exists - schema already applied. Not touching it.")
        cur.execute(sql)  # schema.sql wraps itself in BEGIN/COMMIT
        cur.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public'")
        print(f"Schema applied: {cur.fetchone()[0]} tables in public.")
finally:
    conn.close()
