[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("status", "route", "new-chat", "consult", "watch-start", "watch-stop")]
    [string]$Mode,
    [string]$TaskText,
    [ValidateSet("gemini", "chatgpt")]
    [string[]]$Provider,
    [string]$Prompt,
    [string]$GeminiPrompt,
    [string]$ChatGPTPrompt,
    [switch]$Send,
    [switch]$ForceNewChat,
    [switch]$KeepCurrentChat,
    [double]$IntervalSeconds = 0.1
)

$ErrorActionPreference = "Stop"
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$toolRoot = Split-Path -Parent $packageRoot
$browserRoot = Get-ChildItem -LiteralPath $toolRoot -Directory | Where-Object { $_.Name -like "01_*" } | Select-Object -First 1 -ExpandProperty FullName
if (-not $browserRoot) {
    throw "Browser tool directory was not found under $toolRoot"
}
$bridgeStart = Join-Path $browserRoot "start_live_bridge_server.ps1"
$bridgeWrapper = Join-Path $browserRoot "send_live_page_command.ps1"
$taskRunner = Join-Path $scriptRoot "invoke_local_agent_task.ps1"
$routerScript = Join-Path $scriptRoot "select_collaboration_route.ps1"
$watchStart = Join-Path $scriptRoot "start_screen_watch.ps1"
$watchStop = Join-Path $scriptRoot "stop_screen_watch.ps1"
$watchPidPath = Join-Path $packageRoot "screen_watch.pid"
$watchMetaPath = Join-Path $packageRoot "latest\\screen_latest.json"

function Convert-RawJson {
    param([object]$Raw)
    return (($Raw | Out-String).Trim() | ConvertFrom-Json)
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

function Get-BridgeStatus {
    return Invoke-RestMethod -Uri "http://127.0.0.1:8765/status" -Method Get -TimeoutSec 2
}

function Ensure-BridgeServer {
    if (Test-BridgeReady) {
        return
    }

    & $bridgeStart | Out-Null
    Start-Sleep -Seconds 2
    if (-not (Test-BridgeReady)) {
        throw "Browser bridge server did not become ready."
    }
}

function Get-ProviderClientId {
    param([string]$Name)

    $urlHint = Get-ProviderUrlHint -Name $Name
    $status = Get-BridgeStatus
    $matched = @($status.clients | Where-Object { [string]$_.url -like "*$urlHint*" })
    if (-not $matched -or $matched.Count -eq 0) {
        throw "No bridge client matched provider '$Name'."
    }

    $active = @($matched | Where-Object { $_.active })
    $pool = if ($active.Count -gt 0) { $active } else { $matched }
    return ($pool | Sort-Object timestamp -Descending | Select-Object -First 1).clientId
}

function Invoke-BridgeJson {
    param([string[]]$Arguments)
    $raw = & $bridgeWrapper @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        throw "Bridge command failed: $($Arguments -join ' ')"
    }
    return $raw | ConvertFrom-Json
}

function Send-BridgeCommand {
    param(
        [string]$ClientId,
        [hashtable]$Command
    )

    $payload = @{
        clientId = $ClientId
        command = $Command
    } | ConvertTo-Json -Depth 6

    return Invoke-RestMethod -Uri "http://127.0.0.1:8765/command" -Method Post -ContentType "application/json" -Body $payload -TimeoutSec 8
}

function Get-RouteDecision {
    param([string]$Text)
    $raw = & $routerScript -TaskText $Text
    return Convert-RawJson -Raw $raw
}

function Get-ProviderUrlHint {
    param([string]$Name)
    if ($Name -eq "gemini") {
        return "gemini.google.com"
    }
    return "chatgpt.com"
}

function Open-ProviderNewChat {
    param([string]$Name)

    Ensure-BridgeServer
    $urlHint = Get-ProviderUrlHint -Name $Name
    $clientId = Get-ProviderClientId -Name $Name
    $targetUrl = if ($Name -eq "gemini") { "https://gemini.google.com/app?hl=ko" } else { "https://chatgpt.com/" }

    try {
        $accepted = Send-BridgeCommand -ClientId $clientId -Command @{
            id = [guid]::NewGuid().ToString()
            action = "navigate"
            url = $targetUrl
        }
        if ($accepted.ok) {
            return [ordered]@{
                ok = $true
                provider = $Name
                matchedText = "navigate"
                targetUrl = $targetUrl
                clientId = $clientId
            }
        }
    }
    catch {
    }

    $koreanNewChat = ([string][char]0xC0C8) + [char]0x20 + [char]0xCC44 + [char]0xD305
    foreach ($label in @($koreanNewChat, "New chat")) {
        try {
            $result = Invoke-BridgeJson -Arguments @("click-text", "--text", $label, "--contains", "--url-hint", $urlHint, "--timeout", "6", "--client-id", $clientId)
            if ($result.ok) {
                return [ordered]@{
                    ok = $true
                    provider = $Name
                    matchedText = $result.text
                }
            }
        }
        catch {
        }
    }

    throw "Failed to open a new chat for provider '$Name'."
}

function Get-PromptForProvider {
    param(
        [string]$Name,
        [string]$Task,
        [string]$SharedPrompt,
        [string]$GeminiSpecificPrompt,
        [string]$ChatGPTSpecificPrompt
    )

    if ($Name -eq "gemini" -and -not [string]::IsNullOrWhiteSpace($GeminiSpecificPrompt)) {
        return $GeminiSpecificPrompt
    }

    if ($Name -eq "chatgpt" -and -not [string]::IsNullOrWhiteSpace($ChatGPTSpecificPrompt)) {
        return $ChatGPTSpecificPrompt
    }

    if (-not [string]::IsNullOrWhiteSpace($SharedPrompt)) {
        return $SharedPrompt
    }

    return $Task
}

function Invoke-ProviderPrompt {
    param(
        [string]$Name,
        [string]$PromptText,
        [bool]$DoSend
    )

    if ([string]::IsNullOrWhiteSpace($PromptText)) {
        throw "Prompt text is required for consult mode."
    }

    if ($DoSend) {
        $raw = & $taskRunner -Mode llm-prompt -Provider $Name -Prompt $PromptText -Send
    }
    else {
        $raw = & $taskRunner -Mode llm-prompt -Provider $Name -Prompt $PromptText
    }

    return Convert-RawJson -Raw $raw
}

function Wait-ForProviderReady {
    param(
        [string]$Name,
        [int]$TimeoutSeconds = 8
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        try {
            $raw = & $taskRunner -Mode llm-prompt -Provider $Name -ValidateOnly 2>$null
            if ($LASTEXITCODE -eq 0) {
                return Convert-RawJson -Raw $raw
            }
        }
        catch {
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Provider '$Name' did not become ready after opening a new chat."
}

function Get-ProvidersFromRoute {
    param([object]$Route)
    $providers = New-Object System.Collections.Generic.List[string]
    if ($Route.recommendations.gemini.use) {
        $providers.Add("gemini") | Out-Null
    }
    if ($Route.recommendations.chatgpt.use) {
        $providers.Add("chatgpt") | Out-Null
    }
    return @($providers)
}

switch ($Mode) {
    "status" {
        $bridgeOk = Test-BridgeReady
        $bridgeStatus = $null
        if ($bridgeOk) {
            $bridgeStatus = Get-BridgeStatus
        }

        $watchInfo = [ordered]@{
            running = Test-Path -LiteralPath $watchPidPath
            pidPath = $watchPidPath
            latestMetaPath = $watchMetaPath
            latestMeta = $null
        }
        if (Test-Path -LiteralPath $watchMetaPath) {
            $watchInfo.latestMeta = Get-Content -LiteralPath $watchMetaPath -Raw -Encoding UTF8 | ConvertFrom-Json
        }

        [ordered]@{
            ok = $true
            mode = "status"
            bridge = [ordered]@{
                ready = $bridgeOk
                status = $bridgeStatus
            }
            screenWatch = $watchInfo
        } | ConvertTo-Json -Depth 8
        break
    }
    "route" {
        if ([string]::IsNullOrWhiteSpace($TaskText)) {
            throw "TaskText is required for route mode."
        }
        (Get-RouteDecision -Text $TaskText) | ConvertTo-Json -Depth 8
        break
    }
    "new-chat" {
        if (-not $Provider -or $Provider.Count -eq 0) {
            throw "Provider is required for new-chat mode."
        }

        $results = @()
        foreach ($name in $Provider) {
            try {
                $results += Open-ProviderNewChat -Name $name
            }
            catch {
                $results += [ordered]@{
                    ok = $false
                    provider = $name
                    reason = $_.Exception.Message
                }
            }
        }

        [ordered]@{
            ok = $true
            mode = "new-chat"
            results = $results
        } | ConvertTo-Json -Depth 6
        break
    }
    "consult" {
        if ([string]::IsNullOrWhiteSpace($TaskText)) {
            throw "TaskText is required for consult mode."
        }

        $route = Get-RouteDecision -Text $TaskText
        $targetProviders = if ($Provider -and $Provider.Count -gt 0) { @($Provider) } else { Get-ProvidersFromRoute -Route $route }

        if (-not $targetProviders -or $targetProviders.Count -eq 0) {
            [ordered]@{
                ok = $true
                mode = "consult"
                route = $route
                results = @()
            } | ConvertTo-Json -Depth 8
            break
        }

        $results = @()
        foreach ($name in $targetProviders) {
            try {
                $recommendation = $route.recommendations.$name
                $threadTarget = if ($ForceNewChat) { "new" } elseif ($KeepCurrentChat) { "existing" } else { [string]$recommendation.threadTarget }
                $newChatResult = $null

                if ($threadTarget -eq "new") {
                    try {
                        $newChatResult = Open-ProviderNewChat -Name $name
                        $null = Wait-ForProviderReady -Name $name
                    }
                    catch {
                        $newChatResult = [ordered]@{
                            ok = $false
                            provider = $name
                            reason = $_.Exception.Message
                            fallback = "existing"
                        }
                        $threadTarget = "existing"
                    }
                }

                $promptText = Get-PromptForProvider -Name $name -Task $TaskText -SharedPrompt $Prompt -GeminiSpecificPrompt $GeminiPrompt -ChatGPTSpecificPrompt $ChatGPTPrompt
                $attempt = 0
                while ($true) {
                    try {
                        $promptResult = Invoke-ProviderPrompt -Name $name -PromptText $promptText -DoSend:$Send
                        break
                    }
                    catch {
                        if ($attempt -ge 1) {
                            throw
                        }
                        $attempt++
                        Start-Sleep -Seconds 5
                    }
                }

                $results += [ordered]@{
                    ok = $true
                    provider = $name
                    threadTarget = $threadTarget
                    model = if ($name -eq "gemini") { $recommendation.model } else { $null }
                    modeRecommendation = if ($name -eq "chatgpt") { $recommendation.mode } else { $null }
                    newChat = $newChatResult
                    promptPreview = if ($promptText.Length -gt 120) { $promptText.Substring(0, 120) } else { $promptText }
                    response = $promptResult
                }
            }
            catch {
                $results += [ordered]@{
                    ok = $false
                    provider = $name
                    reason = $_.Exception.Message
                }
            }
        }

        [ordered]@{
            ok = $true
            mode = "consult"
            route = $route
            results = $results
        } | ConvertTo-Json -Depth 8
        break
    }
    "watch-start" {
        $raw = & $watchStart -IntervalSeconds $IntervalSeconds
        (Convert-RawJson -Raw $raw) | ConvertTo-Json -Depth 6
        break
    }
    "watch-stop" {
        $raw = & $watchStop
        (Convert-RawJson -Raw $raw) | ConvertTo-Json -Depth 6
        break
    }
}
