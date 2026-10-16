# Starts backend (new window) and frontend dev server.
# Usage: scripts\dev-windows.ps1 [-Mock]   (-Mock = fake in-memory devices, for testing without hardware)
param([switch]$Mock)
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot

if (-not (Test-Path "$root\backend\.venv")) {
  py -3.13 -m venv "$root\backend\.venv"
  & "$root\backend\.venv\Scripts\python.exe" -m pip install -q -e "$root\backend[dev]"
}
$env:USE_MOCK_ADAPTERS = if ($Mock) { 'true' } else { 'false' }
Start-Process powershell -ArgumentList '-NoExit','-Command',"cd '$root\backend'; .\.venv\Scripts\python.exe run.py"

Push-Location "$root\frontend"
if (-not (Test-Path node_modules)) { npm install }
npm run dev
Pop-Location
