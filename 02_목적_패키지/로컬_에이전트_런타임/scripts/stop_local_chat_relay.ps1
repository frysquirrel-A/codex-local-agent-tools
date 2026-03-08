$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$stateDir = Join-Path $packageRoot "state"
$pidFile = Join-Path $stateDir "local_chat_relay.pid"

if (Test-Path -LiteralPath $pidFile) {
    $relayPid = Get-Content -LiteralPath $pidFile -Raw -Encoding ASCII
    if ($relayPid) {
        Stop-Process -Id ([int]$relayPid) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*local_chat_relay.py*"
    }

foreach ($process in @($existing)) {
    try {
        Stop-Process -Id $process.ProcessId -Force -ErrorAction Stop
    }
    catch {
    }
}

[pscustomobject]@{
    ok = $true
    stopped = $true
    port = 8767
} | ConvertTo-Json -Depth 4
