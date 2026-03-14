[CmdletBinding()]
param(
    [string]$Tag = ((Get-Date).ToString("yyyy-MM-dd") + "-remote-zero-cost"),
    [string]$OutputDir
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$pythonExe = (Get-Command python -ErrorAction Stop).Source

if ([string]::IsNullOrWhiteSpace($OutputDir)) {
    $OutputDir = Join-Path $packageRoot "artifacts"
}

$builder = Join-Path $scriptRoot "build_remote_access_zero_cost_report.py"
$previousPythonIO = $env:PYTHONIOENCODING
$env:PYTHONIOENCODING = "utf-8"
$raw = & $pythonExe -X utf8 $builder --tag $Tag --output-dir $OutputDir
if ($null -ne $previousPythonIO) {
    $env:PYTHONIOENCODING = $previousPythonIO
}
else {
    Remove-Item Env:PYTHONIOENCODING -ErrorAction SilentlyContinue
}
if ($LASTEXITCODE -ne 0) {
    throw "Remote access zero-cost HTML build failed."
}

$result = ($raw | Out-String).Trim() | ConvertFrom-Json
$htmlPath = [string]$result.htmlPath
$pdfPath = [System.IO.Path]::ChangeExtension($htmlPath, ".pdf")
$htmlPreviewPath = [System.IO.Path]::ChangeExtension($htmlPath, ".png")
$pdfPreviewPath = [System.IO.Path]::ChangeExtension($htmlPath, ".pdf.png")

$chromeCandidates = @(
    "C:\Program Files\Google\Chrome\Application\chrome.exe",
    "C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"
)
$chromeExe = $chromeCandidates | Where-Object { Test-Path -LiteralPath $_ } | Select-Object -First 1
if (-not $chromeExe) {
    throw "Chrome executable not found for PDF generation."
}

$tempRoot = Join-Path $env:TEMP "codex_report_build"
New-Item -ItemType Directory -Path $tempRoot -Force | Out-Null
$tempHtmlPath = Join-Path $tempRoot "remote_access_zero_cost_report.html"
$tempPdfPath = Join-Path $tempRoot "remote_access_zero_cost_report.pdf"
$tempHtmlPreviewPath = Join-Path $tempRoot "remote_access_zero_cost_report.png"
$tempPdfPreviewPath = Join-Path $tempRoot "remote_access_zero_cost_report_pdf.png"

Copy-Item -LiteralPath $htmlPath -Destination $tempHtmlPath -Force
foreach ($path in @($tempPdfPath, $tempHtmlPreviewPath, $tempPdfPreviewPath)) {
    if (Test-Path -LiteralPath $path) {
        Remove-Item -LiteralPath $path -Force
    }
}

$htmlUri = [System.Uri]::new($tempHtmlPath).AbsoluteUri
& $chromeExe `
    --headless `
    --disable-gpu `
    --allow-file-access-from-files `
    --print-to-pdf="$tempPdfPath" `
    "$htmlUri" | Out-Null

for ($attempt = 1; $attempt -le 20; $attempt++) {
    if (Test-Path -LiteralPath $tempPdfPath) {
        break
    }
    Start-Sleep -Milliseconds 250
}

if (-not (Test-Path -LiteralPath $tempPdfPath)) {
    throw "PDF generation failed: $pdfPath"
}

& $chromeExe `
    --headless `
    --disable-gpu `
    --allow-file-access-from-files `
    --window-size=1440,2400 `
    --screenshot="$tempHtmlPreviewPath" `
    "$htmlUri" | Out-Null

for ($attempt = 1; $attempt -le 20; $attempt++) {
    if (Test-Path -LiteralPath $tempHtmlPreviewPath) {
        break
    }
    Start-Sleep -Milliseconds 200
}

$pdfUri = [System.Uri]::new($tempPdfPath).AbsoluteUri
& $chromeExe `
    --headless `
    --disable-gpu `
    --allow-file-access-from-files `
    --window-size=1440,2400 `
    --screenshot="$tempPdfPreviewPath" `
    "$pdfUri" | Out-Null

Copy-Item -LiteralPath $tempPdfPath -Destination $pdfPath -Force
if (Test-Path -LiteralPath $tempHtmlPreviewPath) {
    Copy-Item -LiteralPath $tempHtmlPreviewPath -Destination $htmlPreviewPath -Force
}
if (Test-Path -LiteralPath $tempPdfPreviewPath) {
    Copy-Item -LiteralPath $tempPdfPreviewPath -Destination $pdfPreviewPath -Force
}

$latestDir = Join-Path $packageRoot "latest"
New-Item -ItemType Directory -Path $latestDir -Force | Out-Null
$latestPdf = Join-Path $latestDir "remote_access_zero_cost_report_latest.pdf"
$latestHtml = Join-Path $latestDir "remote_access_zero_cost_report_latest.html"
$latestHtmlPreview = Join-Path $latestDir "remote_access_zero_cost_report_latest.png"
$latestPdfPreview = Join-Path $latestDir "remote_access_zero_cost_report_latest_pdf.png"

Copy-Item -LiteralPath $pdfPath -Destination $latestPdf -Force
Copy-Item -LiteralPath $htmlPath -Destination $latestHtml -Force
if (Test-Path -LiteralPath $htmlPreviewPath) {
    Copy-Item -LiteralPath $htmlPreviewPath -Destination $latestHtmlPreview -Force
}
if (Test-Path -LiteralPath $pdfPreviewPath) {
    Copy-Item -LiteralPath $pdfPreviewPath -Destination $latestPdfPreview -Force
}

$repoRoot = Split-Path -Parent (Split-Path -Parent $packageRoot)
$controlCenterReportsDir = Join-Path $repoRoot "codex-control-center\\static\\reports"
New-Item -ItemType Directory -Path $controlCenterReportsDir -Force | Out-Null
$webPdf = Join-Path $controlCenterReportsDir "remote_access_zero_cost_report_latest.pdf"
$webHtml = Join-Path $controlCenterReportsDir "remote_access_zero_cost_report_latest.html"
$webPng = Join-Path $controlCenterReportsDir "remote_access_zero_cost_report_latest.png"

Copy-Item -LiteralPath $latestPdf -Destination $webPdf -Force
Copy-Item -LiteralPath $latestHtml -Destination $webHtml -Force
if (Test-Path -LiteralPath $latestHtmlPreview) {
    Copy-Item -LiteralPath $latestHtmlPreview -Destination $webPng -Force
}

[ordered]@{
    ok = $true
    tag = $Tag
    htmlPath = $htmlPath
    pdfPath = $pdfPath
    htmlPreviewPath = if (Test-Path -LiteralPath $htmlPreviewPath) { $htmlPreviewPath } else { "" }
    pdfPreviewPath = if (Test-Path -LiteralPath $pdfPreviewPath) { $pdfPreviewPath } else { "" }
    dataPath = [string]$result.dataPath
    latestHtmlPath = $latestHtml
    latestPdfPath = $latestPdf
    latestHtmlPreviewPath = if (Test-Path -LiteralPath $latestHtmlPreview) { $latestHtmlPreview } else { "" }
    latestPdfPreviewPath = if (Test-Path -LiteralPath $latestPdfPreview) { $latestPdfPreview } else { "" }
    webPdfUrl = "http://127.0.0.1:8787/reports/remote_access_zero_cost_report_latest.pdf"
    webHtmlUrl = "http://127.0.0.1:8787/reports/remote_access_zero_cost_report_latest.html"
    webPreviewUrl = if (Test-Path -LiteralPath $webPng) { "http://127.0.0.1:8787/reports/remote_access_zero_cost_report_latest.png" } else { "" }
    summary = $result.summary
} | ConvertTo-Json -Depth 6
