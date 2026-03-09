$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$stateDir = Join-Path $packageRoot "state"
$pidFile = Join-Path $stateDir "gmail_command_channel.pid"

if (Test-Path -LiteralPath $pidFile) {
    $pidValue = (Get-Content -LiteralPath $pidFile -Raw -Encoding ASCII).Trim()
    if ($pidValue -match '^\d+$') {
        Stop-Process -Id ([int]$pidValue) -Force -ErrorAction SilentlyContinue
    }
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$existing = Get-CimInstance Win32_Process |
    Where-Object {
        $_.Name -eq "python.exe" -and
        $_.CommandLine -like "*gmail_command_channel.py*"
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
} | ConvertTo-Json -Depth 4
