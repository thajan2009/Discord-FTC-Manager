# Run bot locally using repo-root .env (runtime load, no secrets printed).
. (Join-Path $PSScriptRoot "Load-Env.ps1")
if (-not $env:DISCORD_TOKEN) { Write-Host "Missing DISCORD_TOKEN. Add it to .env (one KEY=VALUE per line)."; exit 1 }
if (-not $env:MONGO_URI) { Write-Host "Missing MONGO_URI. Add it to .env."; exit 1 }
python (Join-Path $PSScriptRoot "..\bot\main.py")
