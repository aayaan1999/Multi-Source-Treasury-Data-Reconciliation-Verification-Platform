# Runs the whole app on this PC: the FastAPI backend, the React frontend and the three Camunda bridge
# workers, then opens the browser. By default everything runs hidden in the background (no extra
# windows); output goes to logs\.
#
#   .\scripts\run-local.ps1              # start everything hidden and open http://localhost:5173
#   .\scripts\run-local.ps1 -NoBrowser   # same, don't open the browser
#   .\scripts\run-local.ps1 -NoWorkers   # only the two servers, no bridge workers
#   .\scripts\run-local.ps1 -Windows     # old behaviour: each server in its own PowerShell window
#   .\scripts\run-local.ps1 -Stop        # stop the servers (ports 8000 and 5173) and the bridge workers
#
# The bridge workers (camunda\bridge\, specs/camunda-bpmn-process-design.md) connect the app to Camunda:
#   outcome_worker.py            writes task decisions back to the database
#   poll_worker.py --loop 300    turns new flags, gaps, breaks and duplicates into tasks, every 5 minutes
#   breach_check.py --loop 300   turns KPI limit breaches into tasks for the CRO, every 5 minutes
# They need Camunda running (Docker Desktop, then `docker compose up -d` in camunda\); without it they are
# skipped with a warning and the Tasks tab shows no live tasks. A worker already running isn't started twice.
#
# One-time setup (see DEPLOYMENT.md / specs/fastapi-backend.md 4a):
#   * backend\.venv exists (python -m venv .venv ; pip install -r requirements.txt)
#   * backend\.env has DATABASE_URL (your Neon string) and JWT_SECRET
#   * frontend packages installed (cd frontend ; npm install)
#   * demo users seeded once (python backend\seed_demo_users.py)
param([switch]$NoBrowser, [switch]$Windows, [switch]$Stop, [switch]$NoWorkers)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
$envFile = Join-Path $root 'backend\.env'
$ports = 8000, 5173
$workers = @(
  @{ Name = 'outcome_worker'; Args = @('outcome_worker.py') },
  @{ Name = 'poll_worker';    Args = @('poll_worker.py', '--loop', '300') },
  @{ Name = 'breach_check';   Args = @('breach_check.py', '--loop', '300') }
)

# The running copies of a bridge worker (the venv python and the interpreter it starts both carry the script name).
function Get-Worker($name) {
  Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" | Where-Object { $_.CommandLine -match "$name\.py" }
}

if ($Stop) {
  foreach ($w in $workers) {
    $running = @(Get-Worker $w.Name)
    foreach ($proc in $running) { Stop-Process -Id $proc.ProcessId -Force -ErrorAction SilentlyContinue }
    Write-Host $(if ($running) { "Stopped $($w.Name)" } else { "$($w.Name) wasn't running" })
  }
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

$serversUp = @($ports | Where-Object { Get-NetTCPConnection -LocalPort $_ -State Listen -ErrorAction SilentlyContinue })
if ($serversUp.Count -eq $ports.Count) {
  Write-Host "The API and the website are already running; only missing bridge workers will be started."
} elseif ($serversUp.Count) {
  throw "Port $($serversUp[0]) is already in use but the other server isn't running. Stop it first: .\scripts\run-local.ps1 -Stop"
}
$startServers = $serversUp.Count -eq 0
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

if (-not $startServers) {
  # both already running (see above)
} elseif ($Windows) {
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

if (-not $NoWorkers) {
  # Zeebe's gRPC port answers once Camunda is up.
  $camunda = $false
  try { $tcp = New-Object Net.Sockets.TcpClient; $camunda = $tcp.ConnectAsync('127.0.0.1', 26500).Wait(2000); $tcp.Close() } catch {}
  if (-not $camunda) {
    Write-Warning "Camunda isn't running (nothing on port 26500), so the bridge workers weren't started. Start Docker Desktop, then 'docker compose up -d' in camunda\, then run this script again (the servers already running are left alone)."
  } else {
    $logs = Join-Path $root 'logs'
    New-Item -ItemType Directory -Force -Path $logs | Out-Null
    foreach ($w in $workers) {
      if (Get-Worker $w.Name) { Write-Host "$($w.Name) already running"; continue }
      Start-Process -FilePath $python -ArgumentList $w.Args -WorkingDirectory (Join-Path $root 'camunda\bridge') -WindowStyle Hidden `
        -RedirectStandardOutput (Join-Path $logs "$($w.Name).log") -RedirectStandardError (Join-Path $logs "$($w.Name).err.log")
      Write-Host "Started $($w.Name)"
    }
  }
}

if ($ready -and -not $NoBrowser) { Start-Process 'http://localhost:5173' }
$stopHint = if ($Windows) { 'close the two windows to stop' } else { 'stop with .\scripts\run-local.ps1 -Stop' }
Write-Host "App: http://localhost:5173   API docs: http://127.0.0.1:8000/docs   ($stopHint)"
