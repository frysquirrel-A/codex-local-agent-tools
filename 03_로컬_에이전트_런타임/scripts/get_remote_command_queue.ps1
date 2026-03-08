[CmdletBinding()]
param(
    [ValidateSet("all", "new", "pending", "processed")]
    [string]$Status = "all"
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$queuePath = Join-Path $packageRoot "state\\remote_command_queue.json"

if (-not (Test-Path -LiteralPath $queuePath)) {
    [pscustomobject]@{
        ok = $true
        count = 0
        items = @()
    } | ConvertTo-Json -Depth 6
    exit 0
}

$raw = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$items = @($raw)
if ($Status -ne "all") {
    $items = @($items | Where-Object { [string]$_.status -eq $Status })
}

[pscustomobject]@{
    ok = $true
    count = @($items).Count
    items = $items
} | ConvertTo-Json -Depth 6
