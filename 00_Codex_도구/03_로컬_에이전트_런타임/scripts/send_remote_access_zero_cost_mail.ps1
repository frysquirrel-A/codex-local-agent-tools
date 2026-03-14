[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PublicUrl,
    [Parameter(Mandatory = $true)]
    [string]$AccessCode,
    [Parameter(Mandatory = $true)]
    [string]$ReportPdfUrl,
    [string]$To = "emnogib@icloud.com",
    [string]$Subject = "Codex remote access link and zero-cost report"
)

$ErrorActionPreference = "Stop"

$sender = Join-Path $PSScriptRoot "send_gmail_direct_macro.ps1"
if (-not (Test-Path -LiteralPath $sender)) {
    throw "send_gmail_direct_macro.ps1 not found."
}

$body = @"
Codex remote access information

1. Access link
$PublicUrl

2. Access code
$AccessCode

3. Zero-cost build report PDF
$ReportPdfUrl

Summary:
- This link is not Firebase or GitHub Pages hosting.
- It is the local Command Center server on this PC exposed through a free public tunnel.
- That is why it works without extra hosting cost.
"@

Start-Process "https://mail.google.com/mail/u/0/#inbox" | Out-Null
Start-Sleep -Seconds 8

& $sender -To $To -Subject $Subject -Body $body
