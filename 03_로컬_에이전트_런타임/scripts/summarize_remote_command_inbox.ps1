[CmdletBinding()]
param(
    [ValidateSet("all", "new", "pending", "processed")]
    [string]$Status = "pending",
    [switch]$NoWriteState
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$configDir = Join-Path $packageRoot "config"
$stateDir = Join-Path $packageRoot "state"
$queuePath = Join-Path $stateDir "remote_command_queue.json"
$outboxPath = Join-Path $stateDir "remote_command_inbox.json"
$agentPolicyPath = Join-Path $configDir "agent_policy.json"
$inboxPolicyPath = Join-Path $configDir "remote_command_inbox_policy.json"

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

function Test-KeywordHit {
    param(
        [string]$Text,
        [string[]]$Keywords
    )

    $hits = New-Object System.Collections.Generic.List[string]
    foreach ($keyword in $Keywords) {
        if ([string]::IsNullOrWhiteSpace($keyword)) {
            continue
        }

        if ($Text.IndexOf($keyword, [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            $hits.Add($keyword) | Out-Null
        }
    }

    return @($hits | Select-Object -Unique)
}

function Get-TargetMode {
    param(
        [string]$Target,
        [object]$Policy
    )

    if ([string]::IsNullOrWhiteSpace($Target)) {
        return $null
    }

    $trimmed = $Target.Trim().ToLowerInvariant()
    foreach ($property in $Policy.targetModeMap.PSObject.Properties) {
        if ($trimmed -eq [string]$property.Name.ToLowerInvariant()) {
            return [string]$property.Value
        }
    }

    return $null
}

function Get-KeywordMode {
    param(
        [string]$Text,
        [object]$Policy
    )

    foreach ($property in $Policy.keywordModes.PSObject.Properties) {
        $hits = Test-KeywordHit -Text $Text -Keywords @($property.Value)
        if ($hits.Count -gt 0) {
            return [pscustomobject]@{
                mode = [string]$property.Name
                hits = $hits
            }
        }
    }

    return $null
}

function Get-ModeApproval {
    param(
        [string]$Mode,
        [object]$AgentPolicy
    )

    if ($AgentPolicy.modes.PSObject.Properties.Name -contains $Mode) {
        return $AgentPolicy.modes.$Mode
    }

    return $null
}

function Get-ConsultProviders {
    param(
        [string]$Mode,
        [object]$Policy
    )

    if ($Policy.consultMap.PSObject.Properties.Name -contains $Mode) {
        return @($Policy.consultMap.$Mode)
    }

    return @($Policy.defaultConsultProviders)
}

if (-not (Test-Path -LiteralPath $queuePath)) {
    $empty = [ordered]@{
        ok = $true
        generatedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        source = $queuePath
        count = 0
        actionableCount = 0
        items = @()
    }

    if (-not $NoWriteState) {
        $empty | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outboxPath -Encoding UTF8
    }

    $empty | ConvertTo-Json -Depth 8
    exit 0
}

$agentPolicy = Read-JsonFile -Path $agentPolicyPath
$inboxPolicy = Read-JsonFile -Path $inboxPolicyPath
$queue = @(Get-Content -LiteralPath $queuePath -Raw -Encoding UTF8 | ConvertFrom-Json)

if ($Status -ne "all") {
    $queue = @($queue | Where-Object { [string]$_.status -eq $Status })
}

$items = @()
foreach ($item in $queue) {
    $title = Get-TextValue -Value $item.title
    $command = Get-TextValue -Value $item.command
    $notes = Get-TextValue -Value $item.notes
    $target = Get-TextValue -Value $item.target
    $joined = (@($title, $command, $notes, $target) -join " ").Trim()

    $financialHits = Test-KeywordHit -Text $joined -Keywords @($agentPolicy.keywordGroups.financialExecution)
    $spendHits = Test-KeywordHit -Text $joined -Keywords @($agentPolicy.keywordGroups.spendingApproval)
    $destructiveHits = Test-KeywordHit -Text $joined -Keywords @($agentPolicy.keywordGroups.destructive)
    $targetMode = Get-TargetMode -Target $target -Policy $inboxPolicy
    $keywordMode = if ($targetMode) { $null } else { Get-KeywordMode -Text $joined -Policy $inboxPolicy }
    $recommendedMode = if ($targetMode) { $targetMode } elseif ($keywordMode) { [string]$keywordMode.mode } else { [string]$inboxPolicy.defaultMode }

    $classification = "ready"
    $risk = "low"
    $requiresApproval = $false
    $requiresPrintedReport = $false
    $reason = $null
    $policyBucket = $null

    if ($financialHits.Count -gt 0) {
        $classification = "blocked"
        $risk = "blocked"
        $recommendedMode = "blocked"
        $requiresApproval = $true
        $policyBucket = "financialExecution"
        $reason = [string]$agentPolicy.blockedCategories.financialExecution.message
    }
    elseif ($spendHits.Count -gt 0) {
        $classification = "approval-needed"
        $risk = "approval"
        $recommendedMode = "spend-approval"
        $requiresApproval = $true
        $requiresPrintedReport = [bool]$agentPolicy.modes."spend-approval".requiresPrintedReport
        $policyBucket = "spendingApproval"
        $reason = [string]$agentPolicy.approvalCategories.spendingApproval.message
    }
    elseif ($destructiveHits.Count -gt 0) {
        $classification = "manual-review"
        $risk = "high"
        $recommendedMode = "manual-review"
        $requiresApproval = $true
        $policyBucket = "destructive"
        $reason = [string]$inboxPolicy.destructiveApprovalMessage
    }
    else {
        $modeApproval = Get-ModeApproval -Mode $recommendedMode -AgentPolicy $agentPolicy
        if ($modeApproval -and [bool]$modeApproval.requiresApproval) {
            $classification = "approval-needed"
            $risk = if ($recommendedMode -eq "desktop-command") { "medium" } else { "approval" }
            $requiresApproval = $true
            if ($modeApproval.PSObject.Properties.Name -contains "requiresPrintedReport") {
                $requiresPrintedReport = [bool]$modeApproval.requiresPrintedReport
            }
            $reason = "Mode '$recommendedMode' requires approval under the current agent policy."
        }
        elseif ($recommendedMode -eq "manual-review") {
            $classification = "manual-review"
            $risk = "medium"
            $reason = [string]$inboxPolicy.manualReviewMessage
        }
        elseif ($recommendedMode -eq "desktop-command") {
            $classification = "approval-needed"
            $risk = "medium"
            $requiresApproval = $true
            $reason = "Desktop control should stay approval-gated before KVM execution."
        }
    }

    $consultProviders = Get-ConsultProviders -Mode $recommendedMode -Policy $inboxPolicy
    $modeSource = if ($targetMode) { "target" } elseif ($keywordMode) { "keywords" } else { "default" }
    $matchedKeywords = @($financialHits + $spendHits + $destructiveHits)
    if ($keywordMode) {
        $matchedKeywords += @($keywordMode.hits)
    }
    $matchedKeywords = @($matchedKeywords | Select-Object -Unique)

    $recommendedAction = switch ($classification) {
        "blocked" { "Do not execute. Leave this command for manual handling only." }
        "approval-needed" {
            if ($recommendedMode -eq "spend-approval") {
                "Prepare the spend-approval report and wait for explicit chat approval before any paid action."
            }
            elseif ($recommendedMode -eq "desktop-command") {
                "Hold for approval, then execute through the desktop or KVM path with a screenshot check."
            }
            else {
                "Hold for approval before execution."
            }
        }
        "manual-review" { "Review the wording and scope first, then choose a safe execution path." }
        default {
            if ($recommendedMode -eq "browser-command") {
                "Can execute through the browser DOM path after a quick provider health check."
            }
            elseif ($recommendedMode -eq "llm-prompt") {
                "Can execute as an LLM prompt or report task."
            }
            else {
                "Ready for the mapped safe execution path."
            }
        }
    }

    $items += [ordered]@{
        number = [int]$item.number
        title = $title
        status = Get-TextValue -Value $item.status
        priority = if ([string]::IsNullOrWhiteSpace([string]$item.priority)) { "normal" } else { [string]$item.priority }
        target = $target
        command = $command
        notes = $notes
        url = Get-TextValue -Value $item.url
        requestedAt = Get-TextValue -Value $item.requestedAt
        matchedBy = Get-TextValue -Value $item.matchedBy
        mode = $recommendedMode
        modeSource = $modeSource
        classification = $classification
        risk = $risk
        requiresApproval = $requiresApproval
        requiresPrintedReport = $requiresPrintedReport
        consultProviders = @($consultProviders)
        policyBucket = $policyBucket
        matchedKeywords = $matchedKeywords
        reason = $reason
        recommendedAction = $recommendedAction
    }
}

$summary = [ordered]@{
    total = @($items).Count
    actionable = @($items | Where-Object { $_.classification -eq "ready" -and $_.status -in @("new", "pending") }).Count
    blocked = @($items | Where-Object { $_.classification -eq "blocked" }).Count
    approvalNeeded = @($items | Where-Object { $_.classification -eq "approval-needed" }).Count
    manualReview = @($items | Where-Object { $_.classification -eq "manual-review" }).Count
    byMode = [ordered]@{
        browser = @($items | Where-Object { $_.mode -eq "browser-command" }).Count
        desktop = @($items | Where-Object { $_.mode -eq "desktop-command" }).Count
        llm = @($items | Where-Object { $_.mode -eq "llm-prompt" }).Count
        spendApproval = @($items | Where-Object { $_.mode -eq "spend-approval" }).Count
        manualReview = @($items | Where-Object { $_.mode -eq "manual-review" }).Count
        blocked = @($items | Where-Object { $_.mode -eq "blocked" }).Count
    }
}

$result = [ordered]@{
    ok = $true
    generatedAt = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
    source = $queuePath
    sourceStatusFilter = $Status
    summary = $summary
    items = $items
}

if (-not $NoWriteState) {
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $outboxPath -Encoding UTF8
}

$result | ConvertTo-Json -Depth 8
