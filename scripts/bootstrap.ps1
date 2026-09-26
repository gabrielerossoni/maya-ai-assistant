$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
$python = ".maya-venv\Scripts\python.exe"
if (-not (Test-Path $python)) { python -m venv .maya-venv }
& $python -m pip install --upgrade pip
& $python -m pip install -r requirements-dev.txt
& $python -m playwright install chromium
$env:TEMP = Join-Path $root ".tmp\pytest"
$env:TMP = $env:TEMP
New-Item -ItemType Directory -Force $env:TEMP | Out-Null
& $python -m pytest -q
