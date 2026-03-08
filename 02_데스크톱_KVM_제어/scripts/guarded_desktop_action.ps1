param(
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Args
)

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$policyPath = Join-Path $packageRoot "config\\action_policy.json"
$approvalScript = Join-Path $scriptRoot "request_approval.ps1"
$coreScript = Join-Path $scriptRoot "desktop_control.py"
$logDir = Join-Path $packageRoot "logs"
$logPath = Join-Path $logDir "activity.jsonl"
$taskId = [guid]::NewGuid().ToString()

if (-not $Args -or $Args.Count -eq 0) {
    throw "No desktop action was provided."
}

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$policy = Get-Content -LiteralPath $policyPath -Raw -Encoding UTF8 | ConvertFrom-Json
$action = $Args[0]
$rule = $policy.actions.$action
if (-not $rule) {
    $rule = [pscustomobject]@{
        level = $policy.defaultLevel
        requiresApproval = $true
    }
}

$approved = $true
if ($rule.requiresApproval) {
    $argSummary = ($Args -join " ")
    $message = "Codex desktop action`n`nAction: $action`nLevel: $($rule.level)`nArgs: $argSummary`n`nAllow this action?"
    & $approvalScript -Title "Codex Desktop Approval" -Message $message -Level $rule.level
    if ($LASTEXITCODE -ne 0) {
        $approved = $false
    }
}

$timestamp = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
function Write-GuardLog {
    param(
        [string]$Phase,
        [bool]$Approved
    )

    $entry = [ordered]@{
        timestamp = $timestamp
        taskId = $taskId
        phase = $Phase
        action = $action
        level = $rule.level
        approved = $Approved
        args = $Args
    } | ConvertTo-Json -Compress

    Add-Content -LiteralPath $logPath -Value $entry -Encoding UTF8
}

if (-not $approved) {
    Write-GuardLog -Phase "denied" -Approved $false
    Write-Output '{"ok":false,"reason":"User denied approval."}'
    exit 1
}

Write-GuardLog -Phase "approved" -Approved $true
python $coreScript @Args
