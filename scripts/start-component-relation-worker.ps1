$ErrorActionPreference = "Stop"

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl
$pythonExecutable = Get-CtbzPythonExecutable
$env:PYTHONPATH = Join-Path $script:CtbzProjectRoot "backend"

Write-Host "Python Component Relation Worker"
Write-Host "Python: $pythonExecutable"

Set-Location (Join-Path $script:CtbzProjectRoot "backend")
& $pythonExecutable -m src.tools.run_component_relation_worker
exit $LASTEXITCODE
