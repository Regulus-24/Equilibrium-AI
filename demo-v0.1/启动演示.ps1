$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$pythonCommand = Get-Command python -ErrorAction SilentlyContinue
$bundledPython = 'C:\Users\Administrator\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
Write-Host 'Open http://127.0.0.1:18128 after start. Ctrl+C stops the local demo.'
if ($pythonCommand) { & $pythonCommand.Source server.py }
elseif (Test-Path -LiteralPath $bundledPython) { & $bundledPython server.py }
else { throw 'Python 3.11+ is required.' }

