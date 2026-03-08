[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$QueuePath,
    [string]$ReportTitle = "과금 승인 리스트 보고서",
    [string]$HighlightRequestId
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$approvalRoot = Join-Path $packageRoot "approvals"
$stamp = Get-Date -Format "yyMMdd_HHmmss"
$reportRoot = Join-Path $approvalRoot ("Q" + $stamp)
$htmlPath = Join-Path $reportRoot "spend_queue_report.html"
$pdfPath = Join-Path $reportRoot "spend_queue_report.pdf"
$jsonPath = Join-Path $reportRoot "spend_queue_report.json"
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"

New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null

if (-not (Test-Path -LiteralPath $QueuePath)) {
    throw "Queue file was not found: $QueuePath"
}

$queue = Get-Content -LiteralPath $QueuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$requests = @($queue.requests)
$pending = @($requests | Where-Object { $_.status -eq "pending" })
$approved = @($requests | Where-Object { $_.status -eq "approved" })

function Escape-Html {
    param([string]$Text)
    return [System.Net.WebUtility]::HtmlEncode($Text)
}

function Format-Krw {
    param([double]$Value)
    return ("{0:N0}" -f $Value) + " KRW"
}

function New-RowHtml {
    param($Item)

    $highlight = if ($HighlightRequestId -and $Item.id -eq $HighlightRequestId) { " style='background:#fff7ed;'" } else { "" }
    return "<tr$highlight><td>$(Escape-Html $Item.id)</td><td>$(Escape-Html $Item.title)</td><td>$(Escape-Html $Item.spendSubject)</td><td>$(Escape-Html (Format-Krw ([double]$Item.estimatedCostKRW)))</td><td>$(Escape-Html $Item.expectedBenefit)</td><td>$(Escape-Html $Item.reason)</td><td>$(Escape-Html ($Item.approvedAt ?? ''))</td></tr>"
}

$pendingRows = if ($pending.Count -gt 0) { ($pending | ForEach-Object { New-RowHtml $_ }) -join "`r`n" } else { "<tr><td colspan='7'>대기 중인 과금 요청이 없습니다.</td></tr>" }
$approvedRows = if ($approved.Count -gt 0) { ($approved | ForEach-Object { New-RowHtml $_ }) -join "`r`n" } else { "<tr><td colspan='7'>승인된 과금 요청이 없습니다.</td></tr>" }
$pendingTotal = ($pending | Measure-Object -Property estimatedCostKRW -Sum).Sum
$approvedTotal = ($approved | Measure-Object -Property estimatedCostKRW -Sum).Sum
$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"

$html = @"
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8">
  <title>$(Escape-Html $ReportTitle)</title>
  <style>
    @page { size: A4; margin: 16mm 12mm; }
    body { font-family: "Malgun Gothic", sans-serif; color: #111827; line-height: 1.5; font-size: 10.5pt; }
    h1 { font-size: 20pt; text-align: center; margin: 0 0 4pt 0; }
    .meta { text-align: center; color: #475569; font-size: 9pt; margin-bottom: 12pt; }
    .summary { display: flex; gap: 10pt; margin-bottom: 12pt; }
    .card { flex: 1; border: 1px solid #cbd5e1; border-radius: 10px; padding: 10pt; background: #f8fafc; }
    h2 { font-size: 13.5pt; margin: 14pt 0 6pt 0; border-bottom: 1px solid #cbd5e1; padding-bottom: 4pt; }
    table { width: 100%; border-collapse: collapse; margin-top: 8pt; font-size: 9.3pt; }
    th, td { border: 1px solid #cbd5e1; padding: 5pt 6pt; vertical-align: top; }
    th { background: #e2e8f0; }
    .note { margin-top: 14pt; padding: 8pt 10pt; border: 1px solid #94a3b8; border-radius: 10px; }
  </style>
</head>
<body>
  <h1>$(Escape-Html $ReportTitle)</h1>
  <div class="meta">생성 시각: $(Escape-Html $generatedAt)</div>

  <div class="summary">
    <div class="card">
      <strong>대기 요청 수</strong><br>
      $($pending.Count)건<br>
      총 예산: $(Escape-Html (Format-Krw ([double]($pendingTotal ?? 0))))
    </div>
    <div class="card">
      <strong>승인 요청 수</strong><br>
      $($approved.Count)건<br>
      총 예산: $(Escape-Html (Format-Krw ([double]($approvedTotal ?? 0))))
    </div>
  </div>

  <h2>1. 대기 중인 과금 요청 리스트</h2>
  <table>
    <tr>
      <th>ID</th>
      <th>제목</th>
      <th>과금 대상</th>
      <th>예산</th>
      <th>기대 효익</th>
      <th>판단 근거</th>
      <th>승인 시각</th>
    </tr>
    $pendingRows
  </table>

  <h2>2. 승인된 과금 리스트</h2>
  <table>
    <tr>
      <th>ID</th>
      <th>제목</th>
      <th>과금 대상</th>
      <th>예산</th>
      <th>기대 효익</th>
      <th>판단 근거</th>
      <th>승인 시각</th>
    </tr>
    $approvedRows
  </table>

  <div class="note">
    과금 실행은 이 보고서를 보고 사용자가 채팅으로 승인한 뒤에만 진행합니다. 주식, 매매, 송금, 이체는 이 승인 구조와 별도로 계속 차단합니다.
  </div>
</body>
</html>
"@

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($htmlPath, $html, $utf8Bom)

if (-not (Test-Path $chromePath)) {
    throw "Chrome was not found at '$chromePath'."
}

$tempProfile = Join-Path $env:TEMP ("codex-spend-queue-" + [guid]::NewGuid().ToString())
New-Item -ItemType Directory -Force -Path $tempProfile | Out-Null

try {
    & $chromePath `
        --headless=new `
        --disable-gpu `
        --allow-file-access-from-files `
        --user-data-dir="$tempProfile" `
        --print-to-pdf-no-header `
        --print-to-pdf="$pdfPath" `
        ([System.Uri]::new($htmlPath).AbsoluteUri) | Out-Null
}
finally {
    Start-Sleep -Seconds 2
    Remove-Item -Recurse -Force $tempProfile -ErrorAction SilentlyContinue
}

$payload = [ordered]@{
    queuePath = $QueuePath
    reportTitle = $ReportTitle
    highlightRequestId = $HighlightRequestId
    pendingCount = $pending.Count
    approvedCount = $approved.Count
    pendingTotalKRW = [double]($pendingTotal ?? 0)
    approvedTotalKRW = [double]($approvedTotal ?? 0)
    htmlPath = $htmlPath
    pdfPath = $pdfPath
    generatedAt = $generatedAt
}

Set-Content -LiteralPath $jsonPath -Value ($payload | ConvertTo-Json -Depth 6) -Encoding UTF8
$payload["jsonPath"] = $jsonPath

$payload | ConvertTo-Json -Depth 6
