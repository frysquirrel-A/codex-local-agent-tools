[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PdfPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$sumatraPath = Join-Path $packageRoot "vendor\\SumatraPDF\\SumatraPDF-3.5.2-64.exe"

if (-not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF was not found: $PdfPath"
}

if (-not (Test-Path -LiteralPath $sumatraPath)) {
    throw "SumatraPDF portable was not found: $sumatraPath"
}

$defaultPrinter = Get-CimInstance Win32_Printer | Where-Object Default -eq $true | Select-Object -First 1
if (-not $defaultPrinter) {
    throw "No default printer is configured."
}

$process = Start-Process -FilePath $sumatraPath -ArgumentList '-print-to-default', '-print-settings', 'fit,paper=A4,color,simplex', '-silent', $PdfPath -PassThru
$process.WaitForExit()
Start-Sleep -Seconds 8

$jobs = @(Get-PrintJob -PrinterName $defaultPrinter.Name -ErrorAction SilentlyContinue | Where-Object { $_.DocumentName -eq $PdfPath } | Select-Object Id,DocumentName,JobStatus,PagesPrinted,SubmittedTime)

[ordered]@{
    ok = ($process.ExitCode -eq 0)
    printer = $defaultPrinter.Name
    exitCode = $process.ExitCode
    pdfPath = $PdfPath
    jobs = $jobs
} | ConvertTo-Json -Depth 6
