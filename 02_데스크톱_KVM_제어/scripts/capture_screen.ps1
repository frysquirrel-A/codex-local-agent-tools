param(
    [string]$OutPath = (Join-Path $PSScriptRoot "..\\captures\\screen.png")
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Drawing
Add-Type -AssemblyName System.Windows.Forms

$resolvedOut = [System.IO.Path]::GetFullPath($OutPath)
$outDir = Split-Path -Parent $resolvedOut
if (-not (Test-Path -LiteralPath $outDir)) {
    New-Item -ItemType Directory -Path $outDir | Out-Null
}

function Save-BoundsImage {
    param(
        [System.Drawing.Rectangle]$Bounds,
        [string]$Path
    )

    $bitmap = New-Object System.Drawing.Bitmap $Bounds.Width, $Bounds.Height
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    try {
        $graphics.CopyFromScreen($Bounds.Left, $Bounds.Top, 0, 0, $bitmap.Size)
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    }
    finally {
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

try {
    $bounds = [System.Windows.Forms.SystemInformation]::VirtualScreen
    Save-BoundsImage -Bounds $bounds -Path $resolvedOut
}
catch {
    # Some elevated or mixed-desktop sessions reject virtual-screen capture.
    $primaryBounds = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
    Save-BoundsImage -Bounds $primaryBounds -Path $resolvedOut
}

Write-Output $resolvedOut
