$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$stateDir = Join-Path $packageRoot "state"
$pidFile = Join-Path $stateDir "gmail_command_channel.pid"
$worker = Join-Path $scriptRoot "gmail_command_channel.py"
$python = (Get-Command python -ErrorAction Stop).Source

if (-not (Test-Path -LiteralPath $stateDir)) {
    New-Item -ItemType Directory -Force -Path $stateDir | Out-Null
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

if (Test-Path -LiteralPath $pidFile) {
    Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
}

$process = Start-Process -FilePath $python -ArgumentList @(
    $worker,
    "serve"
) -WorkingDirectory $scriptRoot -WindowStyle Hidden -PassThru

Set-Content -LiteralPath $pidFile -Value $process.Id -Encoding ASCII

[pscustomobject]@{
    ok = $true
    pid = $process.Id
    pidPath = $pidFile
} | ConvertTo-Json -Depth 4
