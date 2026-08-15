$ErrorActionPreference = "Stop"

function Require-ConfigValue($Value, $Name) {
  if ($null -eq $Value -or $Value -eq "") {
    throw "Missing required configuration: $Name"
  }
  return $Value
}

. (Join-Path $PSScriptRoot "dev-env.ps1")
Import-CtbzDevEnvironment
Assert-CtbzDatabaseUrl

$configPath = Join-Path $PSScriptRoot "dev.config.json"
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$backendDirectory = Join-Path $script:CtbzProjectRoot (Require-ConfigValue $config.backend.workingDirectory "backend.workingDirectory")
$pythonExecutable = Get-CtbzPythonExecutable
$env:PYTHONPATH = $backendDirectory

Set-Location $backendDirectory
& $pythonExecutable `
  -m uvicorn `
  (Require-ConfigValue $config.backend.module "backend.module") `
  --host (Require-ConfigValue $config.backend.host "backend.host") `
  --port (Require-ConfigValue $config.backend.port "backend.port") `
  --reload
exit $LASTEXITCODE
