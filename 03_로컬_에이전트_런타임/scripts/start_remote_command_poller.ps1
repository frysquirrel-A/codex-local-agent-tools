[CmdletBinding()]
param(
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$stateDir = Join-Path $packageRoot "state"
$workerPath = Join-Path $scriptRoot "remote_command_worker.ps1"
$pidPath = Join-Path $stateDir "remote_command_poller.pid"

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
}

$command = "-NoProfile -ExecutionPolicy Bypass -File `"$workerPath`" -PollSeconds $PollSeconds"
$process = Start-Process -FilePath "powershell.exe" -ArgumentList $command -WindowStyle Hidden -PassThru
$process.Id | Set-Content -LiteralPath $pidPath -Encoding ASCII

[pscustomobject]@{
    ok = $true
    pid = $process.Id
    pollSeconds = $PollSeconds
    pidPath = $pidPath
} | ConvertTo-Json -Depth 4
