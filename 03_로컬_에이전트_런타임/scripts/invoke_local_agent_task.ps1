[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("llm-prompt", "browser-command", "desktop-command", "screen-capture", "screen-watch-start", "screen-watch-stop", "spend-approval", "spend-approve")]
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
$toolRoot = Split-Path -Parent $packageRoot
$browserRoot = Join-Path $toolRoot "01_브라우저_자동화"
$desktopRoot = Join-Path $toolRoot "02_데스크톱_KVM_제어"
$policyPath = Join-Path $packageRoot "config\\agent_policy.json"
$bridgeStart = Join-Path $browserRoot "start_live_bridge_server.ps1"
$bridgeWrapper = Join-Path $browserRoot "send_live_page_command.ps1"
$llmHelper = Join-Path $scriptRoot "send_web_llm_prompt.ps1"
$desktopGuard = Join-Path $desktopRoot "scripts\\guarded_desktop_action.ps1"
$screenCapture = Join-Path $desktopRoot "scripts\\capture_screen.ps1"
$screenWatchStart = Join-Path $scriptRoot "start_screen_watch.ps1"
$screenWatchStop = Join-Path $scriptRoot "stop_screen_watch.ps1"
$spendReportBuilder = Join-Path $scriptRoot "build_spend_approval_report.ps1"
$spendReportPrinter = Join-Path $scriptRoot "print_spend_approval_report.ps1"
$spendQueuePath = Join-Path $packageRoot "data\\spend_requests.json"
$logDir = Join-Path $packageRoot "logs"
$logPath = Join-Path $logDir "tasks.jsonl"
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
            $result = Invoke-JsonCommand -Executable $desktopGuard -Arguments $DesktopArgs
        }
        "screen-capture" {
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
