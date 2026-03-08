[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("llm-prompt", "browser-command", "desktop-command", "desktop-policy", "desktop-mode-set", "screen-capture", "screen-watch-start", "screen-watch-stop", "chat-relay-start", "chat-relay-stop", "chat-relay-status", "keepalive-start", "keepalive-stop", "keepalive-status", "spend-approval", "spend-approve")]
    [string]$Mode,
    [string]$TaskText,
    [ValidateSet("gemini", "chatgpt")]
    [string]$Provider,
    [string]$Prompt,
    [switch]$Send,
    [string]$WaitForText,
    [switch]$ValidateOnly,
    [string]$BrowserAction,
    [string[]]$BrowserArgs,
    [string[]]$DesktopArgs,
    [ValidateSet("background", "foreground")]
    [string]$DesktopMode,
    [string]$DesktopModeReason,
    [double]$IntervalSeconds = 0.1,
    [string]$OutPath,
    [string]$SpendTitle,
    [string]$SpendSubject,
    [decimal]$EstimatedCostKRW,
    [string]$ExpectedBenefit,
    [string]$Reason,
    [string]$Recommendation = "승인 권장",
    [string]$Alternatives = "보류 또는 미도입",
    [string]$RequestId
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$packageGroupRoot = Split-Path -Parent $packageRoot
$toolRoot = Split-Path -Parent $packageGroupRoot
$featureRoot = Join-Path $toolRoot "01_공용_기능"
$browserRoot = Join-Path $featureRoot "브라우저_DOM_제어"
$desktopRoot = Join-Path $featureRoot "데스크톱_KVM_제어"
$policyPath = Join-Path $packageRoot "config\\agent_policy.json"
$bridgeStart = Join-Path $browserRoot "start_live_bridge_server.ps1"
$bridgeStop = Join-Path $browserRoot "stop_live_bridge_server.ps1"
$bridgeWrapper = Join-Path $browserRoot "send_live_page_command.ps1"
$llmHelper = Join-Path $scriptRoot "send_web_llm_prompt.ps1"
$desktopGuard = Join-Path $desktopRoot "scripts\\guarded_desktop_action.ps1"
$desktopServerStart = Join-Path $desktopRoot "scripts\\start_desktop_control_server.ps1"
$desktopServerStop = Join-Path $desktopRoot "scripts\\stop_desktop_control_server.ps1"
$screenCapture = Join-Path $desktopRoot "scripts\\capture_screen.ps1"
$screenWatchStart = Join-Path $scriptRoot "start_screen_watch.ps1"
$screenWatchStop = Join-Path $scriptRoot "stop_screen_watch.ps1"
$chatRelayStart = Join-Path $scriptRoot "start_local_chat_relay.ps1"
$chatRelayStop = Join-Path $scriptRoot "stop_local_chat_relay.ps1"
$spendReportBuilder = Join-Path $scriptRoot "build_spend_approval_report.ps1"
$spendReportPrinter = Join-Path $scriptRoot "print_spend_approval_report.ps1"
$spendQueuePath = Join-Path $packageRoot "data\\spend_requests.json"
$logDir = Join-Path $packageRoot "logs"
$logPath = Join-Path $logDir "tasks.jsonl"
$screenWatchPidPath = Join-Path $packageRoot "screen_watch.pid"
$screenWatchMetaPath = Join-Path $packageRoot "latest\\screen_latest.json"
$taskId = [guid]::NewGuid().ToString()

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json

function Write-AgentLog {
    param(
        [string]$Phase,
        [hashtable]$Payload
    )

    $entry = [ordered]@{
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        taskId = $taskId
        mode = $Mode
        phase = $Phase
    }

    foreach ($key in $Payload.Keys) {
        $entry[$key] = $Payload[$key]
    }

    $line = $entry | ConvertTo-Json -Compress
    for ($attempt = 1; $attempt -le 10; $attempt++) {
        try {
            Add-Content -LiteralPath $logPath -Value $line -Encoding UTF8
            return
        }
        catch {
            if ($attempt -eq 10) {
                throw
            }
            Start-Sleep -Milliseconds 120
        }
    }
}

function Test-BridgeReady {
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:8765/status" -Method Get -TimeoutSec 2
        return [bool]$status.ok
    }
    catch {
        return $false
    }
}

function Ensure-BridgeServer {
    if (Test-BridgeReady) {
        return
    }

    & $bridgeStart
    Start-Sleep -Seconds 2
    if (-not (Test-BridgeReady)) {
        throw "Browser bridge server did not become ready."
    }
}

function Test-DesktopServerReady {
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:8766/status" -Method Get -TimeoutSec 2
        return [bool]$status.ok
    }
    catch {
        return $false
    }
}

function Get-DesktopServerStatus {
    return Invoke-RestMethod -Uri "http://127.0.0.1:8766/status" -Method Get -TimeoutSec 2
}

function Ensure-DesktopServer {
    if (Test-DesktopServerReady) {
        return
    }

    & $desktopServerStart | Out-Null
    Start-Sleep -Milliseconds 350
    if (-not (Test-DesktopServerReady)) {
        throw "Desktop control server did not become ready."
    }
}

function Contains-AnyKeyword {
    param(
        [string]$Text,
        [object[]]$Keywords
    )

    foreach ($keyword in $Keywords) {
        if (-not [string]::IsNullOrWhiteSpace([string]$keyword) -and $Text -like "*$keyword*") {
            return $true
        }
    }

    return $false
}

function Test-ChatRelayReady {
    try {
        $status = Invoke-RestMethod -Uri "http://127.0.0.1:8767/status" -Method Get -TimeoutSec 2
        return [bool]$status.ok
    }
    catch {
        return $false
    }
}

function Get-ChatRelayStatus {
    return Invoke-RestMethod -Uri "http://127.0.0.1:8767/status" -Method Get -TimeoutSec 2
}

function Ensure-ChatRelay {
    if (Test-ChatRelayReady) {
        return
    }

    $raw = & $chatRelayStart
    if ($LASTEXITCODE -ne 0) {
        throw "Local chat relay did not start."
    }
    for ($attempt = 1; $attempt -le 12; $attempt++) {
        Start-Sleep -Milliseconds 250
        if (Test-ChatRelayReady) {
            return
        }
    }

    throw "Local chat relay did not become ready."
}

function Get-RiskDecision {
    $joined = @(
        $TaskText,
        $Prompt,
        $Provider,
        $BrowserAction,
        ($BrowserArgs -join " "),
        ($DesktopArgs -join " ")
    ) -join " "

    $result = [ordered]@{
        level = $policy.defaultRisk
        allow = $true
        reason = ""
    }

    if ($Mode -ne "llm-prompt" -and (Contains-AnyKeyword -Text $joined -Keywords $policy.keywordGroups.financialExecution)) {
        $result.level = "financialExecution"
        $result.allow = [bool]$policy.blockedCategories.financialExecution.allow
        $result.reason = [string]$policy.blockedCategories.financialExecution.message
        return $result
    }

    if ($Mode -eq "spend-approval") {
        $result.level = "spendingApproval"
        $result.allow = [bool]$policy.approvalCategories.spendingApproval.allow
        $result.reason = [string]$policy.approvalCategories.spendingApproval.message
        return $result
    }

    if ($Mode -ne "llm-prompt" -and (Contains-AnyKeyword -Text $joined -Keywords $policy.keywordGroups.spendingApproval)) {
        $result.level = "spendingApproval"
        $result.allow = $false
        $result.reason = "This looks like a paid action. Use spend-approval mode first."
        return $result
    }

    if ($Mode -eq "desktop-command" -or (Contains-AnyKeyword -Text $joined -Keywords $policy.keywordGroups.destructive)) {
        $result.level = "guarded"
        $result.allow = $true
        $result.reason = "Desktop or destructive-leaning task. Approval gate applies."
    }

    return $result
}

function Invoke-JsonCommand {
    param(
        [string]$Executable,
        [string[]]$Arguments
    )

    $raw = & $Executable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Command failed: $Executable $($Arguments -join ' ')"
    }
    return $raw | ConvertFrom-Json
}

function Convert-RawJson {
    param(
        [object]$Raw
    )

    return (($Raw | Out-String).Trim() | ConvertFrom-Json)
}

function Load-SpendQueue {
    if (-not (Test-Path -LiteralPath $spendQueuePath)) {
        $empty = [ordered]@{ requests = @() }
        New-Item -ItemType Directory -Force -Path (Split-Path -Parent $spendQueuePath) | Out-Null
        Set-Content -LiteralPath $spendQueuePath -Value ($empty | ConvertTo-Json -Depth 6) -Encoding UTF8
        return $empty
    }

    return (Get-Content -LiteralPath $spendQueuePath -Raw -Encoding UTF8 | ConvertFrom-Json)
}

function Save-SpendQueue {
    param([object]$Queue)
    New-Item -ItemType Directory -Force -Path (Split-Path -Parent $spendQueuePath) | Out-Null
    Set-Content -LiteralPath $spendQueuePath -Value ($Queue | ConvertTo-Json -Depth 8) -Encoding UTF8
}

function Get-ScreenWatchInfo {
    $info = [ordered]@{
        running = $false
        pidPath = $screenWatchPidPath
        pid = $null
        latestMetaPath = $screenWatchMetaPath
        latestMeta = $null
        latestPath = $null
        fresh = $false
        ageSeconds = $null
    }

    if (Test-Path -LiteralPath $screenWatchPidPath) {
        $pidValue = (Get-Content -LiteralPath $screenWatchPidPath -Raw -Encoding ASCII).Trim()
        if ($pidValue -match '^\d+$' -and (Get-Process -Id ([int]$pidValue) -ErrorAction SilentlyContinue)) {
            $info.running = $true
            $info.pid = [int]$pidValue
        }
    }

    if (Test-Path -LiteralPath $screenWatchMetaPath) {
        try {
            $meta = Get-Content -LiteralPath $screenWatchMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
            $info.latestMeta = $meta
            $info.latestPath = [string]$meta.path
            if ($meta.timestamp) {
                $age = ((Get-Date) - (Get-Date $meta.timestamp)).TotalSeconds
                $info.ageSeconds = [Math]::Round($age, 3)
                $freshLimit = [Math]::Max(2.0, ([double]$meta.intervalSeconds * 3.0))
                if ($age -le $freshLimit -and $meta.path -and (Test-Path -LiteralPath ([string]$meta.path))) {
                    $info.fresh = $true
                }
            }
        }
        catch {
        }
    }

    return $info
}

$risk = Get-RiskDecision
Write-AgentLog -Phase "accepted" -Payload @{
    taskText = $TaskText
    risk = $risk.level
    allowed = $risk.allow
    reason = $risk.reason
}

if (-not $risk.allow) {
    $blocked = [ordered]@{
        ok = $false
        mode = $Mode
        taskId = $taskId
        risk = $risk.level
        reason = $risk.reason
    }
    Write-AgentLog -Phase "blocked" -Payload @{
        risk = $risk.level
        reason = $risk.reason
    }
    $blocked | ConvertTo-Json -Depth 5
    exit 1
}

try {
    $result = $null

    switch ($Mode) {
        "llm-prompt" {
            Ensure-BridgeServer
            if ($ValidateOnly) {
                $raw = & $llmHelper -Provider $Provider -ValidateOnly
            } else {
                if ($Send -and $WaitForText) {
                    $raw = & $llmHelper -Provider $Provider -Prompt $Prompt -Send -WaitForText $WaitForText
                } elseif ($Send) {
                    $raw = & $llmHelper -Provider $Provider -Prompt $Prompt -Send
                } else {
                    $raw = & $llmHelper -Provider $Provider -Prompt $Prompt
                }
            }
            $result = Convert-RawJson -Raw $raw
        }
        "browser-command" {
            if ([string]::IsNullOrWhiteSpace($BrowserAction)) {
                throw "BrowserAction is required for browser-command mode."
            }
            Ensure-BridgeServer
            $args = @($BrowserAction)
            if ($BrowserArgs) {
                $args += $BrowserArgs
            }
            $result = Invoke-JsonCommand -Executable $bridgeWrapper -Arguments $args
        }
        "desktop-command" {
            if (-not $DesktopArgs -or $DesktopArgs.Count -eq 0) {
                throw "DesktopArgs are required for desktop-command mode."
            }
            Ensure-DesktopServer
            $result = Invoke-JsonCommand -Executable $desktopGuard -Arguments $DesktopArgs
        }
        "desktop-policy" {
            Ensure-DesktopServer
            $result = Invoke-JsonCommand -Executable $desktopGuard -Arguments @("background-policy")
        }
        "desktop-mode-set" {
            if ([string]::IsNullOrWhiteSpace($DesktopMode)) {
                throw "DesktopMode is required for desktop-mode-set mode."
            }
            Ensure-DesktopServer
            $args = @("set-mode", "--mode", $DesktopMode, "--changed-by", "runtime")
            if (-not [string]::IsNullOrWhiteSpace($DesktopModeReason)) {
                $args += @("--reason", $DesktopModeReason)
            }
            $result = Invoke-JsonCommand -Executable $desktopGuard -Arguments $args
        }
        "screen-capture" {
            $watchInfo = Get-ScreenWatchInfo
            if (-not $OutPath -and $watchInfo.running -and $watchInfo.fresh -and $watchInfo.latestPath) {
                $result = [ordered]@{
                    ok = $true
                    mode = "screen-capture"
                    path = [string]$watchInfo.latestPath
                    source = "screen-watch"
                    ageSeconds = $watchInfo.ageSeconds
                }
            }
            else {
                $args = @()
                if ($OutPath) {
                    $args += @("-OutPath", $OutPath)
                }
                $raw = & $screenCapture @args
                $capturedPath = ($raw | Select-Object -Last 1)
                if (-not $capturedPath -or -not (Test-Path -LiteralPath $capturedPath)) {
                    throw "Screen capture failed."
                }
                $result = [ordered]@{
                    ok = $true
                    mode = "screen-capture"
                    path = $capturedPath
                    source = "direct"
                }
            }
        }
        "screen-watch-start" {
            if ($OutPath) {
                $raw = & $screenWatchStart -IntervalSeconds $IntervalSeconds -OutPath $OutPath
            } else {
                $raw = & $screenWatchStart -IntervalSeconds $IntervalSeconds
            }
            $result = Convert-RawJson -Raw $raw
        }
        "screen-watch-stop" {
            $raw = & $screenWatchStop
            $result = Convert-RawJson -Raw $raw
        }
        "chat-relay-start" {
            Ensure-ChatRelay
            $result = [ordered]@{
                ok = $true
                mode = "chat-relay-start"
                relay = (Get-ChatRelayStatus)
            }
        }
        "chat-relay-stop" {
            $raw = & $chatRelayStop
            $result = Convert-RawJson -Raw $raw
        }
        "chat-relay-status" {
            $relayReady = Test-ChatRelayReady
            $result = [ordered]@{
                ok = $true
                mode = "chat-relay-status"
                relay = [ordered]@{
                    ready = $relayReady
                    status = $(if ($relayReady) { Get-ChatRelayStatus } else { $null })
                }
            }
        }
        "keepalive-start" {
            Ensure-BridgeServer
            Ensure-DesktopServer
            Ensure-ChatRelay
            if ($OutPath) {
                $watchRaw = & $screenWatchStart -IntervalSeconds $IntervalSeconds -OutPath $OutPath
            }
            else {
                $watchRaw = & $screenWatchStart -IntervalSeconds $IntervalSeconds
            }

            $result = [ordered]@{
                ok = $true
                mode = "keepalive-start"
                bridge = [ordered]@{
                    ready = (Test-BridgeReady)
                }
                desktop = [ordered]@{
                    ready = (Test-DesktopServerReady)
                    status = (Get-DesktopServerStatus)
                }
                relay = [ordered]@{
                    ready = (Test-ChatRelayReady)
                    status = (Get-ChatRelayStatus)
                }
                screenWatch = (Convert-RawJson -Raw $watchRaw)
            }
        }
        "keepalive-stop" {
            $bridgeStopped = $false
            if (Test-Path -LiteralPath $bridgeStop) {
                & $bridgeStop
                $bridgeStopped = $true
            }
            $desktopRaw = & $desktopServerStop
            $relayRaw = & $chatRelayStop
            $watchRaw = & $screenWatchStop

            $result = [ordered]@{
                ok = $true
                mode = "keepalive-stop"
                bridge = [ordered]@{
                    stopRequested = $bridgeStopped
                    ready = (Test-BridgeReady)
                }
                desktop = (Convert-RawJson -Raw $desktopRaw)
                relay = (Convert-RawJson -Raw $relayRaw)
                screenWatch = (Convert-RawJson -Raw $watchRaw)
            }
        }
        "keepalive-status" {
            $desktopReady = Test-DesktopServerReady
            $relayReady = Test-ChatRelayReady
            $result = [ordered]@{
                ok = $true
                mode = "keepalive-status"
                bridge = [ordered]@{
                    ready = (Test-BridgeReady)
                }
                desktop = [ordered]@{
                    ready = $desktopReady
                    status = $(if ($desktopReady) { Get-DesktopServerStatus } else { $null })
                }
                relay = [ordered]@{
                    ready = $relayReady
                    status = $(if ($relayReady) { Get-ChatRelayStatus } else { $null })
                }
                screenWatch = (Get-ScreenWatchInfo)
            }
        }
        "spend-approval" {
            if ([string]::IsNullOrWhiteSpace($SpendTitle) -or [string]::IsNullOrWhiteSpace($SpendSubject) -or [string]::IsNullOrWhiteSpace($ExpectedBenefit) -or [string]::IsNullOrWhiteSpace($Reason)) {
                throw "SpendTitle, SpendSubject, ExpectedBenefit, and Reason are required for spend-approval mode."
            }

            $queue = Load-SpendQueue
            $requestRecord = [ordered]@{
                id = "SREQ-" + (Get-Date -Format "yyMMdd-HHmmss") + "-" + (Get-Random -Minimum 10 -Maximum 99)
                title = $SpendTitle
                spendSubject = $SpendSubject
                estimatedCostKRW = [double]$EstimatedCostKRW
                expectedBenefit = $ExpectedBenefit
                reason = $Reason
                recommendation = $Recommendation
                alternatives = $Alternatives
                status = "pending"
                requestedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                approvedAt = ""
            }

            $queue.requests = @($queue.requests) + $requestRecord
            Save-SpendQueue -Queue $queue

            $rawBuild = & $spendReportBuilder -QueuePath $spendQueuePath -HighlightRequestId $requestRecord.id
            $buildResult = Convert-RawJson -Raw $rawBuild

            $rawPrint = & $spendReportPrinter -PdfPath $buildResult.pdfPath
            $printResult = Convert-RawJson -Raw $rawPrint

            $result = [ordered]@{
                ok = $true
                mode = "spend-approval"
                requestId = $requestRecord.id
                status = "pending"
                report = $buildResult
                print = $printResult
                estimatedCostKRW = [double]$EstimatedCostKRW
                recommendation = $Recommendation
            }
        }
        "spend-approve" {
            if ([string]::IsNullOrWhiteSpace($RequestId)) {
                throw "RequestId is required for spend-approve mode."
            }

            $queue = Load-SpendQueue
            $updated = $false
            foreach ($item in $queue.requests) {
                if ($item.id -eq $RequestId) {
                    $item.status = "approved"
                    $item.approvedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
                    $updated = $true
                    break
                }
            }

            if (-not $updated) {
                throw "Spend request was not found: $RequestId"
            }

            Save-SpendQueue -Queue $queue
            $rawBuild = & $spendReportBuilder -QueuePath $spendQueuePath -HighlightRequestId $RequestId
            $buildResult = Convert-RawJson -Raw $rawBuild
            $rawPrint = & $spendReportPrinter -PdfPath $buildResult.pdfPath
            $printResult = Convert-RawJson -Raw $rawPrint

            $result = [ordered]@{
                ok = $true
                mode = "spend-approve"
                requestId = $RequestId
                status = "approved"
                report = $buildResult
                print = $printResult
            }
        }
        default {
            throw "Unsupported mode: $Mode"
        }
    }

    $envelope = [ordered]@{
        ok = if ($result.PSObject.Properties.Name -contains "ok") { [bool]$result.ok } else { $true }
        taskId = $taskId
        mode = $Mode
        risk = $risk.level
        result = $result
    }

    Write-AgentLog -Phase "completed" -Payload @{
        risk = $risk.level
        ok = $envelope.ok
    }

    $envelope | ConvertTo-Json -Depth 8
}
catch {
    Write-AgentLog -Phase "failed" -Payload @{
        risk = $risk.level
        ok = $false
        error = $_.Exception.Message
    }
    throw
}
