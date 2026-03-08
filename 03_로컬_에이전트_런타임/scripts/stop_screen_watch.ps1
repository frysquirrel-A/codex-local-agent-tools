[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$pidPath = Join-Path $packageRoot "screen_watch.pid"

$stopped = $false
$pidValue = $null

if (Test-Path -LiteralPath $pidPath) {
    $pidValue = (Get-Content -LiteralPath $pidPath -Raw -Encoding ASCII).Trim()
    if ($pidValue) {
        Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
        $stopped = $true
    }
    Remove-Item -LiteralPath $pidPath -Force -ErrorAction SilentlyContinue
}

Write-Output ([ordered]@{
    ok = $true
    stopped = $stopped
    pid = $pidValue
} | ConvertTo-Json -Depth 4)
