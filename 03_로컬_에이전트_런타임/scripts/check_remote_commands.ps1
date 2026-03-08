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

try {
    $credentialRaw = "protocol=https`nhost=github.com`n" | git credential fill 2>$null
    if ($LASTEXITCODE -eq 0) {
        foreach ($line in @($credentialRaw)) {
            if ($line -like "password=*") {
                $token = $line.Substring("password=".Length)
                if (-not [string]::IsNullOrWhiteSpace($token)) {
                    $headers["Authorization"] = "Bearer $token"
                    $headers["X-GitHub-Api-Version"] = "2022-11-28"
                }
                break
            }
        }
    }
}
catch {
}

function Get-SectionValue {
    param(
        [string]$Text,
        [string]$Heading
    )

    $pattern = "(?ms)^###\s+" + [regex]::Escape($Heading) + "\s*\r?\n(?<value>.*?)(?=^###\s+|\z)"
    $match = [regex]::Match($Text, $pattern)
    if (-not $match.Success) {
        return ""
    }

    return $match.Groups["value"].Value.Trim()
}

function Convert-IssueToQueueRecord {
    param(
        [object]$Issue,
        [string]$MatchedBy
    )

    $body = [string]$Issue.body
    $command = Get-SectionValue -Text $body -Heading "Command"
    $priority = Get-SectionValue -Text $body -Heading "Priority"
    $target = Get-SectionValue -Text $body -Heading "Target"
    $notes = Get-SectionValue -Text $body -Heading "Notes"
    $requestedAt = Get-SectionValue -Text $body -Heading "Requested At"

    return [pscustomobject]@{
        number = [int]$Issue.number
        title = [string]$Issue.title
        url = [string]$Issue.html_url
        user = [string]$Issue.user.login
        createdAt = [string]$Issue.created_at
        body = $body
        state = [string]$Issue.state
        matchedBy = $MatchedBy
        command = $command
        priority = if ([string]::IsNullOrWhiteSpace($priority)) { "normal" } else { $priority }
        target = if ([string]::IsNullOrWhiteSpace($target)) { "other" } else { $target }
        notes = $notes
        requestedAt = $requestedAt
        status = "new"
        queuedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        processedAt = $null
        result = $null
    }
}

function Normalize-QueueItem {
    param([object]$Item)

    $body = [string]$Item.body
    $command = if ($Item.PSObject.Properties.Name -contains "command") { [string]$Item.command } else { Get-SectionValue -Text $body -Heading "Command" }
    $priority = if ($Item.PSObject.Properties.Name -contains "priority") { [string]$Item.priority } else { Get-SectionValue -Text $body -Heading "Priority" }
    $target = if ($Item.PSObject.Properties.Name -contains "target") { [string]$Item.target } else { Get-SectionValue -Text $body -Heading "Target" }
    $notes = if ($Item.PSObject.Properties.Name -contains "notes") { [string]$Item.notes } else { Get-SectionValue -Text $body -Heading "Notes" }
    $requestedAt = if ($Item.PSObject.Properties.Name -contains "requestedAt") { [string]$Item.requestedAt } else { Get-SectionValue -Text $body -Heading "Requested At" }

    return [pscustomobject]@{
        number = [int]$Item.number
        title = [string]$Item.title
        url = [string]$Item.url
        user = [string]$Item.user
        createdAt = [string]$Item.createdAt
        body = $body
        state = [string]$Item.state
        matchedBy = if ($Item.PSObject.Properties.Name -contains "matchedBy") { [string]$Item.matchedBy } else { "legacy" }
        command = $command
        priority = if ([string]::IsNullOrWhiteSpace($priority)) { "normal" } else { $priority }
        target = if ([string]::IsNullOrWhiteSpace($target)) { "other" } else { $target }
        notes = $notes
        requestedAt = $requestedAt
        status = if ($Item.PSObject.Properties.Name -contains "status" -and -not [string]::IsNullOrWhiteSpace([string]$Item.status)) { [string]$Item.status } else { "new" }
        queuedAt = if ($Item.PSObject.Properties.Name -contains "queuedAt") { [string]$Item.queuedAt } else { (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") }
        processedAt = if ($Item.PSObject.Properties.Name -contains "processedAt") { [string]$Item.processedAt } else { $null }
        result = if ($Item.PSObject.Properties.Name -contains "result") { [string]$Item.result } else { $null }
    }
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
    $queueResponse = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $rawQueue = foreach ($entry in @($queueResponse)) { $entry }
    $queue = @($rawQueue | ForEach-Object { Normalize-QueueItem -Item $_ })
} else {
    $queue = @()
}

$existingNumbers = @{}
foreach ($item in $queue) {
    $existingNumbers[[int]$item.number] = $true
}

$uri = "{0}/repos/{1}/{2}/issues?state=open&sort=created&direction=asc&per_page=30" -f $config.apiBase, $config.owner, $config.repo
$issueResponse = Invoke-RestMethod -Uri $uri -Headers $headers -Method Get
$issues = foreach ($issue in $issueResponse) { $issue }
$newItems = @()
$lastSeen = [int]$state.lastSeenIssueNumber

foreach ($issue in $issues) {
    if ($issue.pull_request) {
        continue
    }

    $labelMatch = @($issue.labels | Where-Object { [string]$_.name -eq [string]$config.label }).Count -gt 0
    $titleMatch = ([string]$issue.title).StartsWith([string]$config.titlePrefix, [System.StringComparison]::OrdinalIgnoreCase)
    if (-not $labelMatch -and -not $titleMatch) {
        continue
    }

    $number = [int]$issue.number
    if ($number -le $lastSeen) {
        continue
    }

    if ($existingNumbers.ContainsKey($number)) {
        if ($number -gt $lastSeen) {
            $lastSeen = $number
        }
        continue
    }

    $matchedBy = if ($labelMatch) { "label" } elseif ($titleMatch) { "titlePrefix" } else { "unknown" }
    $record = Convert-IssueToQueueRecord -Issue $issue -MatchedBy $matchedBy
    $newItems += $record
    $queue += $record
    $existingNumbers[$number] = $true
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
    pendingCount = @($queue | Where-Object { $_.status -in @("new", "pending") }).Count
    newCount = @($newItems).Count
    lastSeenIssueNumber = $state.lastSeenIssueNumber
    siteUrl = [string]$config.siteUrl
} | ConvertTo-Json -Depth 6
