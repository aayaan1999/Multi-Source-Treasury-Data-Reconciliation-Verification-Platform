---
name: run-local
description: Start, check or stop this project's app on the user's own PC (FastAPI backend on port 8000 + React site on port 5173, talking to the Neon database). Use when the user asks to "start the app", "run it locally", "host this locally", "launch the dashboard", or to check whether the local app is running. Also the launch recipe for the built-in `run` skill in this repo.
---

# Run the app locally

The app is two servers started by one script, `scripts/run-local.ps1`: the FastAPI API (`http://127.0.0.1:8000`) and the
Vite dev server for the React site (`http://localhost:5173`, which proxies `/api` to the API). The database is Neon
Postgres, read from `backend/.env`. Cloud hosting (Netlify + Render) is configured but paused; local is the way to run it now.

## Which folder
Work in the project folder the session is in: `C:\Users\Ayan\OneDrive\Desktop\Multi-Source Treasury Data Reconciliation & Verification Platform`.
Its name contains an `&`, so **always quote paths**. A second copy at `C:\Users\Ayan\projects\bank-data-platform` exists but
is unused: do not create or change files there, and never move the run to it, without asking.

## Rules that always apply
* **Never print, log, echo or ask for** `DATABASE_URL`, `JWT_SECRET` or any password. Check them masked (set / length /
  format), as below. Never write a real secret into `.env.example` (it is committed to GitHub).
* **Don't ask for or use the user's demo password.** Verify login with a deliberately wrong password and expect 401.
* Only touch `backend/.env` for whitespace tidying, never the values.
* Start/stop only what the user asked for. Don't kill their servers to "fix" something without saying so.

## 1. Pre-flight (read-only)
Run in PowerShell from the project root:
```powershell
$root = (Get-Location).Path
$l = Get-Content -LiteralPath "$root\backend\.env" | Where-Object { $_ -match '^\s*DATABASE_URL\s*=' } | Select-Object -First 1
if ($l -match '=\s*(\S+)') { $v = $matches[1]; "DATABASE_URL set ($($v.Length) chars), format ok: $($v -match '^postgres(ql)?://[^:]+:[^@]+@[^/]+/[^?]+\?.*sslmode=require'), pooled host: $($v -match '-pooler')" } else { "DATABASE_URL EMPTY" }
"venv: $(Test-Path "$root\backend\.venv\Scripts\python.exe")  packages: $(Test-Path "$root\frontend\node_modules")  launcher: $(Test-Path "$root\scripts\run-local.ps1")"
"listening: 8000=$([bool](Get-NetTCPConnection -LocalPort 8000 -State Listen -EA SilentlyContinue))  5173=$([bool](Get-NetTCPConnection -LocalPort 5173 -State Listen -EA SilentlyContinue))"
```
* Already listening on 8000/5173 -> it is probably already running: check health (step 3) and report, don't start a second copy.
* `DATABASE_URL` empty -> stop and ask the user to paste their Neon string into `backend\.env` (the file named exactly `.env`,
  not `.env.example`) and save it. Use the direct host (no `-pooler`), no quotes, ending `?sslmode=require`.
* Missing venv or packages -> see "First-time setup".
* Optional real connection test before launching: parse `.env` with `dotenv_values` in the venv python, `psycopg2.connect`,
  print only counts (e.g. demo users with a password should be 4; `kpi_daily_summary` rows show whether the pipeline loaded).

## 2. Start
```powershell
Set-Location -LiteralPath $root
& "$root\scripts\run-local.ps1"            # opens 2 PowerShell windows (API, site) and the browser
& "$root\scripts\run-local.ps1" -NoBrowser # same, without opening a browser tab
```
It waits up to ~40 s for both servers. If Windows blocks the script: `powershell -ExecutionPolicy Bypass -File .\scripts\run-local.ps1`.

## 3. Verify (from a separate call)
```powershell
(Invoke-RestMethod http://127.0.0.1:8000/api/v1/live).status                 # alive
(Invoke-RestMethod http://127.0.0.1:8000/api/v1/health)                      # status ok, database True = reached Neon
(Invoke-WebRequest http://localhost:5173/ -UseBasicParsing).StatusCode        # 200 (use localhost, not 127.0.0.1)
(Invoke-RestMethod http://localhost:5173/api/v1/live).status                  # alive = the /api proxy works
# login wiring: a WRONG password must return 401
try { Invoke-RestMethod -Method Post http://localhost:5173/api/v1/auth/login -ContentType 'application/json' -Body '{"email":"analyst@bankx.demo","password":"definitely-wrong"}' } catch { $_.Exception.Response.StatusCode.value__ }
```
Report: site `http://localhost:5173`, API docs `http://127.0.0.1:8000/docs`, demo emails `analyst@`, `reviewer@`, `approver@`,
`admin@bankx.demo` (all share the one password the user chose when seeding), and that closing the two windows stops it.
"No numbers yet" on the dashboard just means the Databricks pipeline hasn't loaded Neon.

## Stop (only when asked)
Close the two PowerShell windows, or: for ports 8000 and 5173, `taskkill /PID <owning pid> /T /F`
(`Get-NetTCPConnection -LocalPort <port> -State Listen`).

## First-time setup (only if something is missing)
```powershell
cd "<root>\backend"
& "C:\Users\Ayan\AppData\Local\Programs\Python\Python311\python.exe" -m venv .venv     # needs Python 3.10+, not the default 3.8
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd "<root>\frontend"; npm install                     # always `npm run ...`, never `npx vite` (the & in the path breaks .cmd shims)
```
* `backend\.env`: copy `.env.example`; needs `DATABASE_URL` and `JWT_SECRET` (`python -c "import secrets; print(secrets.token_urlsafe(48))"`).
* Demo users (once per database; re-running resets the password). **Run by full path** — the script lives in `backend\`,
  and running `seed_demo_users.py` from the project root fails with "can't open file":
  ```powershell
  $env:DATABASE_URL = "<neon string>"; $env:DEMO_USER_PASSWORD = "<password the user picks>"
  & "<root>\backend\.venv\Scripts\python.exe" "<root>\backend\seed_demo_users.py"
  ```
  The user runs this themselves (it needs their secret); it expects `Demo users ready: ...`.

## Known gotchas
* A stray space after `DATABASE_URL=` (or `ok ` typed before a `#` comment) is easy to make when pasting. The launcher now
  tolerates spaces, but tidy the line if the API misbehaves (whitespace only).
* The PowerShell tool refuses scripts containing `Remove-Item` on env vars or temp files: clear a variable with
  `$env:NAME = $null`, and pipe Python code via stdin (`$code | python - args`) instead of using temp files.
* Neon sleeps when idle: a first request or connection can take several seconds; retry before assuming a fault.
* Windows launcher exit codes: robocopy 1 = success. `taskkill` on an already-exited process prints an error that is harmless.

## If it fails
| Symptom | Likely cause |
|---|---|
| Launcher: "DATABASE_URL is empty" | Not saved, or pasted into `.env.example` / the other folder's `.env` |
| `/health` database False, or 503 | Wrong string (typo, `-pooler`, quotes, no `?sslmode=require`), or Neon asleep: retry |
| Login "Incorrect email or password" | Demo users not seeded on this database, or the password differs: re-seed |
| Site loads, "Can't reach the server" | API window closed or crashed: read that window's text |
| Port 8000 / 5173 in use | An earlier run is still open |
