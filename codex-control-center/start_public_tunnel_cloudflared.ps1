$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $MyInvocation.MyCommand.Path
$scriptPath = Join-Path $root "cloudflared_tunnel_supervisor.py"
if (-not (Test-Path -LiteralPath $scriptPath)) {
    throw "cloudflared_tunnel_supervisor.py not found."
}

$logDir = Join-Path $root "state"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stdoutPath = Join-Path $logDir "cloudflared_supervisor.out.log"
$stderrPath = Join-Path $logDir "cloudflared_supervisor.err.log"

Start-Process -FilePath "python" -ArgumentList @($scriptPath) -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath | Out-Null
