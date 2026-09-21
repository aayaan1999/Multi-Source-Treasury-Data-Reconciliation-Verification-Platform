# Runs the whole app on this PC: the FastAPI backend and the React frontend, each in its own window,
# then opens the browser. Close the two windows to stop it.
#
#   .\scripts\run-local.ps1              # start both and open http://localhost:5173
#   .\scripts\run-local.ps1 -NoBrowser   # start both, don't open the browser
#
# One-time setup (see DEPLOYMENT.md / specs/fastapi-backend.md 4a):
#   * backend\.venv exists (python -m venv .venv ; pip install -r requirements.txt)
#   * backend\.env has DATABASE_URL (your Neon string) and JWT_SECRET
#   * frontend packages installed (cd frontend ; npm install)
#   * demo users seeded once (python backend\seed_demo_users.py)
param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$envFile = Join-Path $root 'backend\.env'

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

# -NoExit keeps each window open so you can read errors and logs.
Start-Process powershell -ArgumentList '-NoExit', '-Command',
  "`$Host.UI.RawUI.WindowTitle='API (port 8000)'; Set-Location -LiteralPath '$root\backend'; & '$python' -m uvicorn app.main:app --reload --env-file .env"
Start-Process powershell -ArgumentList '-NoExit', '-Command',
  "`$Host.UI.RawUI.WindowTitle='Frontend (port 5173)'; Set-Location -LiteralPath '$root\frontend'; npm run dev"

# Wait until both answer (up to ~40 s) instead of guessing a delay.
$ready = $false
for ($i = 0; $i -lt 40 -and -not $ready; $i++) {
  try {
    Invoke-RestMethod http://127.0.0.1:8000/api/v1/live -TimeoutSec 2 | Out-Null
    Invoke-WebRequest http://localhost:5173/ -UseBasicParsing -TimeoutSec 2 | Out-Null
    $ready = $true
  } catch { Start-Sleep -Seconds 1 }
}
if (-not $ready) { Write-Warning "The servers didn't answer within 40 s. Look at the two windows for errors." }
if ($ready -and -not $NoBrowser) { Start-Process 'http://localhost:5173' }
Write-Host "App: http://localhost:5173   API docs: http://127.0.0.1:8000/docs   (close the two windows to stop)"
