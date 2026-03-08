[CmdletBinding()]
param(
    [int]$MaxItems = 0,
    [int[]]$Number,
    [switch]$DryRunOnly
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$packageGroupRoot = Split-Path -Parent $packageRoot
$toolRoot = Split-Path -Parent $packageGroupRoot
$featureRoot = Get-ChildItem -LiteralPath $toolRoot -Directory | Where-Object { $_.Name -like "01_*" } | Select-Object -First 1 -ExpandProperty FullName
$browserRoot = Get-ChildItem -LiteralPath $featureRoot -Directory | Where-Object { $_.Name -like "*DOM*" } | Select-Object -First 1 -ExpandProperty FullName
$desktopRoot = Get-ChildItem -LiteralPath $featureRoot -Directory | Where-Object { $_.Name -like "*KVM*" } | Select-Object -First 1 -ExpandProperty FullName
$configDir = Join-Path $packageRoot "config"
$stateDir = Join-Path $packageRoot "state"
$lockDir = Join-Path $stateDir "remote_command_locks"
$logDir = Join-Path $packageRoot "logs"
$queuePath = Join-Path $stateDir "remote_command_queue.json"
$logPath = Join-Path $logDir "remote_executor.jsonl"
$channelPath = Join-Path $configDir "remote_command_channel.json"
$agentPolicyPath = Join-Path $configDir "agent_policy.json"
$executionPolicyPath = Join-Path $configDir "remote_command_execution_policy.json"
$taskRunner = Join-Path $scriptRoot "invoke_local_agent_task.ps1"
$bridgeWrapper = Join-Path $browserRoot "send_live_page_command.ps1"
$desktopCore = Join-Path $desktopRoot "scripts\\desktop_control.py"
$screenCapture = Join-Path $desktopRoot "scripts\\capture_screen.ps1"

if (-not $featureRoot) {
    throw "Shared feature root was not found under $toolRoot"
}

if (-not $browserRoot) {
    throw "Browser tool directory was not found under $toolRoot"
}

if (-not $desktopRoot) {
    throw "Desktop tool directory was not found under $toolRoot"
}

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Force -Path $logDir | Out-Null
}

if (-not (Test-Path -LiteralPath $lockDir)) {
    New-Item -ItemType Directory -Force -Path $lockDir | Out-Null
}

function Read-JsonFile {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        throw "Required file was not found: $Path"
    }

    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-TextValue {
    param([object]$Value)

    if ($null -eq $Value) {
        return ""
    }

    return [string]$Value
}

function Write-ExecutorLog {
    param(
        [string]$Phase,
        [hashtable]$Payload
    )

    $record = [ordered]@{
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        phase = $Phase
    }

    foreach ($key in $Payload.Keys) {
        $record[$key] = $Payload[$key]
    }

    Add-Content -LiteralPath $logPath -Value ($record | ConvertTo-Json -Compress -Depth 10) -Encoding UTF8
}

function Get-HashValue {
    param([string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return ""
    }

    return (Get-FileHash -LiteralPath $Path -Algorithm SHA256).Hash
}

function Save-JsonArtifact {
    param(
        [string]$Path,
        [object]$Payload
    )

    $dir = Split-Path -Parent $Path
    if (-not (Test-Path -LiteralPath $dir)) {
        New-Item -ItemType Directory -Force -Path $dir | Out-Null
    }

    $Payload | ConvertTo-Json -Depth 12 | Set-Content -LiteralPath $Path -Encoding UTF8
    return (Get-HashValue -Path $Path)
}

function Get-GitHubHeaders {
    $credentialInput = "protocol=https`nhost=github.com`n"
    $raw = $credentialInput | git credential fill 2>$null

    if ($LASTEXITCODE -ne 0) {
        throw "GitHub credentials were not available from git credential fill."
    }

    $map = @{}
    foreach ($line in @($raw)) {
        if ($line -match "^(?<key>[^=]+)=(?<value>.*)$") {
            $map[$matches["key"]] = $matches["value"]
        }
    }

    $token = Get-TextValue -Value $map["password"]
    if ([string]::IsNullOrWhiteSpace($token)) {
        throw "GitHub token was empty."
    }

    return @{
        "Authorization" = "Bearer $token"
        "Accept" = "application/vnd.github+json"
        "User-Agent" = "CodexLocalAgentRemoteExecutor"
        "X-GitHub-Api-Version" = "2022-11-28"
    }
}

function Invoke-GitHubApi {
    param(
        [string]$Method,
        [string]$Path,
        [object]$Body
    )

    $channel = Read-JsonFile -Path $channelPath
    $uri = "{0}{1}" -f $channel.apiBase, $Path
    $headers = Get-GitHubHeaders

    if ($null -eq $Body) {
        return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers
    }

    $json = $Body | ConvertTo-Json -Depth 12
    return Invoke-RestMethod -Method $Method -Uri $uri -Headers $headers -ContentType "application/json" -Body $json
}

function Add-IssueComment {
    param(
        [string]$Owner,
        [string]$Repo,
        [int]$Number,
        [string]$Body
    )

    return Invoke-GitHubApi -Method "POST" -Path "/repos/$Owner/$Repo/issues/$Number/comments" -Body @{ body = $Body }
}

function Close-Issue {
    param(
        [string]$Owner,
        [string]$Repo,
        [int]$Number
    )

    return Invoke-GitHubApi -Method "PATCH" -Path "/repos/$Owner/$Repo/issues/$Number" -Body @{ state = "closed" }
}

function Set-QueueStatus {
    param(
        [int]$Number,
        [string]$Status,
        [string]$Result
    )

    $queueResponse = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $items = foreach ($entry in @($queueResponse)) { $entry }
    $matched = $false

    foreach ($item in $items) {
        if ([int]$item.number -ne $Number) {
            continue
        }

        $item.status = $Status
        if ($Status -eq "pending") {
            $item.processedAt = $null
        }
        else {
            $item.processedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        }

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
}

function Acquire-ExecutionLock {
    param([int]$Number)

    $path = Join-Path $lockDir ("issue_{0}.lock" -f $Number)
    try {
        New-Item -ItemType File -Path $path -Force:$false -ErrorAction Stop | Out-Null
        Set-Content -LiteralPath $path -Value (Get-Date).ToString("yyyy-MM-dd HH:mm:ss") -Encoding UTF8
        return $path
    }
    catch {
        return $null
    }
}

function Release-ExecutionLock {
    param([string]$Path)

    if ($Path -and (Test-Path -LiteralPath $Path)) {
        Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
    }
}

function Get-QueueItems {
    if (-not (Test-Path -LiteralPath $queuePath)) {
        return @()
    }

    $queueResponse = Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json
    $items = foreach ($entry in @($queueResponse)) { $entry }
    $filtered = @($items | Where-Object { [string]$_.status -in @("new", "pending") })
    if ($Number -and $Number.Count -gt 0) {
        $numberSet = @{}
        foreach ($value in $Number) {
            $numberSet[[int]$value] = $true
        }
        $filtered = @($filtered | Where-Object { $numberSet.ContainsKey([int]$_.number) })
    }

    $filtered = @($filtered | Sort-Object @{ Expression = { if ([string]$_.status -eq "pending") { 0 } else { 1 } } }, @{ Expression = { [int]$_.number } })
    return $filtered
}

function Test-KeywordHit {
    param(
        [string]$Text,
        [string[]]$Keywords
    )

    foreach ($keyword in $Keywords) {
        if ([string]::IsNullOrWhiteSpace($keyword)) {
            continue
        }

        if ($Text.IndexOf($keyword, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            return $true
        }
    }

    return $false
}

function Try-ParseStructuredCommand {
    param([string]$Text)

    if ([string]::IsNullOrWhiteSpace($Text)) {
        return $null
    }

    try {
        $parsed = $Text | ConvertFrom-Json -ErrorAction Stop
    }
    catch {
        return $null
    }

    if (-not $parsed.PSObject.Properties.Name -contains "mode") {
        return $null
    }

    if (-not $parsed.PSObject.Properties.Name -contains "action" -and [string]$parsed.mode -ne "llm-prompt") {
        return $null
    }

    return $parsed
}

function Get-ResponsiveBridgeClient {
    param([string]$UrlHint)

    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8765/status" -Method Get -TimeoutSec 2
    $clients = @($status.clients)
    if ($UrlHint) {
        $clients = @($clients | Where-Object { [string]$_.url -like "*$UrlHint*" })
    }

    if (-not $clients -or $clients.Count -eq 0) {
        throw "No bridge clients matched the requested hint."
    }

    $pool = if ($executionPolicy.preferBackgroundBridgeClient) {
        @($clients | Sort-Object @{ Expression = { if ($_.focused -or $_.active) { 1 } else { 0 } } }, @{ Expression = { -1 * [double]$_.timestamp } })
    }
    else {
        @($clients | Sort-Object @{ Expression = { if ($_.active) { 0 } else { 1 } } }, @{ Expression = { -1 * [double]$_.timestamp } })
    }

    foreach ($candidate in $pool) {
        $raw = & $bridgeWrapper "ping" "--client-id" ([string]$candidate.clientId) "--timeout" "2" 2>$null
        if ($LASTEXITCODE -ne 0) {
            continue
        }

        try {
            $payload = $raw | ConvertFrom-Json
            if ($payload.ok) {
                return [string]$candidate.clientId
            }
        }
        catch {
        }
    }

    throw "No responsive bridge client was found."
}

function Invoke-BridgeJson {
    param([string[]]$Arguments)

    $raw = & $bridgeWrapper @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Bridge command failed: $($Arguments -join ' ')"
    }

    return $raw | ConvertFrom-Json
}

function Get-CommentBody {
    param(
        [string]$Status,
        [pscustomobject]$QueueItem,
        [object]$Spec,
        [string]$PlanHash,
        [string]$ResultHash,
        [string]$Message
    )

    $mode = if ($Spec) { Get-TextValue -Value $Spec.mode } else { "n/a" }
    $action = if ($Spec -and $Spec.PSObject.Properties.Name -contains "action") { Get-TextValue -Value $Spec.action } else { "n/a" }
    $now = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")

    $body = "## Codex Remote Executor`n`n"
    $body += "- Status: $Status`n"
    $body += "- Queue item: #$($QueueItem.number)`n"
    $body += "- User: $($QueueItem.user)`n"
    $body += "- Mode: $mode`n"
    $body += "- Action: $action`n"
    $body += "- Plan SHA256: $PlanHash`n"
    $body += "- Result SHA256: $ResultHash`n"
    $body += "- Timestamp: $now`n`n"
    $body += $Message
    return $body
}

function Get-ExecutionDecision {
    param(
        [pscustomobject]$Item,
        [object]$Spec
    )

    $specText = if ($Spec) { $Spec | ConvertTo-Json -Depth 8 -Compress } else { "" }
    $joined = (@(
        (Get-TextValue -Value $Item.command)
        (Get-TextValue -Value $Item.notes)
        $specText
    ) -join " ").Trim()

    $isTrusted = @($executionPolicy.trustedIssueUsers) -contains [string]$Item.user
    if (-not $isTrusted) {
        return [pscustomobject]@{
            outcome = "ignored"
            status = "ignored"
            shouldExecute = $false
            shouldComment = [bool]$executionPolicy.commentOnIgnoredExternalCommands
            shouldClose = $false
            reason = "Issue author is not in the trusted remote command allowlist."
        }
    }

    if (-not $Spec) {
        return [pscustomobject]@{
            outcome = "manual-review"
            status = "failed"
            shouldExecute = $false
            shouldComment = [bool]$executionPolicy.commentOnManualReview
            shouldClose = $false
            reason = "Command is not structured JSON. V1 executor only auto-runs structured commands."
        }
    }

    if (-not (@($executionPolicy.autoExecuteModes) -contains [string]$Spec.mode)) {
        return [pscustomobject]@{
            outcome = "manual-review"
            status = "failed"
            shouldExecute = $false
            shouldComment = [bool]$executionPolicy.commentOnManualReview
            shouldClose = $false
            reason = "Mode '$($Spec.mode)' is not enabled for automatic execution."
        }
    }

    if (Test-KeywordHit -Text $joined -Keywords @($agentPolicy.keywordGroups.financialExecution)) {
        return [pscustomobject]@{
            outcome = "blocked"
            status = "failed"
            shouldExecute = $false
            shouldComment = [bool]$executionPolicy.commentOnFailure
            shouldClose = $false
            reason = [string]$agentPolicy.blockedCategories.financialExecution.message
        }
    }

    if (Test-KeywordHit -Text $joined -Keywords @($agentPolicy.keywordGroups.spendingApproval)) {
        return [pscustomobject]@{
            outcome = "approval-needed"
            status = "failed"
            shouldExecute = $false
            shouldComment = [bool]$executionPolicy.commentOnFailure
            shouldClose = $false
            reason = [string]$agentPolicy.approvalCategories.spendingApproval.message
        }
    }

    if ([string]$Spec.mode -eq "browser-command") {
        if (-not (@($executionPolicy.browserAllowedActions) -contains [string]$Spec.action)) {
            return [pscustomobject]@{
                outcome = "manual-review"
                status = "failed"
                shouldExecute = $false
                shouldComment = [bool]$executionPolicy.commentOnManualReview
                shouldClose = $false
                reason = "Browser action '$($Spec.action)' is not in the allowlist."
            }
        }
    }
    elseif ([string]$Spec.mode -eq "desktop-command") {
        if (-not (@($executionPolicy.desktopAllowedActions) -contains [string]$Spec.action)) {
            return [pscustomobject]@{
                outcome = "manual-review"
                status = "failed"
                shouldExecute = $false
                shouldComment = [bool]$executionPolicy.commentOnManualReview
                shouldClose = $false
                reason = "Desktop action '$($Spec.action)' is not in the allowlist."
            }
        }
    }
    elseif ([string]$Spec.mode -eq "llm-prompt") {
        if (-not (@($executionPolicy.llmAllowedProviders) -contains [string]$Spec.provider)) {
            return [pscustomobject]@{
                outcome = "manual-review"
                status = "failed"
                shouldExecute = $false
                shouldComment = [bool]$executionPolicy.commentOnManualReview
                shouldClose = $false
                reason = "Provider '$($Spec.provider)' is not in the allowlist."
            }
        }
    }

    return [pscustomobject]@{
        outcome = "ready"
        status = "processed"
        shouldExecute = $true
        shouldComment = [bool]$executionPolicy.commentOnSuccess
        shouldClose = [bool]$executionPolicy.closeIssueOnSuccess
        reason = "Structured command passed trust and allowlist checks."
    }
}

function Invoke-BrowserSpec {
    param(
        [object]$Spec,
        [string]$ArtifactDir
    )

    $clientId = Get-ResponsiveBridgeClient -UrlHint (Get-TextValue -Value $Spec.urlHint)
    $bridgeArgs = @([string]$Spec.action, "--client-id", $clientId, "--timeout", "10")

    switch ([string]$Spec.action) {
        "navigate" {
            $bridgeArgs += @("--url", [string]$Spec.url)
        }
        "click-text" {
            $bridgeArgs += @("--text", [string]$Spec.text)
            if ($Spec.PSObject.Properties.Name -contains "contains" -and [bool]$Spec.contains) {
                $bridgeArgs += "--contains"
            }
        }
        "visible-text" {
            if ($Spec.PSObject.Properties.Name -contains "selector" -and -not [string]::IsNullOrWhiteSpace([string]$Spec.selector)) {
                $bridgeArgs += @("--selector", [string]$Spec.selector)
            }
            if ($Spec.PSObject.Properties.Name -contains "maxChars") {
                $bridgeArgs += @("--max-chars", [string]$Spec.maxChars)
            }
        }
        "set-text" {
            if ($Spec.PSObject.Properties.Name -contains "selector" -and -not [string]::IsNullOrWhiteSpace([string]$Spec.selector)) {
                $bridgeArgs += @("--selector", [string]$Spec.selector)
            }
            $bridgeArgs += @("--text", [string]$Spec.text)
        }
        "click" {
            $bridgeArgs += @("--selector", [string]$Spec.selector)
        }
        default {
            throw "Unsupported browser action: $($Spec.action)"
        }
    }

    $result = Invoke-BridgeJson -Arguments $bridgeArgs
    return [pscustomobject]@{
        ok = [bool]$result.ok
        clientId = $clientId
        payload = $result
    }
}

function Invoke-DesktopCore {
    param([string[]]$Arguments)

    $raw = & python $desktopCore @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Desktop control command failed: python $desktopCore $($Arguments -join ' ')"
    }

    return (($raw | Out-String).Trim() | ConvertFrom-Json)
}

function Invoke-DesktopSpec {
    param(
        [object]$Spec,
        [string]$ArtifactDir
    )

    $action = [string]$Spec.action
    $beforePath = ""
    $afterPath = ""
    if ($action -in @("focus-window", "click", "type", "combo")) {
        $beforePath = Join-Path $ArtifactDir "before.png"
        & $screenCapture -OutPath $beforePath | Out-Null
    }

    switch ($action) {
        "screen-capture" {
            $capturePath = Join-Path $ArtifactDir "screen.png"
            $resolved = & $screenCapture -OutPath $capturePath
            if ($LASTEXITCODE -ne 0) {
                throw "Screen capture failed."
            }
            $result = [pscustomobject]@{
                ok = $true
                path = ($resolved | Select-Object -Last 1)
            }
        }
        "screen-size" {
            $result = Invoke-DesktopCore -Arguments @("screen-size")
        }
        "cursor-pos" {
            $result = Invoke-DesktopCore -Arguments @("cursor-pos")
        }
        "list-windows" {
            $desktopArgs = @("list-windows")
            if ($Spec.PSObject.Properties.Name -contains "contains" -and -not [string]::IsNullOrWhiteSpace([string]$Spec.contains)) {
                $desktopArgs += @("--contains", [string]$Spec.contains)
            }
            $result = Invoke-DesktopCore -Arguments $desktopArgs
        }
        "focus-window" {
            $result = Invoke-DesktopCore -Arguments @("focus-window", "--contains", [string]$Spec.contains)
        }
        "click" {
            $desktopArgs = @("click", "--x", [string]$Spec.x, "--y", [string]$Spec.y)
            if ($Spec.PSObject.Properties.Name -contains "button" -and -not [string]::IsNullOrWhiteSpace([string]$Spec.button)) {
                $desktopArgs += @("--button", [string]$Spec.button)
            }
            if ($Spec.PSObject.Properties.Name -contains "double" -and [bool]$Spec.double) {
                $desktopArgs += "--double"
            }
            $result = Invoke-DesktopCore -Arguments $desktopArgs
        }
        "type" {
            $desktopArgs = @("type", "--text", [string]$Spec.text)
            if ($Spec.PSObject.Properties.Name -contains "intervalMs") {
                $desktopArgs += @("--interval-ms", [string]$Spec.intervalMs)
            }
            $result = Invoke-DesktopCore -Arguments $desktopArgs
        }
        "combo" {
            $result = Invoke-DesktopCore -Arguments @("combo", "--keys", [string]$Spec.keys)
        }
        default {
            throw "Unsupported desktop action: $action"
        }
    }

    if ($action -in @("focus-window", "click", "type", "combo")) {
        $afterPath = Join-Path $ArtifactDir "after.png"
        & $screenCapture -OutPath $afterPath | Out-Null
    }

    return [pscustomobject]@{
        ok = [bool]$result.ok
        payload = $result
        beforeCapture = $beforePath
        afterCapture = $afterPath
    }
}

function Invoke-LlmSpec {
    param([object]$Spec)

    $runnerArgs = @("-Mode", "llm-prompt", "-Provider", [string]$Spec.provider, "-Prompt", [string]$Spec.prompt)
    if (-not ($Spec.PSObject.Properties.Name -contains "send") -or [bool]$Spec.send) {
        $runnerArgs += "-Send"
    }
    if ($Spec.PSObject.Properties.Name -contains "waitForText" -and -not [string]::IsNullOrWhiteSpace([string]$Spec.waitForText)) {
        $runnerArgs += @("-WaitForText", [string]$Spec.waitForText)
    }

    $raw = & $taskRunner @runnerArgs
    if ($LASTEXITCODE -ne 0) {
        throw "LLM task runner failed."
    }

    return (($raw | Out-String).Trim() | ConvertFrom-Json)
}

function Invoke-StructuredSpec {
    param(
        [object]$Spec,
        [string]$ArtifactDir
    )

    switch ([string]$Spec.mode) {
        "browser-command" {
            return Invoke-BrowserSpec -Spec $Spec -ArtifactDir $ArtifactDir
        }
        "desktop-command" {
            return Invoke-DesktopSpec -Spec $Spec -ArtifactDir $ArtifactDir
        }
        "llm-prompt" {
            return Invoke-LlmSpec -Spec $Spec
        }
        default {
            throw "Unsupported structured command mode: $($Spec.mode)"
        }
    }
}

$channel = Read-JsonFile -Path $channelPath
$agentPolicy = Read-JsonFile -Path $agentPolicyPath
$executionPolicy = Read-JsonFile -Path $executionPolicyPath
$artifactRoot = Join-Path $packageRoot ([string]$executionPolicy.artifactRoot)
if (-not (Test-Path -LiteralPath $artifactRoot)) {
    New-Item -ItemType Directory -Force -Path $artifactRoot | Out-Null
}

$items = Get-QueueItems
$limit = if ($MaxItems -gt 0) { $MaxItems } else { [int]$executionPolicy.maxItemsPerRun }
if ($limit -gt 0) {
    $items = @($items | Select-Object -First $limit)
}

$results = @()
foreach ($item in $items) {
    $startedAt = Get-Date
    $artifactDir = Join-Path $artifactRoot ("issue_{0}_{1}" -f [int]$item.number, ($startedAt.ToString("yyyyMMdd_HHmmss")))
    New-Item -ItemType Directory -Force -Path $artifactDir | Out-Null
    $lockPath = Acquire-ExecutionLock -Number ([int]$item.number)

    if (-not $lockPath) {
        Write-ExecutorLog -Phase "skipped-locked" -Payload @{
            issueNumber = [int]$item.number
        }
        $results += [ordered]@{
            number = [int]$item.number
            outcome = "skipped-locked"
            status = [string]$item.status
            reason = "Another executor already holds the issue lock."
        }
        continue
    }

    try {
        $spec = Try-ParseStructuredCommand -Text (Get-TextValue -Value $item.command)
        $decision = Get-ExecutionDecision -Item $item -Spec $spec
        $plan = [ordered]@{
            issueNumber = [int]$item.number
            issueTitle = [string]$item.title
            issueUser = [string]$item.user
            issueUrl = [string]$item.url
            requestedAt = [string]$item.requestedAt
            dryRunOnly = [bool]$DryRunOnly
            decision = $decision
            structuredCommand = $spec
        }
        $planPath = Join-Path $artifactDir "plan.json"
        $planHash = Save-JsonArtifact -Path $planPath -Payload $plan

        Write-ExecutorLog -Phase "plan" -Payload @{
            issueNumber = [int]$item.number
            issueUser = [string]$item.user
            outcome = [string]$decision.outcome
            shouldExecute = [bool]$decision.shouldExecute
            planHash = $planHash
        }

        if (-not $decision.shouldExecute -or $DryRunOnly) {
            $status = if ($DryRunOnly) { "pending" } else { [string]$decision.status }
            $resultMessage = if ($DryRunOnly) { "dry-run created" } else { [string]$decision.reason }
            Set-QueueStatus -Number ([int]$item.number) -Status $status -Result $resultMessage

            if ($decision.shouldComment) {
                $commentBody = Get-CommentBody -Status (if ($DryRunOnly) { "dry-run" } else { [string]$decision.outcome }) -QueueItem $item -Spec $spec -PlanHash $planHash -ResultHash "" -Message $resultMessage
                Add-IssueComment -Owner $channel.owner -Repo $channel.repo -Number ([int]$item.number) -Body $commentBody | Out-Null
            }

            $results += [ordered]@{
                number = [int]$item.number
                outcome = if ($DryRunOnly) { "dry-run" } else { [string]$decision.outcome }
                status = $status
                reason = $resultMessage
                planPath = $planPath
            }
            continue
        }

        Set-QueueStatus -Number ([int]$item.number) -Status "pending" -Result "execution started"
        $executionResult = Invoke-StructuredSpec -Spec $spec -ArtifactDir $artifactDir
        $resultPath = Join-Path $artifactDir "result.json"
        $resultHash = Save-JsonArtifact -Path $resultPath -Payload $executionResult

        if ($decision.shouldComment) {
            $commentBody = Get-CommentBody -Status "success" -QueueItem $item -Spec $spec -PlanHash $planHash -ResultHash $resultHash -Message "Execution finished successfully."
            Add-IssueComment -Owner $channel.owner -Repo $channel.repo -Number ([int]$item.number) -Body $commentBody | Out-Null
        }

        if ($decision.shouldClose) {
            Close-Issue -Owner $channel.owner -Repo $channel.repo -Number ([int]$item.number) | Out-Null
        }

        Set-QueueStatus -Number ([int]$item.number) -Status "processed" -Result "success"
        Write-ExecutorLog -Phase "success" -Payload @{
            issueNumber = [int]$item.number
            mode = [string]$spec.mode
            action = if ($spec.PSObject.Properties.Name -contains "action") { [string]$spec.action } else { "llm-prompt" }
            planHash = $planHash
            resultHash = $resultHash
        }

        $results += [ordered]@{
            number = [int]$item.number
            outcome = "success"
            status = "processed"
            planPath = $planPath
            resultPath = $resultPath
        }
    }
    catch {
        $errorPayload = [ordered]@{
            ok = $false
            error = $_.Exception.Message
        }
        $resultPath = Join-Path $artifactDir "result.json"
        $resultHash = Save-JsonArtifact -Path $resultPath -Payload $errorPayload

        if ($decision.shouldComment) {
            $commentBody = Get-CommentBody -Status "failed" -QueueItem $item -Spec $spec -PlanHash $planHash -ResultHash $resultHash -Message $_.Exception.Message
            Add-IssueComment -Owner $channel.owner -Repo $channel.repo -Number ([int]$item.number) -Body $commentBody | Out-Null
        }

        Set-QueueStatus -Number ([int]$item.number) -Status "failed" -Result $_.Exception.Message
        Write-ExecutorLog -Phase "failed" -Payload @{
            issueNumber = [int]$item.number
            error = $_.Exception.Message
            planHash = $planHash
            resultHash = $resultHash
        }

        $results += [ordered]@{
            number = [int]$item.number
            outcome = "failed"
            status = "failed"
            reason = $_.Exception.Message
            planPath = $planPath
            resultPath = $resultPath
        }
    }
    finally {
        Release-ExecutionLock -Path $lockPath
    }
}

[ordered]@{
    ok = $true
    count = @($results).Count
    results = $results
} | ConvertTo-Json -Depth 10
