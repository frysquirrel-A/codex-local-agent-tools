[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PdfPath,
    [string]$PrinterName = "SEC842519C6E0ED(C51x Series)",
    [int]$QueueTimeoutSeconds = 20
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $PSCommandPath
$toolRoot = Split-Path -Parent $scriptRoot
$toolParent = Split-Path -Parent $toolRoot
$sharedRoot = Get-ChildItem -LiteralPath $toolParent -Directory |
    Where-Object { $_.Name -like "99_*" } |
    Select-Object -First 1 -ExpandProperty FullName

if (-not $sharedRoot) {
    throw "Shared utility directory was not found under: $toolParent"
}

$sumatraExe = Join-Path $sharedRoot "SumatraPDF-3.5.2-64\SumatraPDF-3.5.2-64.exe"

if (-not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF was not found: $PdfPath"
}

if (-not (Test-Path -LiteralPath $sumatraExe)) {
    throw "Sumatra executable was not found: $sumatraExe"
}

$resolvedPdf = [System.IO.Path]::GetFullPath($PdfPath)
$leaf = [System.IO.Path]::GetFileName($resolvedPdf)
$printer = Get-CimInstance Win32_Printer | Where-Object { $_.Name -eq $PrinterName } | Select-Object -First 1
if (-not $printer) {
    throw "Printer was not found: $PrinterName"
}
if ($printer.WorkOffline) {
    throw "Printer is offline: $PrinterName"
}

$existingJobIds = @(
    Get-PrintJob -PrinterName $PrinterName -ErrorAction SilentlyContinue |
        Select-Object -ExpandProperty ID
)

$process = Start-Process -FilePath $sumatraExe -ArgumentList @("-print-to", $PrinterName, $resolvedPdf) -PassThru -Wait
$deadline = (Get-Date).AddSeconds($QueueTimeoutSeconds)
$matchedJob = $null

while ((Get-Date) -lt $deadline) {
    $jobs = @(Get-PrintJob -PrinterName $PrinterName -ErrorAction SilentlyContinue)
    $matchedJob = @(
        $jobs | Where-Object {
            ($existingJobIds -notcontains $_.ID) -or
            ($_.DocumentName -eq $resolvedPdf) -or
            ($_.DocumentName -like "*$leaf*")
        }
    ) | Sort-Object SubmittedTime -Descending | Select-Object -First 1

    if ($matchedJob) {
        break
    }

    Start-Sleep -Milliseconds 500
}

if (-not $matchedJob) {
    throw "No new print job was observed for $leaf on $PrinterName. Sumatra exit code: $($process.ExitCode)"
}

[ordered]@{
    ok = $true
    method = "sumatra-cli"
    pdfPath = $resolvedPdf
    printer = $PrinterName
    sumatraExe = $sumatraExe
    processExitCode = $process.ExitCode
    job = [ordered]@{
        id = $matchedJob.ID
        documentName = $matchedJob.DocumentName
        jobStatus = $matchedJob.JobStatus
        submittedTime = $matchedJob.SubmittedTime
        pagesPrinted = $matchedJob.PagesPrinted
        totalPages = $matchedJob.TotalPages
    }
} | ConvertTo-Json -Depth 8
