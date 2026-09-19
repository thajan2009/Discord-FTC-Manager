# Background launcher for web. Spawned detached via start-local.ps1 (WMI), so it
# survives the launching shell. Logs to temp; values never printed.
param([string]$LogPath = (Join-Path ([IO.Path]::GetTempPath()) "opencode\\web-local.log"))
. (Join-Path $PSScriptRoot "Load-Env.ps1")
if (-not $env:PUBLIC_WEB_URL) { $env:PUBLIC_WEB_URL = "http://localhost:4321" }
Set-Location (Join-Path $PSScriptRoot "..\web")
New-Item -ItemType Directory -Path (Split-Path $LogPath) -Force | Out-Null
"--- web start $(Get-Date -Format o) ---" | Out-File $LogPath -Append -Encoding utf8
& "C:\Program Files\nodejs\npm.cmd" run dev *>> $LogPath
