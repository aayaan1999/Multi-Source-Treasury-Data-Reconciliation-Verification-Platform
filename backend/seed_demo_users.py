"""Creates (or refreshes) the four demo roles/users the POC logs in with. Safe to run repeatedly.

    cd backend
    $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"
    $env:DEMO_USER_PASSWORD = "choose-a-password"     # optional: if unset, a random one is generated and printed once
    python seed_demo_users.py

All four users share the one password. Also adds users.password_hash if the database was created
before that column existed.
"""
import os
import secrets
import sys

import psycopg2
import psycopg2.extras

from app.security import hash_password

ROLES = {
    "analyst": ["view", "prepare"],
    "reviewer": ["view", "review", "comment"],
    "approver": ["view", "review", "approve"],
    "admin": ["view", "prepare", "review", "approve", "administer"],
}

USERS = [
    ("Demo Analyst", "analyst@bankx.demo", "analyst", "Finance"),
    ("Demo Reviewer", "reviewer@bankx.demo", "reviewer", "Risk"),
    ("Demo Approver", "approver@bankx.demo", "approver", "Finance"),
    ("Demo Admin", "admin@bankx.demo", "admin", "IT"),
]


def seed(cur, password: str) -> None:
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash text")
    role_ids = {}
    for name, permissions in ROLES.items():
        cur.execute(
            """INSERT INTO roles (name, permissions) VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE SET permissions = EXCLUDED.permissions RETURNING role_id""",
            (name, psycopg2.extras.Json(permissions)),
        )
        role_ids[name] = cur.fetchone()[0]
    for name, email, role, department in USERS:
        cur.execute(
            """INSERT INTO users (name, email, role_id, department, password_hash) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, role_id = EXCLUDED.role_id,
                   department = EXCLUDED.department, password_hash = EXCLUDED.password_hash""",
            (name, email, role_ids[role], department, hash_password(password)),
        )


if __name__ == "__main__":
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("Set DATABASE_URL first (see this file's docstring).")
    generated = not os.environ.get("DEMO_USER_PASSWORD")
    password = os.environ.get("DEMO_USER_PASSWORD") or secrets.token_urlsafe(9)

    conn = psycopg2.connect(url, connect_timeout=30)
    try:
        with conn, conn.cursor() as cur:
            seed(cur, password)
    finally:
        conn.close()

    print("Demo users ready: " + ", ".join(email for _, email, _, _ in USERS))
    if generated:
        print(f"Generated password (shown once): {password}")
