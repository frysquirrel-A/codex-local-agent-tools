param(
    [string]$BindHost = "127.0.0.1",
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
    -ArgumentList @($serverPath, "--host", $BindHost, "--port", $Port) `
    -WorkingDirectory $projectRoot `
    -PassThru

Start-Sleep -Seconds 2

if (-not $NoBrowser) {
    Start-Process "http://$BindHost`:$Port"
}

[pscustomobject]@{
    ok = $true
    pid = $process.Id
    host = $BindHost
    port = $Port
    url = "http://$BindHost`:$Port"
    projectRoot = $projectRoot
} | ConvertTo-Json -Depth 4
