# Starts web + bot as DETACHED processes (via WMI) so they keep running after
# this script exits. PIDs saved to temp pid files for stop-local.ps1.
$root = Split-Path $PSScriptRoot -Parent
$tmp = Join-Path ([IO.Path]::GetTempPath()) "opencode"
New-Item -ItemType Directory -Path $tmp -Force | Out-Null

function Start-Detached([string]$cmd, [string]$workdir) {
  $r = Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{
    CommandLine = $cmd; CurrentDirectory = $workdir
  }
  return $r.ProcessId
}

$ps = "$env:SystemRoot\\System32\\WindowsPowerShell\\v1.0\\powershell.exe"
$webPid = Start-Detached "$ps -NoProfile -ExecutionPolicy Bypass -File `"$root\\scripts\\launch-web-bg.ps1`"" "$root\\web"
$botPid = Start-Detached "$ps -NoProfile -ExecutionPolicy Bypass -File `"$root\\scripts\\launch-bot-bg.ps1`"" "$root"
$webPid | Out-File (Join-Path $tmp "web-local.pid") -Encoding ascii
$botPid | Out-File (Join-Path $tmp "bot-local.pid") -Encoding ascii
Write-Host "Started web wrapper PID=$webPid bot wrapper PID=$botPid"
Write-Host "Logs: $tmp\\web-local.log , $tmp\\bot-local.log"
