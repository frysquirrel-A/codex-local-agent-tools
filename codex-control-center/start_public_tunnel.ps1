param(
    [string]$Target = "127.0.0.1:8787",
    [int]$WaitSeconds = 15
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $projectRoot "start_public_tunnel.py"

if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "Tunnel script not found: $scriptPath"
}

python $scriptPath --target $Target --wait-seconds $WaitSeconds
