$ErrorActionPreference = "Stop"

function Require-ConfigValue($Value, $Name) {
  if ($null -eq $Value -or $Value -eq "") {
    throw "Missing required configuration: $Name"
  }
  return $Value
}

$scriptDirectory = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptDirectory
$configPath = Join-Path $scriptDirectory "dev.config.json"
$config = Get-Content -Path $configPath -Raw -Encoding UTF8 | ConvertFrom-Json
$backendDirectory = Join-Path $projectRoot (Require-ConfigValue $config.backend.workingDirectory "backend.workingDirectory")

Set-Location $backendDirectory
$env:PYTHONPATH = Require-ConfigValue $config.backend.pythonPath "backend.pythonPath"

& (Require-ConfigValue $config.backend.pythonExecutable "backend.pythonExecutable") `
  -m uvicorn `
  (Require-ConfigValue $config.backend.module "backend.module") `
  --host (Require-ConfigValue $config.backend.host "backend.host") `
  --port (Require-ConfigValue $config.backend.port "backend.port")
