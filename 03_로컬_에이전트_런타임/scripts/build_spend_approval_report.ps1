[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$QueuePath,
    [string]$ReportTitle,
    [string]$HighlightRequestId,
    [string]$ReportingPolicyPath,
    [string]$GlossaryCatalogPath
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$packageRoot = Split-Path -Parent $scriptRoot
$configRoot = Join-Path $packageRoot "config"
$approvalRoot = Join-Path $packageRoot "approvals"
$stamp = Get-Date -Format "yyMMdd_HHmmss"
$reportRoot = Join-Path $approvalRoot ("Q" + $stamp)
$htmlPath = Join-Path $reportRoot "spend_queue_report.html"
$pdfPath = Join-Path $reportRoot "spend_queue_report.pdf"
$jsonPath = Join-Path $reportRoot "spend_queue_report.json"
$chromePath = "C:\Program Files\Google\Chrome\Application\chrome.exe"

if ([string]::IsNullOrWhiteSpace($ReportTitle)) {
    $ReportTitle = "Spend approval list report"
}

if ([string]::IsNullOrWhiteSpace($ReportingPolicyPath)) {
    $ReportingPolicyPath = Join-Path $configRoot "reporting_policy.json"
}

if ([string]::IsNullOrWhiteSpace($GlossaryCatalogPath)) {
    $GlossaryCatalogPath = Join-Path $configRoot "technical_terms_glossary.json"
}

New-Item -ItemType Directory -Force -Path $reportRoot | Out-Null

if (-not (Test-Path -LiteralPath $QueuePath)) {
    throw "Queue file was not found: $QueuePath"
}

function Escape-Html {
    param([AllowNull()][string]$Text)

    if ($null -eq $Text) {
        return ""
    }

    return [System.Net.WebUtility]::HtmlEncode($Text)
}

function Format-Krw {
    param([AllowNull()][double]$Value)

    return ("{0:N0}" -f $Value) + " KRW"
}

function Get-OptionalJson {
    param([string]$Path)

    if ([string]::IsNullOrWhiteSpace($Path) -or -not (Test-Path -LiteralPath $Path)) {
        return $null
    }

    return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json
}

function Get-NumberOrZero {
    param($Value)

    if ($null -eq $Value -or [string]::IsNullOrWhiteSpace([string]$Value)) {
        return 0.0
    }

    return [double]$Value
}

function Convert-RequestToRowHtml {
    param(
        $Item,
        [string]$HighlightRequestId
    )

    $highlight = if ($HighlightRequestId -and $Item.id -eq $HighlightRequestId) {
        " style='background:#fff7ed;'"
    }
    else {
        ""
    }

    $approvedAt = if ($null -ne $Item.approvedAt) { [string]$Item.approvedAt } else { "" }
    $cost = Get-NumberOrZero -Value $Item.estimatedCostKRW

    return @(
        "<tr$highlight>",
        "<td>$(Escape-Html ([string]$Item.id))</td>",
        "<td>$(Escape-Html ([string]$Item.title))</td>",
        "<td>$(Escape-Html ([string]$Item.spendSubject))</td>",
        "<td>$(Escape-Html (Format-Krw $cost))</td>",
        "<td>$(Escape-Html ([string]$Item.expectedBenefit))</td>",
        "<td>$(Escape-Html ([string]$Item.reason))</td>",
        "<td>$(Escape-Html $approvedAt)</td>",
        "</tr>"
    ) -join ""
}

function Get-GlossaryMatches {
    param(
        [string]$Text,
        [object[]]$Catalog
    )

    $glossaryMatches = New-Object System.Collections.Generic.List[object]

    if ([string]::IsNullOrWhiteSpace($Text) -or $null -eq $Catalog) {
        return @()
    }

    foreach ($entry in $Catalog) {
        $candidates = New-Object System.Collections.Generic.List[string]

        if ($null -ne $entry.term -and -not [string]::IsNullOrWhiteSpace([string]$entry.term)) {
            [void]$candidates.Add([string]$entry.term)
        }

        foreach ($alias in @($entry.aliases)) {
            if ($null -ne $alias -and -not [string]::IsNullOrWhiteSpace([string]$alias)) {
                [void]$candidates.Add([string]$alias)
            }
        }

        $matchedBy = @()
        foreach ($candidate in ($candidates | Select-Object -Unique)) {
            if ($Text -match [regex]::Escape($candidate)) {
                $matchedBy += $candidate
            }
        }

        if ($matchedBy.Count -gt 0) {
            $glossaryMatches.Add([pscustomobject]@{
                id = [string]$entry.id
                term = [string]$entry.term
                matchedBy = @($matchedBy | Select-Object -Unique)
                meaning = [string]$entry.meaning
                plainExplanation = [string]$entry.plainExplanation
                whyItMatters = [string]$entry.whyItMatters
                projectContext = [string]$entry.projectContext
            })
        }
    }

    return @($glossaryMatches | Sort-Object term)
}

function Convert-GlossaryToHtml {
    param(
        [object[]]$GlossaryItems,
        [string]$SectionTitle
    )

    if ($null -eq $GlossaryItems -or $GlossaryItems.Count -eq 0) {
        return ""
    }

    $itemsHtml = foreach ($item in $GlossaryItems) {
        $matchedByText = if ($item.matchedBy.Count -gt 0) {
            $quotedMatches = @($item.matchedBy | ForEach-Object { "'{0}'" -f $_ })
            "본문에서 확인된 표기: " + ($quotedMatches -join ", ")
        }
        else {
            ""
        }

@"
  <div class="glossary-item">
    <h3>$(Escape-Html $item.term)</h3>
    <p><strong>정확한 의미</strong>: $(Escape-Html $item.meaning)</p>
    <p><strong>쉽게 말해</strong>: $(Escape-Html $item.plainExplanation)</p>
    <p><strong>이 보고서에서 중요한 이유</strong>: $(Escape-Html $item.whyItMatters)</p>
    <p><strong>이 시스템에서의 맥락</strong>: $(Escape-Html $item.projectContext)</p>
    <p class="glossary-match">$(Escape-Html $matchedByText)</p>
  </div>
"@
    }

@"
  <h2 class="appendix-title">$(Escape-Html $SectionTitle)</h2>
  <div class="appendix-note">기술 용어를 모르는 사람도 보고서를 이해할 수 있도록, 본문에서 쓰인 핵심 용어를 자세히 풀어 썼습니다.</div>
$($itemsHtml -join "`r`n")
"@
}

$queue = Get-Content -LiteralPath $QueuePath -Raw -Encoding UTF8 | ConvertFrom-Json
$requests = @($queue.requests)
$pending = @($requests | Where-Object { $_.status -eq "pending" })
$approved = @($requests | Where-Object { $_.status -eq "approved" })
$pendingTotal = ($pending | Measure-Object -Property estimatedCostKRW -Sum).Sum
$approvedTotal = ($approved | Measure-Object -Property estimatedCostKRW -Sum).Sum
$generatedAt = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
$pendingTotalValue = Get-NumberOrZero -Value $pendingTotal
$approvedTotalValue = Get-NumberOrZero -Value $approvedTotal

$pendingRows = if ($pending.Count -gt 0) {
    ($pending | ForEach-Object { Convert-RequestToRowHtml -Item $_ -HighlightRequestId $HighlightRequestId }) -join "`r`n"
}
else {
    "<tr><td colspan='7'>대기 중인 과금 요청이 없습니다.</td></tr>"
}

$approvedRows = if ($approved.Count -gt 0) {
    ($approved | ForEach-Object { Convert-RequestToRowHtml -Item $_ -HighlightRequestId $HighlightRequestId }) -join "`r`n"
}
else {
    "<tr><td colspan='7'>승인된 과금 요청이 없습니다.</td></tr>"
}

$reportingPolicy = Get-OptionalJson -Path $ReportingPolicyPath
$rawGlossaryCatalog = Get-OptionalJson -Path $GlossaryCatalogPath
$glossaryCatalog = @($rawGlossaryCatalog | ForEach-Object { $_ })
$glossarySectionTitle = if ($null -ne $reportingPolicy -and $null -ne $reportingPolicy.appendix.sectionTitle) {
    [string]$reportingPolicy.appendix.sectionTitle
}
else {
    "부록 A. 용어 설명"
}

$textSegments = New-Object System.Collections.Generic.List[string]
[void]$textSegments.Add($ReportTitle)
[void]$textSegments.Add("API 구독, 라이선스, 업그레이드 같은 과금 항목은 사용자 승인 뒤에만 실행한다.")

foreach ($item in $requests) {
    foreach ($value in @(
        [string]$item.title,
        [string]$item.spendSubject,
        [string]$item.expectedBenefit,
        [string]$item.reason
    )) {
        if (-not [string]::IsNullOrWhiteSpace($value)) {
            [void]$textSegments.Add($value)
        }
    }
}

$glossaryItems = @()
if ($null -ne $reportingPolicy -and $reportingPolicy.appendix.enabledWhenTechnicalTermsExist -and $glossaryCatalog.Count -gt 0) {
    $reportText = ($textSegments | Select-Object -Unique) -join "`n"
    $glossaryItems = @(Get-GlossaryMatches -Text $reportText -Catalog $glossaryCatalog)
}

$glossaryHtml = Convert-GlossaryToHtml -GlossaryItems $glossaryItems -SectionTitle $glossarySectionTitle

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
    h2.appendix-title { break-before: page; }
    h3 { font-size: 11.5pt; margin: 10pt 0 4pt 0; }
    table { width: 100%; border-collapse: collapse; margin-top: 8pt; font-size: 9.3pt; }
    th, td { border: 1px solid #cbd5e1; padding: 5pt 6pt; vertical-align: top; }
    th { background: #e2e8f0; }
    .note { margin-top: 14pt; padding: 8pt 10pt; border: 1px solid #94a3b8; border-radius: 10px; }
    .appendix-note { margin-top: 4pt; color: #334155; }
    .glossary-item { margin-top: 10pt; padding: 10pt; border: 1px solid #cbd5e1; border-radius: 10px; background: #fcfcfd; }
    .glossary-item p { margin: 3pt 0; }
    .glossary-match { color: #475569; font-size: 9pt; }
  </style>
</head>
<body>
  <h1>$(Escape-Html $ReportTitle)</h1>
  <div class="meta">생성 시각: $(Escape-Html $generatedAt)</div>

  <div class="summary">
    <div class="card">
      <strong>대기 요청 수</strong><br>
      $($pending.Count)건<br>
      총 예산: $(Escape-Html (Format-Krw $pendingTotalValue))
    </div>
    <div class="card">
      <strong>승인 요청 수</strong><br>
      $($approved.Count)건<br>
      총 예산: $(Escape-Html (Format-Krw $approvedTotalValue))
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

  <h2>2. 승인된 과금 요청 리스트</h2>
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
    과금 실행은 이 보고서를 보고 사용자가 채팅으로 승인한 뒤에만 진행합니다. 주식, 매매, 송금, 이체, 결제 같은 금융 실행은 별도 승인 구조로 계속 차단합니다.
  </div>

$glossaryHtml
</body>
</html>
"@

$utf8Bom = New-Object System.Text.UTF8Encoding($true)
[System.IO.File]::WriteAllText($htmlPath, $html, $utf8Bom)

if (-not (Test-Path -LiteralPath $chromePath)) {
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
    pendingTotalKRW = $pendingTotalValue
    approvedTotalKRW = $approvedTotalValue
    htmlPath = $htmlPath
    pdfPath = $pdfPath
    generatedAt = $generatedAt
    reportingPolicyPath = $ReportingPolicyPath
    glossaryCatalogPath = $GlossaryCatalogPath
    glossaryItems = @($glossaryItems | ForEach-Object {
        [ordered]@{
            id = $_.id
            term = $_.term
            matchedBy = $_.matchedBy
        }
    })
}

Set-Content -LiteralPath $jsonPath -Value ($payload | ConvertTo-Json -Depth 8) -Encoding UTF8
$payload["jsonPath"] = $jsonPath

$payload | ConvertTo-Json -Depth 8
