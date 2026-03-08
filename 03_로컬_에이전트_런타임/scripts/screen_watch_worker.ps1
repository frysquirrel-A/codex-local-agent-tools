[CmdletBinding()]
param(
    [double]$IntervalSeconds = 0.1,
    [Parameter(Mandatory = $true)]
    [string]$OutPath,
    [Parameter(Mandatory = $true)]
    [string]$MetaPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$toolRoot = Split-Path -Parent $packageRoot
$captureScript = Join-Path $toolRoot "02_데스크톱_KVM_제어\\scripts\\capture_screen.ps1"
$sleepMs = [Math]::Max(50, [int][Math]::Round($IntervalSeconds * 1000))

while ($true) {
    $resolved = & $captureScript -OutPath $OutPath
    $payload = [ordered]@{
        timestamp = (Get-Date).ToString("yyyy-MM-dd HH:mm:ss")
        path = ($resolved | Select-Object -Last 1)
        intervalSeconds = $IntervalSeconds
        sleepMilliseconds = $sleepMs
    }
    Set-Content -LiteralPath $MetaPath -Value ($payload | ConvertTo-Json -Compress) -Encoding UTF8
    Start-Sleep -Milliseconds $sleepMs
}
