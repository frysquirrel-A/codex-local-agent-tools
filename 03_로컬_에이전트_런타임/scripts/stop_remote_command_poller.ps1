[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$pidPath = Join-Path $packageRoot "state\\remote_command_poller.pid"

if (-not (Test-Path -LiteralPath $pidPath)) {
    [pscustomobject]@{
        ok = $true
        stopped = $false
        reason = "pid file not found"
    } | ConvertTo-Json -Depth 4
    exit 0
}

$pidValue = Get-Content -LiteralPath $pidPath -Raw -Encoding ASCII
if ($pidValue -match '^\d+$') {
    $process = Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue
    if ($process) {
        Stop-Process -Id $process.Id -Force
    }
}

Remove-Item -LiteralPath $pidPath -Force

[pscustomobject]@{
    ok = $true
    stopped = $true
    pid = $pidValue
} | ConvertTo-Json -Depth 4
