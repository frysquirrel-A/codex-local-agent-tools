param(
    [int]$Port = 8787,
    [switch]$NoBrowser
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$serverPath = Join-Path $projectRoot "src\control_center_server.py"

if (-not (Test-Path -LiteralPath $serverPath)) {
    throw "Server script not found: $serverPath"
}

$process = Start-Process -FilePath "python" `
    -ArgumentList @($serverPath, "--port", $Port) `
    -WorkingDirectory $projectRoot `
    -PassThru

Start-Sleep -Seconds 2

if (-not $NoBrowser) {
    Start-Process "http://127.0.0.1:$Port"
}

[pscustomobject]@{
    ok = $true
    pid = $process.Id
    port = $Port
    url = "http://127.0.0.1:$Port"
    projectRoot = $projectRoot
} | ConvertTo-Json -Depth 4
