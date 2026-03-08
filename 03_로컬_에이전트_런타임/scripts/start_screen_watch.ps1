[CmdletBinding()]
param(
    [double]$IntervalSeconds = 0.1,
    [string]$OutPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$pidPath = Join-Path $packageRoot "screen_watch.pid"
$latestDir = Join-Path $packageRoot "latest"
$worker = Join-Path $scriptRoot "screen_watch_worker.ps1"

if (-not $OutPath) {
    $OutPath = Join-Path $latestDir "screen_latest.png"
}

$metaPath = Join-Path $latestDir "screen_latest.json"

if (-not (Test-Path -LiteralPath $latestDir)) {
    New-Item -ItemType Directory -Path $latestDir | Out-Null
}

if (Test-Path -LiteralPath $pidPath) {
    $existingPid = (Get-Content -LiteralPath $pidPath -Raw -Encoding ASCII).Trim()
    if ($existingPid -and (Get-Process -Id ([int]$existingPid) -ErrorAction SilentlyContinue)) {
        Write-Output ([ordered]@{
            ok = $true
            alreadyRunning = $true
            pid = [int]$existingPid
            outPath = $OutPath
            metaPath = $metaPath
            intervalSeconds = $IntervalSeconds
        } | ConvertTo-Json -Depth 4)
        exit 0
    }
}

$process = Start-Process -FilePath "powershell.exe" -ArgumentList @(
    "-NoProfile",
    "-ExecutionPolicy",
    "Bypass",
    "-File",
    $worker,
    "-IntervalSeconds",
    [string]$IntervalSeconds,
    "-OutPath",
    $OutPath,
    "-MetaPath",
    $metaPath
) -WindowStyle Hidden -PassThru

Set-Content -LiteralPath $pidPath -Value $process.Id -Encoding ASCII

Write-Output ([ordered]@{
    ok = $true
    alreadyRunning = $false
    pid = $process.Id
    intervalSeconds = $IntervalSeconds
    outPath = $OutPath
    metaPath = $metaPath
} | ConvertTo-Json -Depth 4)
