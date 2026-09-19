# Run web locally using repo-root .env (runtime load, no secrets printed).
. (Join-Path $PSScriptRoot "Load-Env.ps1")
if (-not $env:PUBLIC_WEB_URL) { $env:PUBLIC_WEB_URL = "http://localhost:4321" }
& "C:\Program Files\nodejs\npm.cmd" --prefix (Join-Path $PSScriptRoot "..\web") run dev
