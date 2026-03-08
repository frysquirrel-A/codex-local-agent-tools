[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [int]$Number,
    [ValidateSet("processed", "ignored", "failed")]
    [string]$Status = "processed",
    [string]$Result
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$queuePath = Join-Path $packageRoot "state\\remote_command_queue.json"

if (-not (Test-Path -LiteralPath $queuePath)) {
    throw "Remote command queue was not found."
}

$items = @()
$rawItems = @(Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json)
foreach ($item in $rawItems) {
    $body = [string]$item.body
    $items += [pscustomobject]@{
        number = [int]$item.number
        title = [string]$item.title
        url = [string]$item.url
        user = [string]$item.user
        createdAt = [string]$item.createdAt
        body = $body
        state = [string]$item.state
        matchedBy = if ($item.PSObject.Properties.Name -contains "matchedBy") { [string]$item.matchedBy } else { "legacy" }
        command = if ($item.PSObject.Properties.Name -contains "command") { [string]$item.command } else { "" }
        priority = if ($item.PSObject.Properties.Name -contains "priority") { [string]$item.priority } else { "normal" }
        target = if ($item.PSObject.Properties.Name -contains "target") { [string]$item.target } else { "other" }
        notes = if ($item.PSObject.Properties.Name -contains "notes") { [string]$item.notes } else { "" }
        requestedAt = if ($item.PSObject.Properties.Name -contains "requestedAt") { [string]$item.requestedAt } else { "" }
        status = if ($item.PSObject.Properties.Name -contains "status" -and -not [string]::IsNullOrWhiteSpace([string]$item.status)) { [string]$item.status } else { "new" }
        queuedAt = if ($item.PSObject.Properties.Name -contains "queuedAt") { [string]$item.queuedAt } else { (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") }
        processedAt = if ($item.PSObject.Properties.Name -contains "processedAt") { [string]$item.processedAt } else { $null }
        result = if ($item.PSObject.Properties.Name -contains "result") { [string]$item.result } else { $null }
    }
}
$matched = $false

foreach ($item in $items) {
    if ([int]$item.number -ne $Number) {
        continue
    }

    $item.status = $Status
    $item.processedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    if (-not [string]::IsNullOrWhiteSpace($Result)) {
        $item.result = $Result
    }
    $matched = $true
    break
}

if (-not $matched) {
    throw "Queue item #$Number was not found."
}

$items | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $queuePath -Encoding UTF8

[pscustomobject]@{
    ok = $true
    number = $Number
    status = $Status
    result = $Result
} | ConvertTo-Json -Depth 4
