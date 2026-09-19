# Stops the detached web + bot launched by start-local.ps1 (kills whole trees).
$tmp = Join-Path ([IO.Path]::GetTempPath()) "opencode"

function Kill-Tree([int]$procId) {
  try {
    $kids = Get-CimInstance Win32_Process -Filter "ParentProcessId=$procId" -ErrorAction SilentlyContinue
    foreach ($k in $kids) { Kill-Tree $k.ProcessId }
    Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue
  } catch {}
}

foreach ($name in @("web-local.pid", "bot-local.pid")) {
  $f = Join-Path $tmp $name
  if (Test-Path $f) {
    $id = [int](Get-Content $f -Raw)
    Kill-Tree $id
    Remove-Item $f -Force -ErrorAction SilentlyContinue
    Write-Host "Stopped $name (was PID=$id)"
  }
}
# Fallback: leftover astro dev chains (cmd wrappers show only "astro dev" in
# CommandLine, no repo path) and orphaned bot pythons ("bot\main.py", no repo path).
# Scoped narrowly enough for a dev machine; parses orphans too.
Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {
  ($_.CommandLine -like "*astro*dev*") -or ($_.CommandLine -like "*bot?main.py*")
} | ForEach-Object { Kill-Tree $_.ProcessId; Write-Host "Stopped leftover PID=$($_.ProcessId)" }
Write-Host "Done."
