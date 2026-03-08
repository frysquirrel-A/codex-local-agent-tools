[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("gemini", "chatgpt")]
    [string]$Provider,
    [string]$Prompt,
    [switch]$Send,
    [string]$WaitForText,
    [double]$Timeout = 30,
    [switch]$ValidateOnly
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$toolRoot = Split-Path -Parent $packageRoot
$browserRoot = Join-Path $toolRoot "01_브라우저_자동화"
$profilePath = Join-Path $packageRoot "config\\web_llm_profiles.json"
$bridgeWrapper = Join-Path $browserRoot "send_live_page_command.ps1"
$logDir = Join-Path $packageRoot "logs"
$logPath = Join-Path $logDir "tasks.jsonl"
$taskId = [guid]::NewGuid().ToString()

if (-not (Test-Path -LiteralPath $logDir)) {
    New-Item -ItemType Directory -Path $logDir | Out-Null
}

$profiles = Get-Content -LiteralPath $profilePath -Raw -Encoding UTF8 | ConvertFrom-Json
$providerProfile = $profiles.providers.$Provider
if (-not $providerProfile) {
    throw "Provider profile not found: $Provider"
}

function Resolve-ProviderClient {
    $status = Invoke-RestMethod -Uri "http://127.0.0.1:8765/status" -Method Get -TimeoutSec 3
    $matched = @()
    foreach ($client in $status.clients) {
        foreach ($hint in $providerProfile.urlHints) {
            if ([string]$client.url -like "*$hint*") {
                $matched += $client
                break
            }
        }
    }

    if (-not $matched -or $matched.Count -eq 0) {
        throw "No connected bridge client matched provider '$Provider'."
    }

    $pool = @(
        $matched |
        Sort-Object @{ Expression = { if ($_.active) { 0 } else { 1 } } }, @{ Expression = { if ($_.focused) { 0 } else { 1 } } }, @{ Expression = { -1 * [double]$_.timestamp } }
    )

    foreach ($candidate in $pool) {
        if (Test-BridgeClientResponsive -ClientId ([string]$candidate.clientId)) {
            return $candidate
        }
    }

    $candidateList = @($pool | ForEach-Object { [string]$_.url })
    throw "No responsive bridge client matched provider '$Provider'. Candidates: $($candidateList -join ', ')"
}

function Test-BridgeClientResponsive {
    param([string]$ClientId)

    try {
        $raw = & $bridgeWrapper "ping" "--client-id" $ClientId "--timeout" "2" 2>$null
        if ($LASTEXITCODE -ne 0) {
            return $false
        }

        $payload = $raw | ConvertFrom-Json
        return [bool]$payload.ok
    }
    catch {
        return $false
    }
}

function Write-AgentLog {
    param(
        [string]$Phase,
        [hashtable]$Payload
    )

    $entry = [ordered]@{
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        taskId = $taskId
        provider = $Provider
        phase = $Phase
        send = [bool]$Send
        validateOnly = [bool]$ValidateOnly
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

function Invoke-BridgeJson {
    param(
        [string[]]$Arguments,
        [string]$ClientId
    )

    $fullArgs = @($Arguments)
    if ($ClientId) {
        $fullArgs += @("--client-id", $ClientId)
    }

    $raw = & $bridgeWrapper @fullArgs
    if ($LASTEXITCODE -ne 0) {
        throw "Bridge command failed: $($fullArgs -join ' ')"
    }
    return $raw | ConvertFrom-Json
}

$client = Resolve-ProviderClient
$clientId = [string]$client.clientId
$url = [string]$client.url
$matchedUrl = $true
$baseResult = [ordered]@{
    ok = $true
    provider = $Provider
    currentUrl = $url
    matchedUrl = $matchedUrl
    visibleInputs = $null
    visibleClickables = $null
}

if ($ValidateOnly) {
    $ping = Invoke-BridgeJson -Arguments @("ping") -ClientId $clientId
    $summary = Invoke-BridgeJson -Arguments @("dom-summary") -ClientId $clientId
    $baseResult.visibleInputs = @($summary.summary.inputs).Count
    $baseResult.visibleClickables = @($summary.summary.clickable).Count
    $baseResult.validateOnly = $true
    $baseResult.summary = $summary.summary
    Write-AgentLog -Phase "validated" -Payload @{
        matchedUrl = $matchedUrl
        currentUrl = $url
        clientId = $clientId
        visibleInputs = @($summary.summary.inputs).Count
    }
    $baseResult | ConvertTo-Json -Depth 6
    exit 0
}

if ([string]::IsNullOrWhiteSpace($Prompt)) {
    throw "Prompt is required unless -ValidateOnly is used."
}

if (-not $matchedUrl) {
    throw "Current bridge page does not match provider '$Provider'. Current URL: $url"
}

if ($Send) {
    $promptSendResult = $null
    $selectedInput = $null
    $sendErrors = @()
    foreach ($selector in $providerProfile.inputSelectors) {
        try {
            $arguments = @("prompt-send", "--selector", $selector, "--text", $Prompt, "--timeout", [string]$Timeout)
            foreach ($sendSelector in @($providerProfile.sendSelectors)) {
                $arguments += @("--send-selector", [string]$sendSelector)
            }
            $promptSendResult = Invoke-BridgeJson -Arguments $arguments -ClientId $clientId
            if ($promptSendResult.ok) {
                $selectedInput = $selector
                break
            }
        }
        catch {
            $sendErrors += $_.Exception.Message
        }
    }

    if (-not $selectedInput) {
        Write-AgentLog -Phase "failed" -Payload @{
            reason = "No provider prompt-send selector matched."
            errors = $sendErrors
        }
        throw "No provider prompt-send selector matched for '$Provider'."
    }

    $baseResult.inputSelector = $selectedInput
    $baseResult.sendSelector = $promptSendResult.sendSelector
    $baseResult.sendResult = $promptSendResult

    if ($WaitForText) {
        $waitResult = Invoke-BridgeJson -Arguments @("wait-text", "--selector", "main", "--text", $WaitForText, "--contains", "--timeout", [string]$Timeout) -ClientId $clientId
        $baseResult.waitResult = $waitResult
    }
}
else {
    $setResult = $null
    $selectedInput = $null
    $setErrors = @()
    foreach ($selector in $providerProfile.inputSelectors) {
        try {
            $setResult = Invoke-BridgeJson -Arguments @("set-text", "--selector", $selector, "--text", $Prompt, "--timeout", [string]$Timeout) -ClientId $clientId
            if ($setResult.ok) {
                $selectedInput = $selector
                break
            }
        }
        catch {
            $setErrors += $_.Exception.Message
        }
    }

    if (-not $selectedInput) {
        Write-AgentLog -Phase "failed" -Payload @{
            reason = "No provider input selector matched."
            errors = $setErrors
        }
        throw "No provider input selector matched for '$Provider'."
    }

    $baseResult.inputSelector = $selectedInput
    $baseResult.setText = $setResult
}

Write-AgentLog -Phase "completed" -Payload @{
    matchedUrl = $matchedUrl
    currentUrl = $url
    inputSelector = $selectedInput
    send = [bool]$Send
}

$baseResult | ConvertTo-Json -Depth 6
