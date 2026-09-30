"""Creates (or refreshes) the demo roles and the seven demo users (specs/user-roles.md). Safe to run repeatedly.

    cd backend
    $env:DATABASE_URL = "postgresql://USER:PASSWORD@HOST/DBNAME?sslmode=require"   # or leave it in backend/.env
    python seed_demo_users.py

Each user gets the password listed in specs/user-roles.md, the same on every machine. Those passwords are
public (the repository is public): for a copy others can reach, set DEMO_USER_PASSWORD to give every user
that password instead. The four logins from before (analyst@, reviewer@, approver@, admin@) are renamed in
place, so audit rows keep pointing at the same person. Also adds users.password_hash if the database was
created before that column existed.
"""
import os
import pathlib
import sys

import psycopg2
import psycopg2.extras

from app.security import hash_password

# role -> permissions (roles.permissions); what each role sees on screen is in app/roles.py
ROLES = {
    "approver": ["view", "review", "approve", "sign_off"],
    "risk": ["view", "review"],
    "analyst": ["view", "prepare", "decide"],
    "preparer": ["view", "prepare"],
    "compliance": ["view", "investigate"],
    "auditor": ["view"],
    "admin": ["view", "prepare", "review", "approve", "administer"],
}

# (name, email, role, department, demo password, the email it had before specs/user-roles.md)
USERS = [
    ("CFO", "cfo@bankx.demo", "approver", "Finance", "BankX-Cfo-2026", "approver@bankx.demo"),
    ("CRO", "cro@bankx.demo", "risk", "Risk", "BankX-Cro-2026", "reviewer@bankx.demo"),
    ("Reconciliation Analyst", "recon.analyst@bankx.demo", "analyst", "Operations", "BankX-Recon-2026", "analyst@bankx.demo"),
    ("Reporting Officer", "reporting@bankx.demo", "preparer", "Finance", "BankX-Report-2026", None),
    ("Compliance Officer", "compliance@bankx.demo", "compliance", "Compliance", "BankX-Comply-2026", None),
    ("Internal Auditor", "auditor@bankx.demo", "auditor", "Internal Audit", "BankX-Audit-2026", None),
    ("Platform Admin", "admin@bankx.demo", "admin", "IT", "BankX-Admin-2026", None),
]


def seed(cur, password: str = None) -> None:
    """password: one password for every user (tests, or a hosted copy); None gives each their demo password."""
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS password_hash text")
    role_ids = {}
    for name, permissions in ROLES.items():
        cur.execute(
            """INSERT INTO roles (name, permissions) VALUES (%s, %s)
               ON CONFLICT (name) DO UPDATE SET permissions = EXCLUDED.permissions RETURNING role_id""",
            (name, psycopg2.extras.Json(permissions)),
        )
        role_ids[name] = cur.fetchone()[0]
    for name, email, role, department, demo_password, old_email in USERS:
        if old_email:
            # Renamed in place: same user_id, so decisions and audit rows stay theirs.
            cur.execute("""UPDATE users SET email = %s WHERE email = %s
                           AND NOT EXISTS (SELECT 1 FROM users WHERE email = %s)""", (email, old_email, email))
        cur.execute(
            """INSERT INTO users (name, email, role_id, department, password_hash) VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (email) DO UPDATE SET name = EXCLUDED.name, role_id = EXCLUDED.role_id,
                   department = EXCLUDED.department, password_hash = EXCLUDED.password_hash""",
            (name, email, role_ids[role], department, hash_password(password or demo_password)),
        )


def _database_url():
    if os.environ.get("DATABASE_URL"):
        return os.environ["DATABASE_URL"]
    env = pathlib.Path(__file__).with_name(".env")
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip("\"'") or None
    return None


if __name__ == "__main__":
    url = _database_url()
    if not url:
        sys.exit("Set DATABASE_URL first, or fill it in backend/.env (see this file's docstring).")
    shared = os.environ.get("DEMO_USER_PASSWORD") or None
    conn = psycopg2.connect(url, connect_timeout=30)
    try:
        with conn, conn.cursor() as cur:
            seed(cur, shared)
    finally:
        conn.close()
    print("Demo users ready: " + ", ".join(u[1] for u in USERS))
    print("Passwords: " + ("the one in DEMO_USER_PASSWORD, for every user" if shared else "as listed in specs/user-roles.md"))
