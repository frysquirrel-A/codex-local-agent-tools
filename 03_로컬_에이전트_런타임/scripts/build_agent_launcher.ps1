[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$srcPath = Join-Path $packageRoot "src\\CodexLocalAgentLauncher.cs"
$guiSrcPath = Join-Path $packageRoot "src\\CodexLocalAgentLauncherGui.cs"
$binDir = Join-Path $packageRoot "bin"
$outPath = Join-Path $binDir "CodexLocalAgentLauncher.exe"
$guiOutPath = Join-Path $binDir "CodexLocalAgentLauncherGui.exe"
$cscCandidates = @(
    "C:\\Windows\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe",
    "C:\\Windows\\Microsoft.NET\\Framework\\v4.0.30319\\csc.exe"
)

$cscPath = $cscCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $cscPath) {
    throw "csc.exe was not found."
}

if (-not (Test-Path -LiteralPath $srcPath)) {
    throw "Launcher source was not found: $srcPath"
}
if (-not (Test-Path -LiteralPath $guiSrcPath)) {
    throw "GUI launcher source was not found: $guiSrcPath"
}

New-Item -ItemType Directory -Force -Path $binDir | Out-Null

& $cscPath /nologo /target:exe /out:$outPath $srcPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $outPath)) {
    throw "Launcher build failed."
}

& $cscPath /nologo /target:winexe /out:$guiOutPath /reference:System.Windows.Forms.dll /reference:System.Drawing.dll $guiSrcPath
if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $guiOutPath)) {
    throw "GUI launcher build failed."
}

[ordered]@{
    ok = $true
    compiler = $cscPath
    consoleOutput = $outPath
    guiOutput = $guiOutPath
} | ConvertTo-Json -Depth 4
