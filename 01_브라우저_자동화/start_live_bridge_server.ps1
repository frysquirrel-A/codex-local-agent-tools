$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$server = Join-Path $scriptRoot "live_bridge_server.py"
$pidFile = Join-Path $scriptRoot "live_bridge_server.pid"

$process = Start-Process -FilePath $python -ArgumentList @(
    $server
) -WorkingDirectory $scriptRoot -WindowStyle Hidden -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII
