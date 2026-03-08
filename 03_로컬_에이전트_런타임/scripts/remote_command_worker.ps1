[CmdletBinding()]
param(
    [int]$PollSeconds = 60
)

$ErrorActionPreference = "Continue"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$checkScript = Join-Path $scriptRoot "check_remote_commands.ps1"
$summarizeScript = Join-Path $scriptRoot "summarize_remote_command_inbox.ps1"
$executeScript = Join-Path $scriptRoot "execute_remote_command_inbox.ps1"
$stateDir = Join-Path $packageRoot "state"
$heartbeatPath = Join-Path $stateDir "remote_command_worker_heartbeat.json"

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
}

while ($true) {
    try {
        & $checkScript -ShowPopup | Out-Null
        & $summarizeScript -Status pending | Out-Null
        & $executeScript | Out-Null
        [pscustomobject]@{
            timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            pollSeconds = $PollSeconds
            ok = $true
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $heartbeatPath -Encoding UTF8
    }
    catch {
        [pscustomobject]@{
            timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
            pollSeconds = $PollSeconds
            ok = $false
            error = $_.Exception.Message
        } | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath $heartbeatPath -Encoding UTF8
    }

    Start-Sleep -Seconds $PollSeconds
}
