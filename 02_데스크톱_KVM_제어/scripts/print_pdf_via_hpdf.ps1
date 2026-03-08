[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$PdfPath,
    [string]$PrinterName = "SEC842519C6E0ED(C51x Series)",
    [int]$OpenTimeoutSeconds = 12,
    [int]$DialogTimeoutSeconds = 8,
    [int]$QueueTimeoutSeconds = 20,
    [switch]$CloseViewer
)

$ErrorActionPreference = "Stop"

$scriptRoot = Split-Path -Parent $PSCommandPath
$desktopControl = Join-Path $scriptRoot "desktop_control.py"

if (-not (Test-Path -LiteralPath $PdfPath)) {
    throw "PDF was not found: $PdfPath"
}

if (-not (Test-Path -LiteralPath $desktopControl)) {
    throw "desktop_control.py was not found: $desktopControl"
}

$leaf = [System.IO.Path]::GetFileName($PdfPath)
$printDialogText = ([string][char]0xC778) + [char]0xC1C4
$printer = Get-CimInstance Win32_Printer | Where-Object { $_.Name -eq $PrinterName } | Select-Object -First 1
if (-not $printer) {
    throw "Printer was not found: $PrinterName"
}
if ($printer.WorkOffline) {
    throw "Printer is offline: $PrinterName"
}

function Invoke-DesktopJson {
    param(
        [string[]]$Arguments
    )

    $raw = & python $desktopControl @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "desktop_control.py failed: $($Arguments -join ' ')"
    }
    return $raw | ConvertFrom-Json
}

function Get-TargetWindow {
    param(
        [string]$Contains
    )

    $result = Invoke-DesktopJson -Arguments @("list-windows", "--contains", $Contains)
    if (-not $result.ok -or $result.count -lt 1) {
        return $null
    }
    return $result.windows[0]
}

function Wait-ForWindow {
    param(
        [string]$Contains,
        [int]$TimeoutSeconds
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    while ((Get-Date) -lt $deadline) {
        $window = Get-TargetWindow -Contains $Contains
        if ($window) {
            return $window
        }
        Start-Sleep -Milliseconds 400
    }
    return $null
}

function Get-PrinterJobIds {
    param(
        [string]$Name
    )

    return @(
        Get-PrintJob -PrinterName $Name -ErrorAction SilentlyContinue |
            Select-Object -ExpandProperty ID
    )
}

$existingJobIds = Get-PrinterJobIds -Name $PrinterName

Start-Process -FilePath $PdfPath | Out-Null
$window = Wait-ForWindow -Contains $leaf -TimeoutSeconds $OpenTimeoutSeconds
if (-not $window) {
    throw "PDF viewer window did not appear for: $leaf"
}

Invoke-DesktopJson -Arguments @("focus-window", "--contains", $leaf) | Out-Null

# Click inside the document canvas first so Ctrl+P targets the viewer instead of a side pane.
$docX = [int]($window.left + (($window.right - $window.left) * 0.72))
$docY = [int]($window.top + (($window.bottom - $window.top) * 0.50))
Invoke-DesktopJson -Arguments @("click", "--x", $docX.ToString(), "--y", $docY.ToString()) | Out-Null
Start-Sleep -Milliseconds 800
Invoke-DesktopJson -Arguments @("combo", "--keys", "ctrl+p") | Out-Null

$printDialog = Wait-ForWindow -Contains $printDialogText -TimeoutSeconds $DialogTimeoutSeconds
if (-not $printDialog) {
    throw "The print dialog did not appear after Ctrl+P."
}

Invoke-DesktopJson -Arguments @("focus-window", "--contains", $printDialogText) | Out-Null
Start-Sleep -Milliseconds 250
Invoke-DesktopJson -Arguments @("combo", "--keys", "enter") | Out-Null

$deadline = (Get-Date).AddSeconds($QueueTimeoutSeconds)
$matchedJob = $null
while ((Get-Date) -lt $deadline) {
    $jobs = @(Get-PrintJob -PrinterName $PrinterName -ErrorAction SilentlyContinue)
    $matchedJob = @(
        $jobs | Where-Object {
            ($existingJobIds -notcontains $_.ID) -or ($_.DocumentName -like "*$leaf*")
        }
    ) | Sort-Object SubmittedTime -Descending | Select-Object -First 1

    if ($matchedJob) {
        break
    }
    Start-Sleep -Milliseconds 500
}

if (-not $matchedJob) {
    throw "No new print job was observed for $leaf on $PrinterName."
}

if ($CloseViewer) {
    Get-Process Hpdf -ErrorAction SilentlyContinue |
        Where-Object { $_.MainWindowTitle -like "*$leaf*" } |
        Stop-Process -Force -ErrorAction SilentlyContinue
}

[ordered]@{
    ok = $true
    method = "hanpdf-ui"
    pdfPath = $PdfPath
    printer = $PrinterName
    documentWindow = $window
    printDialogSeen = $true
    job = [ordered]@{
        id = $matchedJob.ID
        documentName = $matchedJob.DocumentName
        jobStatus = $matchedJob.JobStatus
        submittedTime = $matchedJob.SubmittedTime
    }
} | ConvertTo-Json -Depth 8
