# HusCC kurulumu (Windows / PowerShell)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

$py = "python"
if (-not (Get-Command python -ErrorAction SilentlyContinue)) {
  if (Get-Command py -ErrorAction SilentlyContinue) { $py = "py" }
  else { Write-Host "Python 3.10+ kurulu degil: https://www.python.org/downloads/"; exit 1 }
}

& $py bootstrap.py @args
Write-Host ""
Write-Host "Kisayol icin bu oturumda:  `$env:PATH = `"$root\.venv\Scripts;`$env:PATH`""
