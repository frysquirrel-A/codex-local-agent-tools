$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$stateDir = Join-Path $packageRoot "state"
$pidFile = Join-Path $stateDir "local_chat_relay.pid"
$server = Join-Path $scriptRoot "local_chat_relay.py"
$python = (Get-Command python -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
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

if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$attempt = 0
do {
    $listener = Get-NetTCPConnection -LocalPort 8767 -State Listen -ErrorAction SilentlyContinue
    if (-not $listener) {
        break
    }
    Start-Sleep -Milliseconds 200
    $attempt++
} while ($attempt -lt 20)

$process = Start-Process -FilePath $python -ArgumentList @(
    $server
) -WorkingDirectory $scriptRoot -WindowStyle Hidden -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII

[pscustomobject]@{
    ok = $true
    pid = $process.Id
    pidPath = $pidFile
    port = 8767
} | ConvertTo-Json -Depth 4
