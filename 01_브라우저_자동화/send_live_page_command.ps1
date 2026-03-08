$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = (Get-Command python -ErrorAction Stop).Source
$script = Join-Path $scriptRoot "send_live_page_command.py"

$env:PYTHONIOENCODING = "utf-8"
& $python $script @args
