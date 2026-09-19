# Background launcher for bot. Spawned detached via start-local.ps1 (WMI), so it
# survives the launching shell. main.py also reads repo-root .env itself at runtime.
param([string]$LogPath = (Join-Path ([IO.Path]::GetTempPath()) "opencode\\bot-local.log"))
. (Join-Path $PSScriptRoot "Load-Env.ps1")
Set-Location (Join-Path $PSScriptRoot "..")
New-Item -ItemType Directory -Path (Split-Path $LogPath) -Force | Out-Null
"--- bot start $(Get-Date -Format o) ---" | Out-File $LogPath -Append -Encoding utf8
python -u bot/main.py *>> $LogPath
