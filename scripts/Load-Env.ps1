# Loads KEY=VALUE lines from repo-root .env into $env at RUNTIME only.
# This file is executed on your machine; the AI never reads your .env.
param([string]$EnvPath = (Join-Path $PSScriptRoot "..\\.env"))
if (-not (Test-Path -LiteralPath $EnvPath)) { Write-Host "No .env at $EnvPath (using process env)."; return }
Get-Content -LiteralPath $EnvPath | ForEach-Object {
  $line = $_.Trim()
  if ($line -eq "" -or $line.StartsWith("#")) { return }
  $idx = $line.IndexOf("=")
  if ($idx -lt 1) { return }
  $k = $line.Substring(0, $idx).Trim()
  $v = $line.Substring($idx + 1).Trim().Trim('"').Trim("'")
  if ($k -ne "") { Set-Item -Path "env:$k" -Value $v }
}
Write-Host "Loaded env from $EnvPath (keys only, values hidden)."
