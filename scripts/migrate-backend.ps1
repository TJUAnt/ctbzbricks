$ErrorActionPreference = "Stop"

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDirectory

if ($env:PYTHON_BIN) {
  $pythonExecutable = $env:PYTHON_BIN
} elseif (Test-Path (Join-Path $projectRoot ".venv-app\Scripts\python.exe")) {
  $pythonExecutable = Join-Path $projectRoot ".venv-app\Scripts\python.exe"
} elseif (Test-Path (Join-Path $projectRoot ".venv\Scripts\python.exe")) {
  $pythonExecutable = Join-Path $projectRoot ".venv\Scripts\python.exe"
} else {
  $pythonExecutable = "python"
}

$backendDirectory = Join-Path $projectRoot "backend"
$env:PYTHONPATH = $backendDirectory

Write-Host "Applying backend database migrations..."
Write-Host "Python: $pythonExecutable"
Set-Location $backendDirectory
& $pythonExecutable -m alembic -c alembic.ini upgrade head
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}
