# Runs the whole app on this PC: the FastAPI backend and the React frontend, then opens the browser.
# By default both servers run hidden in the background (no extra windows); their output goes to logs\.
#
#   .\scripts\run-local.ps1              # start both hidden and open http://localhost:5173
#   .\scripts\run-local.ps1 -NoBrowser   # start both hidden, don't open the browser
#   .\scripts\run-local.ps1 -Windows     # old behaviour: each server in its own PowerShell window
#   .\scripts\run-local.ps1 -Stop        # stop both servers (whatever is listening on ports 8000 and 5173)
#
# One-time setup (see DEPLOYMENT.md / specs/fastapi-backend.md 4a):
#   * backend\.venv exists (python -m venv .venv ; pip install -r requirements.txt)
#   * backend\.env has DATABASE_URL (your Neon string) and JWT_SECRET
#   * frontend packages installed (cd frontend ; npm install)
#   * demo users seeded once (python backend\seed_demo_users.py)
param([switch]$NoBrowser, [switch]$Windows, [switch]$Stop)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$envFile = Join-Path $root 'backend\.env'
$ports = 8000, 5173

if ($Stop) {
  foreach ($p in $ports) {
    $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($c) {
      # /T also ends child processes (uvicorn's --reload worker); errors for already-exited ones are harmless.
      taskkill /PID $c.OwningProcess /T /F 2>&1 | Out-Null
      Write-Host "Stopped port $p (pid $($c.OwningProcess))"
    } else { Write-Host "Nothing running on port $p" }
  }
  return
}

foreach ($p in $ports) {
  if (Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue) {
    throw "Port $p is already in use - the app is probably already running. Stop it first: .\scripts\run-local.ps1 -Stop"
  }
}
if (-not (Test-Path -LiteralPath $python)) {
  throw "backend\.venv not found. Create it: cd backend; python -m venv .venv; .\.venv\Scripts\python.exe -m pip install -r requirements.txt"
}
if (-not (Test-Path -LiteralPath (Join-Path $root 'frontend\node_modules'))) {
  throw "frontend packages missing. Run: cd frontend; npm install"
}
if (-not (Test-Path -LiteralPath $envFile)) {
  throw "backend\.env not found. Copy backend\.env.example to backend\.env and fill in DATABASE_URL and JWT_SECRET."
}
$dbLine = Get-Content -LiteralPath $envFile | Where-Object { $_ -match '^\s*DATABASE_URL\s*=\s*\S' }
if (-not $dbLine) {
  throw "DATABASE_URL is empty in backend\.env. Paste your Neon connection string after 'DATABASE_URL='."
}

if ($Windows) {
  # -NoExit keeps each window open so you can read errors and logs.
  Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "`$Host.UI.RawUI.WindowTitle='API (port 8000)'; Set-Location -LiteralPath '$root\backend'; & '$python' -m uvicorn app.main:app --reload --env-file .env"
  Start-Process powershell -ArgumentList '-NoExit', '-Command',
    "`$Host.UI.RawUI.WindowTitle='Frontend (port 5173)'; Set-Location -LiteralPath '$root\frontend'; npm run dev"
} else {
  # Hidden background processes. Both are started directly (python, node) rather than through a .cmd
  # shim, since the project folder name may contain an '&'. The frontend command is the same one
  # `npm run dev` runs (frontend\package.json).
  $logs = Join-Path $root 'logs'
  New-Item -ItemType Directory -Force -Path $logs | Out-Null
  Start-Process -FilePath $python -ArgumentList '-m', 'uvicorn', 'app.main:app', '--reload', '--env-file', '.env' `
    -WorkingDirectory (Join-Path $root 'backend') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'api.log') -RedirectStandardError (Join-Path $logs 'api.err.log')
  Start-Process -FilePath 'node' -ArgumentList 'node_modules/vite/bin/vite.js' `
    -WorkingDirectory (Join-Path $root 'frontend') -WindowStyle Hidden `
    -RedirectStandardOutput (Join-Path $logs 'frontend.log') -RedirectStandardError (Join-Path $logs 'frontend.err.log')
}

# Wait until both answer (up to ~40 s) instead of guessing a delay.
$ready = $false
for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
  try {
    Invoke-RestMethod http://127.0.0.1:8000/api/v1/live -TimeoutSec 2 | Out-Null
    Invoke-WebRequest http://localhost:5173/ -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ready = $true
  } catch { Start-Sleep -Seconds 1 }
}
$where = if ($Windows) { 'the two windows' } else { 'logs\api.err.log and logs\frontend.log' }
if (-not $ready) { Write-Warning "The servers didn't answer within 40 s. Look at $where for errors." }
if ($ready -and -not $NoBrowser) { Start-Process 'http://localhost:5173' }
$stopHint = if ($Windows) { 'close the two windows to stop' } else { 'stop with .\scripts\run-local.ps1 -Stop' }
Write-Host "App: http://localhost:5173   API docs: http://127.0.0.1:8000/docs   ($stopHint)"
