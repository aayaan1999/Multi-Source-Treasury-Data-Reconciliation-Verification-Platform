---
name: setup-new-machine
description: Set up this project from scratch on a PC that has never run it before — clone, backend venv, frontend packages, .env, demo user seeding, and (optionally) the Camunda Docker stack. Use when the user asks to "set this up on another PC", "set up a new machine", "onboard a new dev", or wants the from-scratch install steps rather than just starting an already-configured checkout (that's `run-local`).
---

# Set up this project on a new machine

This is the from-scratch install: a PC that has never had this repo, its Python venv, its npm
packages, or its `.env` on it before. If the checkout already exists and is just not currently
running, use the `run-local` skill instead — don't redo these steps on a machine that's already
set up.

Two layers, install the first always, the second only if the workflow tabs (Tasks / Audit &
Oversight) need to work:

1. **Application layer** — FastAPI backend + React frontend + Neon Postgres. Always needed.
2. **Camunda 8 stack** — Zeebe + Elasticsearch + Tasklist via Docker Compose, plus the Python
   bridge/outcome workers. Only needed for Screen 6 (Tasks / Audit & Oversight) to show live task
   data; the rest of the app runs fine without it.

## Rules that always apply
* **Never print, log, echo, or ask the user to paste** `DATABASE_URL`, `JWT_SECRET`, or any
  password into chat. Have the user paste secrets directly into the `.env` file, or set them as
  env vars in a command the user runs themselves if a script needs one.
* **Don't ask for or use the user's demo password.** Verify login by trying a deliberately wrong
  password and expecting 401.
* Never write a real secret into `.env.example` — it's committed to git.
* The project folder name contains an `&`. Always quote paths. Always `npm run ...`, never
  `npx vite` — the `&` breaks Windows `.cmd` shims.

## 1. Prerequisites (install if missing)
* **Git**
* **Python 3.10+** — check with `python --version`; on Windows the OS-default can be an old 3.8,
  so may need `C:\Users\<user>\AppData\Local\Programs\Python\Python311\python.exe` explicitly.
* **Node.js** (for `npm`)
* Access to the project's **Neon** connection string — this is an existing database; don't create
  a new one, get the string from whoever holds it.
* **Docker Desktop** — only if setting up the Camunda stack (step 6). Must be running, not just
  installed, before `docker compose up` will work.

## 2. Clone
```
git clone https://github.com/aayaan1999/Multi-Source-Treasury-Data-Reconciliation-Verification-Platform.git
```

## 3. Backend
```powershell
cd backend
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
If the default `python` is too old, use a specific interpreter, e.g.:
```powershell
& "C:\Users\<user>\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv
```

## 4. Backend config
Copy `backend\.env.example` to `backend\.env`, then have the user fill in (Claude should not see
or handle the raw values beyond confirming they're present and correctly formatted):
* `DATABASE_URL` — the Neon string, **direct host** (no `-pooler`), no quotes, ending
  `?sslmode=require`
* `JWT_SECRET` — generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`

Leave `JWT_EXPIRE_MINUTES`, `CORS_ORIGINS`, `DB_POOL_MAX` at the `.env.example` defaults unless
the user says otherwise.

## 5. Frontend
```powershell
cd frontend
npm install
```

## 6. Seed demo users (once per database — skip if this Neon database already has them)
Re-running resets the password, so only do this if the user wants that. The user runs this
themselves since it needs a secret:
```powershell
$env:DATABASE_URL = "<neon string>"; $env:DEMO_USER_PASSWORD = "<password the user picks>"
& "<root>\backend\.venv\Scripts\python.exe" "<root>\backend\seed_demo_users.py"
```
Expect `Demo users ready: ...`. Demo emails: `analyst@`, `reviewer@`, `approver@`,
`admin@bankx.demo`, all sharing that one password.

## 7. Start and verify the app
Use the `run-local` skill from here — it covers the pre-flight check, starting both servers
(windowless via background tool calls, not the two-popup-window launcher, unless the user asks for
the windowed version), and verification (health check, proxy check, login-wiring 401 check).

## 8. Camunda stack (optional — only if Tasks / Audit & Oversight need live data)
Requires Docker Desktop running first.
```powershell
cd camunda
docker compose up -d
```
This starts Zeebe, Elasticsearch, and Tasklist (Operate is commented out in
`camunda/docker-compose.yaml` to cut CPU/RAM contention — see `camunda/README.md`). Then, from the
backend venv, per `specs/camunda-bpmn-process-design.md`:
```powershell
& "<root>\backend\.venv\Scripts\python.exe" "<root>\camunda\bridge\deploy.py"        # deploys the BPMN process + form, once
& "<root>\backend\.venv\Scripts\python.exe" "<root>\camunda\bridge\poll_worker.py"   # syncs flagged_transactions -> Camunda process instances
& "<root>\backend\.venv\Scripts\python.exe" "<root>\camunda\bridge\outcome_worker.py" # writes review outcomes back to review_outcomes in Neon
```
`poll_worker.py` and `outcome_worker.py` are long-running — start them as background tool calls,
same pattern as the app's own servers, not in a way that blocks the session.

Without this stack, the Tasks and Audit & Oversight tabs still load in the frontend but won't show
live task data from Tasklist.

## Not needed just to run the app locally
The Databricks notebooks (`notebooks/`) and the multi-source ingestion sources (Mockaroo,
Salesforce, IMF API, Google Sheets, the second reconciliation Neon project) feed data *into* Neon
but aren't required to start or view the app — the app reads whatever's already in Neon. Only set
those up if the user specifically wants to (re)run the data pipeline, not for a basic local setup.

## If something fails
See `run-local`'s "If it fails" table for backend/frontend/login issues once install steps are
done — most failures at that point are `.env` formatting, not the install itself.
