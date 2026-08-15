# start-local: launch the DigiDex API + web app locally on Windows.
#
# This starts two background processes (uvicorn + vite) and prints their PIDs
# so you can stop them:
#   Stop-Process -Id <API_PID> -Force; Stop-Process -Id <WEB_PID> -Force
# or close this PowerShell window and kill any lingering node/python processes
# that still hold the ports (8000 / 5173).
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\dev.ps1

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

Write-Host "DigiDex local launch"
Write-Host "  - API: http://localhost:8000/docs"
Write-Host "  - Web: http://localhost:5173"
Write-Host "Stopping: Stop-Process -Id <PID> -Force for each PID printed below."

# API (uvicorn) on 8000
$api = Start-Process -FilePath "uv" -ArgumentList "run","uvicorn","apps.api.main:app","--reload","--port","8000" `
    -WorkingDirectory $root -PassThru -WindowStyle Hidden
Write-Host ("API  PID {0}" -f $api.Id)

# Web (vite) on 5173
$web = Start-Process -FilePath "cmd" -ArgumentList "/c","npm run dev" `
    -WorkingDirectory (Join-Path $root "apps\web") -PassThru -WindowStyle Hidden
Write-Host ("WEB  PID {0}" -f $web.Id)

Write-Host ""
Write-Host "Both running. Open http://localhost:5173"
Write-Host ("Stop API: Stop-Process -Id {0} -Force" -f $api.Id)
Write-Host ("Stop WEB: Stop-Process -Id {0} -Force  (also kills its child vite process)" -f $web.Id)
