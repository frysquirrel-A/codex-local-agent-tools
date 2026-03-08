[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$TaskText
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$policyPath = Join-Path $packageRoot "config\\llm_collaboration_policy.json"

if (-not (Test-Path -LiteralPath $policyPath)) {
    throw "Collaboration policy was not found: $policyPath"
}

$policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$normalized = [string]$TaskText
$lowered = $normalized.ToLowerInvariant()

function Test-KeywordGroup {
    param(
        [string]$Text,
        [object[]]$Keywords
    )

    foreach ($keyword in $Keywords) {
        if ([string]::IsNullOrWhiteSpace([string]$keyword)) {
            continue
        }

        if ($Text -like ("*" + ([string]$keyword).ToLowerInvariant() + "*")) {
            return $true
        }
    }

    return $false
}

$flags = [ordered]@{
    highRisk = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.highRisk
    currentWeb = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.currentWeb
    googleWorkspace = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.googleWorkspace
    reporting = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.reporting
    codeReasoning = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.codeReasoning
    deterministicLocal = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.deterministicLocal
    deepPlanning = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.deepPlanning
    crossCheck = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.crossCheck
    continueThread = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.continueThread
    newThread = Test-KeywordGroup -Text $lowered -Keywords $policy.keywordSets.newThread
}

$route = "codexSolo"
$reasons = New-Object System.Collections.Generic.List[string]

if ($flags.highRisk -or $flags.crossCheck -or (($flags.currentWeb -or $flags.googleWorkspace) -and ($flags.reporting -or $flags.codeReasoning -or $flags.deepPlanning))) {
    $route = "consultBoth"
    $reasons.Add("This task needs both current web context and structured judgment.") | Out-Null
}
elseif ($flags.currentWeb -or $flags.googleWorkspace -or $flags.deepPlanning) {
    $route = "consultGemini"
    $reasons.Add("Web structure or staged planning is central, so Gemini is preferred.") | Out-Null
}
elseif ($flags.reporting -or $flags.codeReasoning) {
    $route = "consultChatGPT"
    $reasons.Add("Documentation or structured reasoning is central, so ChatGPT is preferred.") | Out-Null
}
elseif ($flags.deterministicLocal) {
    $route = "codexSolo"
    $reasons.Add("This is a deterministic local task that Codex can execute directly.") | Out-Null
}
else {
    $reasons.Add("Codex solo stays the default to avoid unnecessary external consultation.") | Out-Null
}

function Get-GeminiModel {
    param([hashtable]$Flags)
    if ($Flags.highRisk -or $Flags.deepPlanning -or $Flags.reporting) {
        return "Gemini 1.5 Pro"
    }
    return "Gemini 2.0 Flash"
}

function Get-ChatGPTMode {
    param([hashtable]$Flags)
    if ($Flags.highRisk -or $Flags.crossCheck -or ($Flags.deepPlanning -and $Flags.reporting)) {
        return "Extended Pro"
    }
    if ($Flags.codeReasoning -or $Flags.reporting -or $Flags.deepPlanning) {
        return "Pro"
    }
    return "Standard"
}

$geminiModel = Get-GeminiModel -Flags $flags
$chatgptMode = Get-ChatGPTMode -Flags $flags

function Get-ThreadTarget {
    param(
        [string]$Provider,
        [hashtable]$Flags
    )

    if ($Flags.newThread) {
        return [ordered]@{
            target = "new"
            reason = "The task text explicitly asks for a new or reset conversation."
        }
    }

    if ($Flags.continueThread) {
        return [ordered]@{
            target = "existing"
            reason = "The task text explicitly asks to continue the current context."
        }
    }

    if ($Provider -eq "gemini") {
        if ($Flags.currentWeb -or $Flags.googleWorkspace -or $Flags.codeReasoning) {
            return [ordered]@{
                target = "existing"
                reason = "Keeping the current browser or project-debugging context is more efficient."
            }
        }

        if ($Flags.deepPlanning -or $Flags.highRisk -or $Flags.crossCheck) {
            return [ordered]@{
                target = "new"
                reason = "A clean context is safer for new design work or cross-check review."
            }
        }
    }

    if ($Provider -eq "chatgpt") {
        if ($Flags.reporting -or $Flags.codeReasoning) {
            return [ordered]@{
                target = "existing"
                reason = "Continuing the same document or code explanation thread is more efficient."
            }
        }

        if ($Flags.highRisk -or $Flags.crossCheck -or $Flags.deepPlanning) {
            return [ordered]@{
                target = "new"
                reason = "A new chat reduces mixed-thread noise and gives a cleaner independent review."
            }
        }
    }

    return [ordered]@{
        target = "existing"
        reason = "No topic-reset signal was found, so keeping the existing context is the default."
    }
}

$geminiThread = Get-ThreadTarget -Provider "gemini" -Flags $flags
$chatgptThread = Get-ThreadTarget -Provider "chatgpt" -Flags $flags

$result = [ordered]@{
    ok = $true
    taskText = $TaskText
    route = $route
    routeLabel = $policy.routes.$route.label
    reasons = @($reasons)
    flags = $flags
    recommendations = [ordered]@{
        codex = [ordered]@{
            use = $true
            role = "Execution, file edits, browser DOM control, and KVM fallback"
        }
        gemini = [ordered]@{
            use = $route -in @("consultGemini", "consultBoth")
            model = $geminiModel
            threadTarget = $geminiThread.target
            threadReason = $geminiThread.reason
            role = "Current web structure, selectors, Google ecosystem, and staged planning"
            selectionHint = $policy.providerProfiles.gemini.selectionHint
        }
        chatgpt = [ordered]@{
            use = $route -in @("consultChatGPT", "consultBoth")
            mode = $chatgptMode
            threadTarget = $chatgptThread.target
            threadReason = $chatgptThread.reason
            role = "Documentation, explanations, and structured code reasoning"
            selectionHint = $policy.providerProfiles.chatgpt.selectionHint
        }
    }
}

$result | ConvertTo-Json -Depth 8
