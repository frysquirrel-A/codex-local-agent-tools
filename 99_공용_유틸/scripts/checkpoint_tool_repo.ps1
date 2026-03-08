[CmdletBinding()]
param(
    [string]$Message,
    [switch]$NoPush
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$utilsRoot = Split-Path -Parent $scriptRoot
$toolRoot = Split-Path -Parent $utilsRoot

if (-not (Test-Path -LiteralPath (Join-Path $toolRoot ".git"))) {
    throw "Git repository was not found at $toolRoot"
}

if ([string]::IsNullOrWhiteSpace($Message)) {
    $Message = "Checkpoint $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
}

$statusBefore = git -C $toolRoot status --short
if (-not $statusBefore) {
    [pscustomobject]@{
        ok = $true
        repo = $toolRoot
        changed = $false
        committed = $false
        pushed = $false
        message = "No changes to commit."
    } | ConvertTo-Json -Depth 4
    exit 0
}

git -C $toolRoot add -A

$staged = git -C $toolRoot diff --cached --name-only
if (-not $staged) {
    [pscustomobject]@{
        ok = $true
        repo = $toolRoot
        changed = $true
        committed = $false
        pushed = $false
        message = "Nothing staged after git add."
    } | ConvertTo-Json -Depth 4
    exit 0
}

git -C $toolRoot commit -m $Message | Out-Null
$commit = (git -C $toolRoot rev-parse --short HEAD).Trim()
$branch = (git -C $toolRoot branch --show-current).Trim()

$pushed = $false
if (-not $NoPush) {
    git -C $toolRoot push origin $branch | Out-Null
    $pushed = $true
}

[pscustomobject]@{
    ok = $true
    repo = $toolRoot
    changed = $true
    committed = $true
    pushed = $pushed
    branch = $branch
    commit = $commit
    message = $Message
} | ConvertTo-Json -Depth 4
