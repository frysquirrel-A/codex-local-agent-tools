$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $scriptRoot "live_bridge_server.pid"

if (Test-Path -LiteralPath $pidFile) {
    $bridgePid = Get-Content -LiteralPath $pidFile -Raw -Encoding ASCII
    if ($bridgePid) {
        Stop-Process -Id ([int]$bridgePid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}
