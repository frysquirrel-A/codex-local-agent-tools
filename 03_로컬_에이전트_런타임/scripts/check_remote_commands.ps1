[CmdletBinding()]
param(
    [switch]$ShowPopup
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$configPath = Join-Path $packageRoot "config\\remote_command_channel.json"
$stateDir = Join-Path $packageRoot "state"
$statePath = Join-Path $stateDir "remote_command_state.json"
$queuePath = Join-Path $stateDir "remote_command_queue.json"

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
}

$config = Get-Content -LiteralPath $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$headers = @{
    "User-Agent" = "CodexLocalAgentRemotePoller"
    "Accept" = "application/vnd.github+json"
}

if (Test-Path -LiteralPath $statePath) {
    $state = Get-Content -LiteralPath $statePath -Raw -Encoding UTF8 | ConvertFrom-Json
} else {
    $state = [pscustomobject]@{
        lastSeenIssueNumber = 0
        lastCheckedAt = $null
    }
}

if (Test-Path -LiteralPath $queuePath) {
    $queue = @(Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json)
} else {
    $queue = @()
}

$uri = "{0}/repos/{1}/{2}/issues?state=open&labels={3}&sort=created&direction=asc&per_page=30" -f $config.apiBase, $config.owner, $config.repo, $config.label
$issues = @(Invoke-RestMethod -Uri $uri -Headers $headers -Method Get)
$newItems = @()
$lastSeen = [int]$state.lastSeenIssueNumber

foreach ($issue in $issues) {
    if ($issue.pull_request) {
        continue
    }

    $number = [int]$issue.number
    if ($number -le $lastSeen) {
        continue
    }

    $record = [ordered]@{
        number = $number
        title = [string]$issue.title
        url = [string]$issue.html_url
        user = [string]$issue.user.login
        createdAt = [string]$issue.created_at
        body = [string]$issue.body
        state = [string]$issue.state
    }
    $newItems += [pscustomobject]$record
    $queue += [pscustomobject]$record
    if ($number -gt $lastSeen) {
        $lastSeen = $number
    }
}

$state = [pscustomobject]@{
    lastSeenIssueNumber = $lastSeen
    lastCheckedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
}

$state | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $statePath -Encoding UTF8
$queue | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $queuePath -Encoding UTF8

if ($ShowPopup -and $newItems.Count -gt 0) {
    $shell = New-Object -ComObject WScript.Shell
    foreach ($item in $newItems) {
        $message = "새 원격 명령 #" + $item.number + "`n" + $item.title
        $null = $shell.Popup($message, 8, "Codex Remote Command", 64)
    }
}

[pscustomobject]@{
    ok = $true
    checkedAt = $state.lastCheckedAt
    queueCount = @($queue).Count
    newCount = @($newItems).Count
    lastSeenIssueNumber = $state.lastSeenIssueNumber
    siteUrl = [string]$config.siteUrl
} | ConvertTo-Json -Depth 6
