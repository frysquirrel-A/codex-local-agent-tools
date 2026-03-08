param(
    [string]$Title = "Codex Approval",
    [string]$Message = "Allow this action?",
    [ValidateSet("read_only", "caution", "critical")]
    [string]$Level = "critical"
)

Add-Type -AssemblyName System.Windows.Forms

$icon = [System.Windows.Forms.MessageBoxIcon]::Question
if ($Level -eq "critical") {
    $icon = [System.Windows.Forms.MessageBoxIcon]::Warning
}

$result = [System.Windows.Forms.MessageBox]::Show(
    $Message,
    $Title,
    [System.Windows.Forms.MessageBoxButtons]::YesNo,
    $icon
)

if ($result -eq [System.Windows.Forms.DialogResult]::Yes) {
    Write-Output '{"ok":true,"approved":true}'
    exit 0
}

Write-Output '{"ok":false,"approved":false,"reason":"User denied approval."}'
exit 1
